"""Integrations: AI enquiry agent, WhatsApp webhook and email intake."""
from __future__ import annotations

import json
import uuid
from typing import Optional

import anthropic
from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..errors import ValidationError
from ..services import ai_agent
from ..services import email_inbox
from ..services import inbound as inbound_service
from ..services import integration_settings as settings_service
from ..services import whatsapp as whatsapp_service
from .pagination import PageParams, page_params

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _all(db: Session) -> dict:
    return {
        "ai": settings_service.view(settings_service.get(db, settings_service.AI)),
        "whatsapp": settings_service.view(settings_service.get(db, settings_service.WHATSAPP)),
        "email": settings_service.view(settings_service.get(db, settings_service.EMAIL)),
        "models": settings_service.AI_MODELS,
    }


@router.get("", response_model=schemas.IntegrationsOut)
def get_integrations(db: Session = Depends(get_db)):
    """Every integration's settings. Credentials only say whether they are set."""
    return _all(db)


@router.put("/{name}", response_model=schemas.IntegrationOut)
def update_integration(name: str, payload: schemas.IntegrationUpdate, db: Session = Depends(get_db)):
    """Switch an integration on or off and change its settings."""
    row = settings_service.update(
        db, name, enabled=payload.enabled, config=payload.config, secrets=payload.credentials
    )
    return settings_service.view(row)


@router.post("/ai/test", response_model=schemas.AiTestOut)
def test_ai(db: Session = Depends(get_db)):
    """Send one tiny request with the saved model and key."""
    row = settings_service.get(db, settings_service.AI)
    api_key = settings_service.credentials(row).get("api_key")
    if not api_key:
        raise ValidationError("Save an API key first.")
    model = row.config["model"]
    try:
        reply = ai_agent.test_connection(model, api_key)
    except anthropic.AuthenticationError:
        raise ValidationError("The API key was rejected. Check it and save it again.")
    except anthropic.PermissionDeniedError:
        raise ValidationError("This API key may not use {}.".format(model))
    except anthropic.NotFoundError:
        raise ValidationError("The model {} is not available to this API key.".format(model))
    except anthropic.RateLimitError:
        raise ValidationError("The AI provider is rate limiting this key. Try again in a minute.")
    except anthropic.APIStatusError as exc:
        raise ValidationError("The AI provider returned an error ({}).".format(exc.status_code))
    except anthropic.APIConnectionError:
        raise ValidationError("Could not reach the AI provider. Check the server's internet access.")
    return {"ok": True, "model": model, "reply": reply}


# --- WhatsApp -------------------------------------------------------------------


@router.get("/whatsapp/webhook", response_class=PlainTextResponse, include_in_schema=False)
def whatsapp_verify(
    mode: Optional[str] = Query(default=None, alias="hub.mode"),
    token: Optional[str] = Query(default=None, alias="hub.verify_token"),
    challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
    db: Session = Depends(get_db),
):
    """Meta's check when the webhook is registered: echo the challenge."""
    return PlainTextResponse(whatsapp_service.verify_subscription(db, mode, token, challenge))


@router.post("/whatsapp/webhook", include_in_schema=False)
async def whatsapp_receive(request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Meta posts every WhatsApp event here. Answer fast; the agent runs after."""
    raw = await request.body()
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        return JSONResponse(status_code=400, content={"code": "bad_request", "message": "Body is not JSON."})
    ids = whatsapp_service.receive(db, payload, raw, request.headers.get("X-Hub-Signature-256"))
    for message_id in ids:
        background.add_task(inbound_service.process, message_id)
    return {"received": len(ids)}


# --- Email --------------------------------------------------------------------------


@router.post("/email/check", response_model=schemas.EmailCheckOut)
def email_check(background: BackgroundTasks, db: Session = Depends(get_db)):
    """Read the inbox now instead of waiting for the next scheduled check."""
    ids = email_inbox.check_inbox(db)
    for message_id in ids:
        background.add_task(inbound_service.process, message_id)
    return {"new_messages": len(ids)}


# --- What came in ---------------------------------------------------------------------


@router.get("/messages", response_model=schemas.Page[schemas.InboundMessageOut])
def list_messages(
    channel: Optional[str] = Query(default=None, pattern="^(whatsapp|email)$"),
    status: Optional[str] = Query(default=None),
    paging: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
):
    """Messages received on WhatsApp and email, newest first, with what the AI did."""
    rows = inbound_service.list_recent(db, channel, status, paging.limit, paging.offset)
    return paging.page([inbound_service.view(row) for row in rows], inbound_service.count(db, channel, status))


@router.post("/messages/{message_id}/retry", response_model=schemas.InboundMessageOut)
def retry_message(message_id: uuid.UUID, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Let the agent try a failed or skipped message again."""
    message = inbound_service.retry(db, message_id)
    background.add_task(inbound_service.process, message.id)
    return inbound_service.view(message)
