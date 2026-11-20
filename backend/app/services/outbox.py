"""Sending messages to customers and suppliers: WhatsApp (free text within 24
hours of their last message) and email (SMTP of the connected mailbox).

A message is sent at once, or held for a person to approve when the flow step
says "prepare for approval". Every message is kept.
"""
from __future__ import annotations

import smtplib
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import NotFoundError, ValidationError
from ..models import OutboundMessage, User
from . import integration_settings as settings_service
from . import whatsapp


def _send_whatsapp(session: Session, to: str, body: str) -> str:
    row = settings_service.get(session, settings_service.WHATSAPP)
    token = settings_service.credentials(row).get("access_token")
    if not (row.enabled and token and row.config.get("phone_number_id")):
        raise whatsapp.SendError("WhatsApp sending is not set up (phone number id and access token).")
    number = whatsapp.recipient(to, row.config.get("country_code") or "91")
    template = (row.config.get("message_template") or "").strip()
    if template and not _in_window(session, to):
        # WhatsApp only allows free text within 24 hours of their last
        # message; outside it, a business-started message must be an approved
        # template. A one-variable template ({{1}}) carries the text.
        return whatsapp.send_template(row.config, token, number, template, [body[:1000]])
    base = "{}/{}/{}".format(whatsapp.GRAPH, row.config.get("graph_version") or "v23.0", row.config["phone_number_id"])
    try:
        with whatsapp.http_factory() as client:
            response = client.post(base + "/messages", headers={"Authorization": "Bearer " + token},
                                   json={"messaging_product": "whatsapp", "to": number, "type": "text", "text": {"body": body[:4000]}})
    except httpx.HTTPError as exc:
        raise whatsapp.SendError("Could not reach WhatsApp: {}".format(exc)) from exc
    if response.status_code >= 400:
        raise whatsapp.SendError("WhatsApp refused the message: " + whatsapp._graph_error(response))
    return ((response.json().get("messages") or [{}])[0]).get("id") or ""


def _in_window(session: Session, to: str) -> bool:
    """Did this number write to us in the last 24 hours (WhatsApp's free-text window)?"""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func, select

    from ..models import InboundMessage

    digits = "".join(ch for ch in to if ch.isdigit())[-10:]
    if not digits:
        return False
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    return bool(session.execute(select(func.count(InboundMessage.id)).where(
        InboundMessage.channel == "whatsapp", InboundMessage.sender.like("%" + digits), InboundMessage.created_at >= since)).scalar_one())


#: Swappable in tests.
smtp_factory = smtplib.SMTP


def _send_email(session: Session, to: str, subject: Optional[str], body: str) -> str:
    row = settings_service.get(session, settings_service.EMAIL)
    password = settings_service.credentials(row).get("password")
    config = row.config
    if not (config.get("smtp_host") and config.get("username") and password):
        raise whatsapp.SendError("Email replies need the outgoing (SMTP) server in Settings -> Email.")
    message = EmailMessage()
    message["From"] = config["username"]
    message["To"] = to
    message["Subject"] = subject or "Re: your enquiry"
    message.set_content(body)
    with smtp_factory(config["smtp_host"], int(config.get("smtp_port") or 587), timeout=20) as server:
        server.starttls()
        server.login(config["username"], password)
        server.send_message(message)
    return message.get("Message-ID") or ""


def deliver(session: Session, message: OutboundMessage) -> OutboundMessage:
    try:
        if message.channel == "whatsapp":
            message.provider_id = _send_whatsapp(session, message.to, message.body)
        elif message.channel == "email":
            message.provider_id = _send_email(session, message.to, message.subject, message.body)
        else:
            raise whatsapp.SendError("Messages can be sent on WhatsApp or email.")
        message.status, message.sent_at, message.error = "sent", datetime.now(timezone.utc), None
    except (whatsapp.SendError, smtplib.SMTPException, OSError) as exc:
        message.status, message.error = "failed", str(exc)[:1000]
    session.flush()
    return message


def queue(session: Session, channel: str, to: str, body: str, *, hold: bool, author: str = "tai", subject: Optional[str] = None,
          inbound_id=None, customer_id=None, enquiry_id=None) -> OutboundMessage:
    message = OutboundMessage(channel=channel, to=to, subject=subject, body=body, author=author,
                              status="pending_approval" if hold else "sent", inbound_id=inbound_id,
                              customer_id=customer_id, enquiry_id=enquiry_id)
    session.add(message)
    session.flush()
    if not hold:
        deliver(session, message)
    return message


def view(message: OutboundMessage) -> Dict[str, Any]:
    return {"id": message.id, "channel": message.channel, "to": message.to, "subject": message.subject, "body": message.body,
            "status": message.status, "error": message.error, "author": message.author, "customer_id": message.customer_id,
            "enquiry_id": message.enquiry_id, "inbound_id": message.inbound_id, "created_at": message.created_at,
            "sent_at": message.sent_at, "approved_by": message.approved_by}


def list_messages(session: Session, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    stmt = select(OutboundMessage).order_by(OutboundMessage.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(OutboundMessage.status == status)
    return [view(m) for m in session.execute(stmt).scalars()]


def approve(session: Session, message_id: uuid.UUID, user: Optional[User], body: Optional[str] = None) -> Dict[str, Any]:
    message = session.get(OutboundMessage, message_id)
    if message is None:
        raise NotFoundError("Message not found.")
    if message.status not in ("pending_approval", "failed"):
        raise ValidationError("This message was already {}.".format(message.status))
    if body is not None and body.strip():
        message.body = body.strip()
    message.approved_by = user.username if user else None
    deliver(session, message)
    session.commit()
    return view(message)


def discard(session: Session, message_id: uuid.UUID) -> Dict[str, Any]:
    message = session.get(OutboundMessage, message_id)
    if message is None:
        raise NotFoundError("Message not found.")
    if message.status != "pending_approval":
        raise ValidationError("Only a message waiting for approval can be discarded.")
    message.status = "discarded"
    session.commit()
    return view(message)
