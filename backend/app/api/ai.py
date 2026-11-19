"""The assistant's endpoints.

Replies stream as Server-Sent Events: ``message_start``, ``token`` (text as it
is written), ``tool_start``/``tool_end`` (what the assistant is looking up or
proposing), ``block`` (a table, chart, file, link or action card), ``error``
and ``message_end`` (the stored message).
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ..database import get_db
from ..errors import NotFoundError, ValidationError
from ..models import AiAction, AiConversation, AiFile, AiMessage, AiToolCall, User, utcnow
from ..services import auth as auth_service
from ..ai import actions, agent, catalog, documents, provider
from .auth import require_user

router = APIRouter(prefix="/api/ai", tags=["assistant"])


class PageContext(BaseModel):
    path: str = Field(max_length=300)
    title: Optional[str] = Field(default=None, max_length=200)
    record: Optional[Dict[str, Any]] = None


class MessageIn(BaseModel):
    text: str = Field(default="", max_length=20000)
    attachments: List[uuid.UUID] = Field(default_factory=list, max_length=documents.MAX_FILES_PER_MESSAGE)
    context: Optional[PageContext] = None


class ConversationIn(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)


def _factory(db: Session):
    """Sessions for the worker thread, on the same database as this request."""
    return sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False, future=True)


def _conversation(db: Session, conversation_id: uuid.UUID, user: User) -> AiConversation:
    conversation = db.get(AiConversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise NotFoundError("Conversation not found.")
    return conversation


def _sse(generator) -> StreamingResponse:
    return StreamingResponse(generator, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- Status and capabilities ----------------------------------------------------


@router.get("/status")
def status(db: Session = Depends(get_db)):
    """Whether the assistant can answer (live, development mode or not
    configured). Never includes credentials."""
    return provider.status(db)


@router.get("/models")
def models(db: Session = Depends(get_db)):
    """Gemini models the saved key can use (the built-in list without a key)."""
    return provider.list_models(db)


@router.get("/capabilities")
def capabilities():
    """What the assistant can do, by area, and which actions need confirmation."""
    groups: Dict[str, List[Dict[str, str]]] = {}
    for operation in catalog.OPERATIONS:
        groups.setdefault(operation.group, []).append(
            {"name": operation.name, "label": operation.label, "risk": operation.risk, "description": operation.description}
        )
    return {"groups": groups, "tool_count": len(catalog.OPERATIONS) + 6}


# --- Conversations --------------------------------------------------------------


@router.get("/conversations")
def list_conversations(limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db),
                       user: User = Depends(require_user)):
    rows = db.execute(
        select(AiConversation, func.count(AiMessage.id))
        .outerjoin(AiMessage, AiMessage.conversation_id == AiConversation.id)
        .where(AiConversation.user_id == user.id)
        .group_by(AiConversation.id)
        .order_by(AiConversation.updated_at.desc())
        .limit(limit)
    ).all()
    return [
        {"id": str(c.id), "title": c.title, "updated_at": c.updated_at, "created_at": c.created_at, "messages": count}
        for c, count in rows
    ]


@router.post("/conversations", status_code=201)
def create_conversation(payload: ConversationIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    conversation = AiConversation(user_id=user.id, title=(payload.title or "New chat").strip()[:255] or "New chat")
    db.add(conversation)
    db.commit()
    return {"id": str(conversation.id), "title": conversation.title, "updated_at": conversation.updated_at,
            "created_at": conversation.created_at, "messages": 0}


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_user)):
    conversation = _conversation(db, conversation_id, user)
    messages = db.execute(
        select(AiMessage).where(AiMessage.conversation_id == conversation.id, AiMessage.role != "event")
        .order_by(AiMessage.created_at)
    ).scalars().all()
    pending = db.execute(
        select(AiAction.id).where(AiAction.conversation_id == conversation.id, AiAction.status == "pending")
    ).scalars().all()
    return {
        "id": str(conversation.id),
        "title": conversation.title,
        "updated_at": conversation.updated_at,
        "messages": [agent.message_view(message) for message in messages],
        "pending_actions": [str(item) for item in pending],
    }


@router.patch("/conversations/{conversation_id}")
def rename_conversation(conversation_id: uuid.UUID, payload: ConversationIn, db: Session = Depends(get_db),
                        user: User = Depends(require_user)):
    conversation = _conversation(db, conversation_id, user)
    title = (payload.title or "").strip()
    if not title:
        raise ValidationError("Give the conversation a name.")
    conversation.title = title[:255]
    db.commit()
    return {"id": str(conversation.id), "title": conversation.title}


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_user)):
    conversation = _conversation(db, conversation_id, user)
    db.delete(conversation)
    db.commit()
    return Response(status_code=204)


@router.post("/conversations/{conversation_id}/messages")
def send_message(conversation_id: uuid.UUID, payload: MessageIn, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_user)):
    """Send a message; the reply streams back as Server-Sent Events."""
    conversation = _conversation(db, conversation_id, user)
    text = payload.text.strip()
    if not text and not payload.attachments:
        raise ValidationError("Write a message or attach a file.")
    attachments = []
    for file_id in payload.attachments:
        file = db.get(AiFile, file_id)
        if file is None or file.user_id != user.id or file.kind != "upload":
            raise NotFoundError("An attached file was not found.")
        file.conversation_id = conversation.id
        attachments.append({"id": str(file.id), "filename": file.filename, "mime_type": file.mime_type, "size": file.size_bytes})
    # Spreadsheets become datasets now, so every later turn can use them.
    datasets: Dict[str, Any] = {}
    for item in attachments:
        file = db.get(AiFile, uuid.UUID(item["id"]))
        if file.mime_type in documents.SHEETS:
            try:
                _, made = documents.for_model(item, file.data)
            except Exception:
                raise ValidationError("{} could not be read as a spreadsheet.".format(file.filename))
            datasets.update({dataset["id"]: dataset for dataset in made})
    context = payload.context.model_dump() if payload.context else None
    message = AiMessage(conversation_id=conversation.id, role="user", content=text,
                        attachments_json=json.dumps(attachments) if attachments else None,
                        context_json=json.dumps(context) if context else None,
                        steps_json=json.dumps({"datasets": datasets}, default=str) if datasets else None)
    db.add(message)
    if conversation.title == "New chat":
        base = text or (attachments[0]["filename"] if attachments else "New chat")
        conversation.title = (base[:60] + ("…" if len(base) > 60 else "")) or "New chat"
    conversation.updated_at = utcnow()
    db.commit()
    user_view = agent.message_view(message)
    factory = _factory(db)
    cookie = request.cookies.get(auth_service.COOKIE)
    user_id, username, conv_id = user.id, user.username, conversation.id

    def start(emit):
        emit("user_message", user_view)
        agent.respond(factory, conv_id, user_id, username, cookie, context, emit)

    return _sse(agent.stream(start))


# --- Actions --------------------------------------------------------------------


@router.post("/actions/{action_id}/confirm")
def confirm_action(action_id: uuid.UUID, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_user)):
    """Run a proposed change, then let the assistant report the real outcome."""
    action = db.get(AiAction, action_id)
    if action is None or action.user_id != user.id:
        raise NotFoundError("That proposed change was not found.")
    if action.status != "pending":
        raise ValidationError("This change was already {}.".format(action.status))
    factory = _factory(db)
    cookie = request.cookies.get(auth_service.COOKIE)
    user_id, username, conversation_id = user.id, user.username, action.conversation_id

    def start(emit):
        emit("action_update", {"action_id": str(action_id), "status": "running"})
        outcome = actions.execute(factory, action_id, user_id, cookie)
        emit("action_update", {"action_id": str(action_id), "status": outcome["status"], "error": outcome.get("error"),
                               "result": outcome.get("result_summary"), "link": outcome.get("link")})
        session = factory()
        try:
            actions.record_outcome(session, action_id, outcome)
            still_pending = session.execute(
                select(func.count()).select_from(AiAction)
                .where(AiAction.conversation_id == conversation_id, AiAction.status == "pending")
            ).scalar_one()
        finally:
            session.close()
        if still_pending:
            # Wait for the user to decide on the rest before the assistant speaks again.
            emit("idle", {"pending": still_pending})
            return
        agent.respond(factory, conversation_id, user_id, username, cookie, None, emit)

    return _sse(agent.stream(start))


@router.post("/actions/{action_id}/cancel")
def cancel_action(action_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_user)):
    action = actions.cancel(db, action_id, user.id)
    return {"action_id": str(action.id), "status": action.status}


# --- Files ----------------------------------------------------------------------


@router.post("/files", status_code=201)
async def upload_file(file: UploadFile = File(...), conversation_id: Optional[str] = Form(default=None),
                      db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Attach a file (PDF, image, spreadsheet, text). Up to 15 MB."""
    data = await file.read(documents.MAX_BYTES + 1)
    mime = documents.check(file.filename or "file", file.content_type or "", len(data))
    conv = None
    if conversation_id:
        conv = _conversation(db, uuid.UUID(conversation_id), user).id
    row = AiFile(user_id=user.id, conversation_id=conv, kind="upload", filename=(file.filename or "file")[:255],
                 mime_type=mime, size_bytes=len(data), data=data)
    db.add(row)
    db.commit()
    return {"id": str(row.id), "filename": row.filename, "mime_type": row.mime_type, "size": row.size_bytes}


