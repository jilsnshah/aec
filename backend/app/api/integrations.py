"""Integrations: AI enquiry agent, WhatsApp webhook and email intake."""
from __future__ import annotations

import json
import uuid
from typing import Optional

import anthropic
from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..errors import NotFoundError, ValidationError
from ..services import ai_agent
from ..services import email_inbox
from ..services import inbound as inbound_service
from ..services import integration_settings as settings_service
from ..services import invoice_pdf, tally, tally_sync
from ..services import whatsapp as whatsapp_service
from .pagination import PageParams, page_params

router = APIRouter(prefix="/api/integrations", tags=["integrations"])
#: Called by Meta, not by a signed-in user: no sign-in required. The verify
#: token and the app-secret signature protect them instead.
webhooks = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _all(db: Session) -> dict:
    models = settings_service.available_models()
    return {
        "ai": settings_service.view(settings_service.get(db, settings_service.AI)),
        "whatsapp": settings_service.view(settings_service.get(db, settings_service.WHATSAPP)),
        "email": settings_service.view(settings_service.get(db, settings_service.EMAIL)),
        "tally": settings_service.view(settings_service.get(db, settings_service.TALLY)),
        "models": models,
        # Which providers the server holds credentials for. Never the credentials.
        "providers": sorted(
            {settings_service.PROVIDER_LABELS[model["provider"]] for model in models}
        ),
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
    """Send one tiny request with the chosen model and the server's credentials."""
    row = settings_service.get(db, settings_service.AI)
    model = row.config["model"]
    try:
        reply = ai_agent.test_connection(model)
    except ai_agent.NotConfigured:
        raise ValidationError("The AI is not set up on the server yet.")
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
    except Exception as exc:  # the Gemini client's errors
        if type(exc).__module__.startswith(("google", "langchain_google")):
            raise ValidationError("The AI provider refused the request: {}".format(str(exc)[:300]))
        raise
    return {"ok": True, "model": model, "reply": reply}


# --- WhatsApp -------------------------------------------------------------------


@webhooks.get("/whatsapp/webhook", response_class=PlainTextResponse, include_in_schema=False)
def whatsapp_verify(
    mode: Optional[str] = Query(default=None, alias="hub.mode"),
    token: Optional[str] = Query(default=None, alias="hub.verify_token"),
    challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
    db: Session = Depends(get_db),
):
    """Meta's check when the webhook is registered: echo the challenge."""
    return PlainTextResponse(whatsapp_service.verify_subscription(db, mode, token, challenge))


@webhooks.post("/whatsapp/webhook", include_in_schema=False)
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


# --- Tally ----------------------------------------------------------------------------


@router.post("/tally/test", response_model=schemas.TallyTestOut)
def tally_test(db: Session = Depends(get_db)):
    """Reach the saved Tally server and list the companies open in it."""
    try:
        return tally_sync.test_connection(db)
    except tally.TallyError as exc:
        raise ValidationError(str(exc))


@router.get("/tally/syncs", response_model=schemas.Page[schemas.TallySyncOut])
def tally_syncs(
    status: Optional[str] = Query(default=None, pattern="^(pending|synced|failed)$"),
    entity_id: Optional[uuid.UUID] = None,
    paging: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
):
    """What has been sent to Tally, newest first. ``entity_id`` narrows to one order."""
    if entity_id:
        rows = tally_sync.for_entity(db, entity_id)
        return paging.page([tally_sync.view(row) for row in rows], len(rows))
    rows = tally_sync.list_recent(db, status, paging.limit, paging.offset)
    return paging.page([tally_sync.view(row) for row in rows], tally_sync.count(db, status))


@router.post("/tally/syncs/{sync_id}/retry", response_model=schemas.TallySyncOut)
def tally_retry(sync_id: uuid.UUID, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Push a failed document again, or resend an invoice that was not sent."""
    row = tally_sync.retry(db, sync_id)
    background.add_task(tally_sync.process, row.id)
    return tally_sync.view(row)


@router.get("/whatsapp/template", response_model=schemas.TemplateStatusOut)
def whatsapp_template(db: Session = Depends(get_db)):
    """Whether Meta has approved the invoice template."""
    row = settings_service.get(db, settings_service.WHATSAPP)
    token = settings_service.credentials(row).get("access_token")
    if not token or not row.config.get("invoice_template"):
        raise ValidationError("Save the access token and the template name first.")
    try:
        status = whatsapp_service.template_status(row.config, token)
    except whatsapp_service.SendError as exc:
        raise ValidationError(str(exc))
    return {"template": row.config["invoice_template"], "status": status}


@router.get("/invoices/{order_id}.pdf", include_in_schema=False)
def invoice_download(order_id: uuid.UUID, db: Session = Depends(get_db)):
    """The invoice PDF for an order, once Tally has the invoice."""
    row = tally_sync.invoice_for_order(db, order_id)
    if row is None:
        raise NotFoundError("This order has no invoice in Tally yet.")
    invoice = tally_sync.build_invoice(db, row)
    return Response(
        content=invoice_pdf.render(invoice),
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="Invoice-{}.pdf"'.format(invoice.number.replace("/", "-"))},
    )
