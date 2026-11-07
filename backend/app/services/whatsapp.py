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
from typing import Any, Dict, List, Optional

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


def receive(session: Session, payload: Dict[str, Any], raw_body: bytes, signature: Optional[str]) -> List[uuid.UUID]:
    """Record the new messages in a webhook call. Returns the ids to process."""
    row = settings_service.get(session, settings_service.WHATSAPP)
    if not row.enabled:
        logger.info("WhatsApp webhook called while WhatsApp is switched off; ignored.")
        return []
    app_secret = settings_service.credentials(row).get("app_secret")
    if not check_signature(app_secret, raw_body, signature):
        raise WebhookRejected("The request signature does not match the app secret.")

    recorded: List[uuid.UUID] = []
    for message in parse_messages(payload, row.config.get("phone_number_id") or ""):
        stored = inbound.record(session, CHANNEL, **message)
        if stored is not None:
            recorded.append(stored.id)
    return recorded