@router.get("/files/{file_id}")
def download_file(file_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_user)):
    row = db.get(AiFile, file_id)
    if row is None or row.user_id != user.id:
        raise NotFoundError("File not found.")
    disposition = "inline" if row.mime_type == "application/pdf" or row.mime_type.startswith("image/") else "attachment"
    return Response(content=row.data, media_type=row.mime_type, headers={
        "Content-Disposition": "{}; filename*=UTF-8''{}".format(disposition, quote(row.filename)),
        "Cache-Control": "private, max-age=3600",
    })


# --- Audit ----------------------------------------------------------------------


@router.get("/activity")
def activity(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db),
             user: User = Depends(require_user)):
    """Every tool the assistant ran: yours, or everyone's for an administrator."""
    stmt = select(AiToolCall, User.username).outerjoin(User, AiToolCall.user_id == User.id)
    if not user.is_admin:
        stmt = stmt.where(AiToolCall.user_id == user.id)
    rows = db.execute(stmt.order_by(AiToolCall.created_at.desc()).limit(limit)).all()
    return [
        {"id": str(call.id), "user": username, "tool": call.tool, "route": call.route, "ok": call.ok,
         "status_code": call.status_code, "error": call.error, "duration_ms": call.duration_ms,
         "created_at": call.created_at, "conversation_id": str(call.conversation_id) if call.conversation_id else None}
        for call, username in rows
    ]
