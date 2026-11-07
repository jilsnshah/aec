"""Messages arriving from WhatsApp or email, and handing them to the AI agent.

Both channels go through here: record the message once (a repeat delivery is
ignored), then let the enquiry agent read it and store what it decided. Each
step commits on its own, so a message that fails to process is still on record
with the error.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..database import SessionLocal, begin_write
from ..models import InboundMessage
from . import ai_agent
from . import integration_settings as settings_service
from .common import windowed

logger = logging.getLogger(__name__)

#: Builds the chat model from its id, with the server's credentials. Tests replace it.
model_factory: Callable[[str], Any] = ai_agent.chat_model
#: Opens a session for background work, outside any request. Tests replace it.
session_factory: Callable[[], Session] = SessionLocal


def record(
    session: Session,
    channel: str,
    external_id: str,
    sender: str,
    body: str,
    sender_name: Optional[str] = None,
    subject: Optional[str] = None,
    received_at: Optional[datetime] = None,
) -> Optional[InboundMessage]:
    """Store a message. Returns None when this message was already received."""
    try:
        begin_write(session)
        message = InboundMessage(
            channel=channel,
            external_id=external_id[:255],
            sender=sender[:255],
            sender_name=(sender_name or None) and sender_name[:255],
            subject=(subject or None) and subject[:500],
            body=body,
            received_at=received_at or datetime.now(timezone.utc),
            status="pending",
        )
        session.add(message)
        session.commit()
    except IntegrityError:
        session.rollback()
        logger.info("Ignoring repeat delivery of %s message %s", channel, external_id)
        return None
    except Exception:
        session.rollback()
        raise
    return message


def process(message_id: uuid.UUID) -> None:
    """Let the agent read one recorded message. Runs in the background."""
    session = session_factory()
    try:
        message = session.get(InboundMessage, message_id)
        if message is None or message.status != "pending":
            return
        ai = settings_service.get(session, settings_service.AI)
        if not ai.enabled:
            _finish(session, message, "skipped", summary="AI is switched off, so nobody read this message.")
            return

        context = ai_agent.InboundContext(
            channel=message.channel,
            sender=message.sender,
            sender_name=message.sender_name,
            subject=message.subject,
        )
        try:
            outcome = ai_agent.run(session, context, message.body, model_factory(ai.config["model"]))
        except Exception as exc:  # the agent, the model API or a tool failed
            logger.exception("The agent could not process %s message %s", message.channel, message.id)
            session.rollback()
            message = session.get(InboundMessage, message_id)
            # An enquiry recorded before the failure is still real.
            _finish(
                session,
                message,
                "enquiry_created" if context.enquiry_id else "failed",
                enquiry_id=context.enquiry_id,
                error="{}: {}".format(type(exc).__name__, exc)[:2000],
            )
            return
        _finish(session, message, outcome.status, enquiry_id=outcome.enquiry_id, summary=outcome.summary)
    finally:
        session.close()


def _finish(
    session: Session,
    message: InboundMessage,
    status: str,
    enquiry_id: Optional[uuid.UUID] = None,
    summary: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    message.status = status
    message.enquiry_id = enquiry_id
    message.summary = summary
    message.error = error
    message.processed_at = datetime.now(timezone.utc)
    session.commit()


def retry(session: Session, message_id: uuid.UUID) -> InboundMessage:
    """Put a failed or skipped message back in the queue."""
    from ..errors import ConflictError, NotFoundError

    message = session.get(InboundMessage, message_id)
    if message is None:
        raise NotFoundError("Message {} does not exist.".format(message_id))
    if message.status not in ("failed", "skipped"):
        raise ConflictError("Only a failed or skipped message can be retried.")
    begin_write(session)
    message.status = "pending"
    message.error = None
    message.summary = None
    session.commit()
    return message


def _filter(channel: Optional[str], status: Optional[str]):
    stmt = select(InboundMessage)
    if channel:
        stmt = stmt.where(InboundMessage.channel == channel)
    if status:
        stmt = stmt.where(InboundMessage.status == status)
    return stmt


def count(session: Session, channel: Optional[str] = None, status: Optional[str] = None) -> int:
    return session.execute(
        select(func.count()).select_from(_filter(channel, status).subquery())
    ).scalar_one()


def list_recent(
    session: Session,
    channel: Optional[str] = None,
    status: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> List[InboundMessage]:
    stmt = (
        _filter(channel, status)
        .options(joinedload(InboundMessage.enquiry))
        .order_by(InboundMessage.received_at.desc(), InboundMessage.id)
    )
    return list(session.execute(windowed(stmt, limit, offset)).scalars().all())


def view(message: InboundMessage) -> Dict[str, Any]:
    return {
        "id": message.id,
        "channel": message.channel,
        "sender": message.sender,
        "sender_name": message.sender_name,
        "subject": message.subject,
        "body": message.body,
        "received_at": message.received_at,
        "status": message.status,
        "enquiry_id": message.enquiry_id,
        "enquiry_number": message.enquiry.enquiry_number if message.enquiry else None,
        "summary": message.summary,
        "error": message.error,
        "processed_at": message.processed_at,
    }
