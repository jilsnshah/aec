"""WhatsApp Business (Meta Cloud API) webhook: receive customer messages.

Meta calls the webhook twice over:

* ``GET`` once, when the webhook is registered, to check the verify token --
  answered with the challenge it sent;
* ``POST`` for every event. Text messages sent to the configured phone number
  are recorded and handed to the enquiry agent; everything else (delivery
  receipts, other numbers) is ignored.

When an app secret is configured, every ``POST`` must carry Meta's
``X-Hub-Signature-256`` HMAC of the raw body, so nobody else can post fake
messages to the webhook.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from ..errors import DomainError
from . import inbound
from . import integration_settings as settings_service

logger = logging.getLogger(__name__)

CHANNEL = "whatsapp"


class WebhookRejected(DomainError):
    status_code = 403
    code = "webhook_rejected"


def verify_subscription(session: Session, mode: Optional[str], token: Optional[str], challenge: Optional[str]) -> str:
    """Meta's one-time check when the webhook URL is saved in the app dashboard."""
    row = settings_service.get(session, settings_service.WHATSAPP)
    expected = row.config.get("verify_token") or ""
    if (
        mode == "subscribe"
        and row.enabled
        and expected
        and token is not None
        and hmac.compare_digest(token, expected)
    ):
        return challenge or ""
    raise WebhookRejected("The verify token does not match, or WhatsApp is switched off.")


def check_signature(app_secret: Optional[str], raw_body: bytes, header: Optional[str]) -> bool:
    """True when no app secret is configured, or the signature matches."""
    if not app_secret:
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[len("sha256="):], expected)


def parse_messages(payload: Dict[str, Any], phone_number_id: str) -> List[Dict[str, Any]]:
    """Text messages sent to our number, from a webhook payload."""
    found: List[Dict[str, Any]] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            if str((value.get("metadata") or {}).get("phone_number_id", "")) != str(phone_number_id):
                continue
            names = {
                contact.get("wa_id"): (contact.get("profile") or {}).get("name")
                for contact in value.get("contacts") or []
            }
            for message in value.get("messages") or []:
                if message.get("type") != "text":
                    continue
                body = ((message.get("text") or {}).get("body") or "").strip()
                if not body or not message.get("id") or not message.get("from"):
                    continue
                received = None
                try:
                    received = datetime.fromtimestamp(int(message.get("timestamp")), tz=timezone.utc)
                except (TypeError, ValueError):
                    pass
                found.append(
                    {
                        "external_id": message["id"],
                        "sender": "+" + str(message["from"]).lstrip("+"),
                        "sender_name": names.get(message["from"]),
                        "body": body,
                        "received_at": received,
                    }
                )
    return found


def parse_statuses(payload: Dict[str, Any], phone_number_id: str) -> List[Dict[str, Any]]:
    """Delivery receipts for messages we sent: sent, delivered, read, failed."""
    found: List[Dict[str, Any]] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            if str((value.get("metadata") or {}).get("phone_number_id", "")) != str(phone_number_id):
                continue
            for status in value.get("statuses") or []:
                if not status.get("id") or not status.get("status"):
                    continue
                at = None
                try:
                    at = datetime.fromtimestamp(int(status.get("timestamp")), tz=timezone.utc)
                except (TypeError, ValueError):
                    pass
                errors = status.get("errors") or []
                found.append({"wamid": status["id"], "status": status["status"], "at": at,
                              "error_code": (errors[0] or {}).get("code") if errors else None,
                              "error": ((errors[0] or {}).get("title") or (errors[0] or {}).get("message")) if errors else None,
                              "pricing": status.get("pricing") or {}})
    return found


def receive(session: Session, payload: Dict[str, Any], raw_body: bytes, signature: Optional[str]) -> List[uuid.UUID]:
    """Record the new messages in a webhook call. Returns the ids to process."""
    row = settings_service.get(session, settings_service.WHATSAPP)
    if not row.enabled:
        logger.info("WhatsApp webhook called while WhatsApp is switched off; ignored.")
        return []
    app_secret = settings_service.credentials(row).get("app_secret")
    if not check_signature(app_secret, raw_body, signature):
        raise WebhookRejected("The request signature does not match the app secret.")

    statuses = parse_statuses(payload, row.config.get("phone_number_id") or "")
    if statuses:
        from . import marketing

        marketing.on_statuses(session, statuses)
    recorded: List[uuid.UUID] = []
    for message in parse_messages(payload, row.config.get("phone_number_id") or ""):
        stored = inbound.record(session, CHANNEL, **message)
        if stored is not None:
            recorded.append(stored.id)
    return recorded


# ---------------------------------------------------------------------------
# Sending: invoices to customers
# ---------------------------------------------------------------------------


GRAPH = "https://graph.facebook.com"

#: Builds the HTTP client for Meta's Graph API. Tests replace it.
http_factory: Callable[[], httpx.Client] = lambda: httpx.Client(timeout=60)


class SendError(Exception):
    """Meta refused or could not take the message; the text is Meta's reason."""

    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message)
        self.code = code


def _graph_code(response: httpx.Response) -> Optional[int]:
    try:
        return (response.json().get("error") or {}).get("code")
    except ValueError:
        return None


def recipient(phone: Optional[str], country_code: str) -> Optional[str]:
    """A phone number as WhatsApp wants it: digits only, with the country code."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits:
        return None
    if len(digits) == 10 and country_code:
        digits = country_code + digits
    return digits.lstrip("0") or None


def _graph_error(response: httpx.Response) -> str:
    try:
        error = response.json().get("error", {})
        return "{} (code {})".format(error.get("message", response.text[:200]), error.get("code", response.status_code))
    except ValueError:
        return "HTTP {}".format(response.status_code)


def send_invoice(
    config: Dict[str, Any],
    access_token: str,
    to: str,
    pdf: bytes,
    filename: str,
    body_parameters: List[str],
) -> str:
    """Upload the invoice PDF, then send the approved template with it attached.

    A message the business starts must use a template Meta has approved. The
    template needs a DOCUMENT header and a body whose variables are, in order,
    ``body_parameters`` (customer name, invoice number, amount). Returns the
    WhatsApp message id.
    """
    base = "{}/{}/{}".format(GRAPH, config.get("graph_version") or "v23.0", config["phone_number_id"])
    headers = {"Authorization": "Bearer " + access_token}
    try:
        with http_factory() as client:
            upload = client.post(
                base + "/media",
                headers=headers,
                data={"messaging_product": "whatsapp", "type": "application/pdf"},
                files={"file": (filename, pdf, "application/pdf")},
            )
            if upload.status_code >= 400 or "id" not in upload.json():
                raise SendError("Uploading the invoice failed: " + _graph_error(upload))
            message = client.post(
                base + "/messages",
                headers=headers,
                json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "template",
                    "template": {
                        "name": config["invoice_template"],
                        "language": {"code": config.get("template_language") or "en"},
                        "components": [
                            {"type": "header", "parameters": [
                                {"type": "document", "document": {"id": upload.json()["id"], "filename": filename}},
                            ]},
                            {"type": "body", "parameters": [
                                {"type": "text", "text": text} for text in body_parameters
                            ]},
                        ],
                    },
                },
            )
    except httpx.HTTPError as exc:
        raise SendError("Could not reach WhatsApp: {}".format(exc)) from exc
    if message.status_code >= 400:
        raise SendError("WhatsApp refused the message: " + _graph_error(message))
    messages = message.json().get("messages") or [{}]
    return messages[0].get("id") or ""


def send_template(config: Dict[str, Any], access_token: str, to: str, template: str, body_parameters: List[str],
                  language: Optional[str] = None, header_image: Optional[str] = None) -> str:
    """Send an approved template, e.g. an order confirmation or a marketing
    message (optionally with an image header). Returns the WhatsApp message id."""
    components: List[Dict[str, Any]] = []
    if header_image:
        components.append({"type": "header", "parameters": [{"type": "image", "image": {"link": header_image}}]})
    if body_parameters:
        components.append({"type": "body", "parameters": [{"type": "text", "text": text} for text in body_parameters]})
    base = "{}/{}/{}".format(GRAPH, config.get("graph_version") or "v23.0", config["phone_number_id"])
    try:
        with http_factory() as client:
            message = client.post(
                base + "/messages",
                headers={"Authorization": "Bearer " + access_token},
                json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "template",
                    "template": {
                        "name": template,
                        "language": {"code": language or config.get("template_language") or "en"},
                        "components": components,
                    },
                },
            )
    except httpx.HTTPError as exc:
        raise SendError("Could not reach WhatsApp: {}".format(exc)) from exc
    if message.status_code >= 400:
        raise SendError("WhatsApp refused the message: " + _graph_error(message), code=_graph_code(message))
    messages = message.json().get("messages") or [{}]
    return messages[0].get("id") or ""


def template_status(config: Dict[str, Any], access_token: str) -> str:
    """Whether Meta has approved the invoice template: APPROVED, PENDING, REJECTED..."""
    waba = config.get("business_account_id")
    if not waba:
        raise SendError("Add the WhatsApp Business Account ID to check the template.")
    try:
        with http_factory() as client:
            response = client.get(
                "{}/{}/{}/message_templates".format(GRAPH, config.get("graph_version") or "v23.0", waba),
                headers={"Authorization": "Bearer " + access_token},
                params={"name": config["invoice_template"], "fields": "name,status,language"},
            )
    except httpx.HTTPError as exc:
        raise SendError("Could not reach WhatsApp: {}".format(exc)) from exc
    if response.status_code >= 400:
        raise SendError(_graph_error(response))
    matches = [t for t in response.json().get("data", []) if t.get("name") == config["invoice_template"]]
    if not matches:
        return "NOT_FOUND"
    return ", ".join(sorted({"{} ({})".format(t.get("status"), t.get("language")) for t in matches}))


# ---------------------------------------------------------------------------
# Message templates (marketing)
# ---------------------------------------------------------------------------


def list_templates(config: Dict[str, Any], access_token: str) -> List[Dict[str, Any]]:
    waba = config.get("business_account_id")
    if not waba:
        raise SendError("Add the WhatsApp Business Account ID in Settings → WhatsApp.")
    out: List[Dict[str, Any]] = []
    url = "{}/{}/{}/message_templates".format(GRAPH, config.get("graph_version") or "v23.0", waba)
    params: Optional[Dict[str, Any]] = {"fields": "id,name,status,language,category,components,rejected_reason", "limit": 100}
    try:
        with http_factory() as client:
            for _ in range(10):
                response = client.get(url, headers={"Authorization": "Bearer " + access_token}, params=params)
                if response.status_code >= 400:
                    raise SendError(_graph_error(response), code=_graph_code(response))
                data = response.json()
                out.extend(data.get("data") or [])
                url = ((data.get("paging") or {}).get("next")) or ""
                params = None
                if not url:
                    break
    except httpx.HTTPError as exc:
        raise SendError("Could not reach WhatsApp: {}".format(exc)) from exc
    return out


def create_template(config: Dict[str, Any], access_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    waba = config.get("business_account_id")
    if not waba:
        raise SendError("Add the WhatsApp Business Account ID in Settings → WhatsApp.")
    try:
        with http_factory() as client:
            response = client.post(
                "{}/{}/{}/message_templates".format(GRAPH, config.get("graph_version") or "v23.0", waba),
                headers={"Authorization": "Bearer " + access_token}, json=payload,
            )
    except httpx.HTTPError as exc:
        raise SendError("Could not reach WhatsApp: {}".format(exc)) from exc
    if response.status_code >= 400:
        raise SendError("WhatsApp refused the template: " + _graph_error(response), code=_graph_code(response))
    return response.json()
