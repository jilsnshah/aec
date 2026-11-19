"""Messages the business sends on its own: the order confirmation on WhatsApp.

Sent only when switched on in Settings (WhatsApp: "send order confirmations")
with an approved template; a person can also send it from the order. The
number used is the ordering contact's WhatsApp number, else the customer's.
Every attempt, sent or not, is written to the audit log.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from sqlalchemy import select

from ..errors import ValidationError
from ..models import ContactPoint, SalesOrder, User
from . import integration_settings as settings_service
from . import whatsapp


def _number(session, order: SalesOrder) -> Optional[str]:
    points = session.execute(
        select(ContactPoint).where(ContactPoint.customer_id == order.customer_id, ContactPoint.kind == "phone", ContactPoint.is_active.is_(True))
        .order_by(ContactPoint.is_whatsapp.desc(), ContactPoint.is_primary.desc(), ContactPoint.created_at)
    ).scalars().all()
    if order.contact_id:
        for point in points:
            if point.contact_id == order.contact_id and point.is_whatsapp:
                return point.value
    for point in points:
        if point.is_whatsapp:
            return point.value
    return points[0].value if points else order.customer.phone


def confirmation_text(order: SalesOrder) -> Dict[str, Any]:
    items = "; ".join("{:g} {} {}".format(float(i.quantity_ordered), i.product.unit_of_measure, i.product.name) for i in order.items[:4])
    if len(order.items) > 4:
        items += "; and {} more".format(len(order.items) - 4)
    total = "Rs {:,.2f}".format(float(order.total_amount))
    return {"parameters": [order.customer.name, order.order_number, total, items],
            "preview": "Hello {}, your order {} for {} is confirmed: {}.".format(order.customer.name, order.order_number, total, items)}


def send_order_confirmation(session, order_id: uuid.UUID, user: Optional[User] = None, automatic: bool = False) -> Dict[str, Any]:
    from .controls import log
    from .orders import get_order

    row = settings_service.get(session, settings_service.WHATSAPP)
    config = row.config
    token = settings_service.credentials(row).get("access_token")
    if automatic and not (row.enabled and config.get("send_order_confirmations")):
        return {"sent": False, "reason": "off"}
    if not (row.enabled and token and config.get("phone_number_id") and config.get("order_template")):
        raise ValidationError("Set up WhatsApp sending and an approved order template in Settings first.")
    order = get_order(session, order_id)
    to = whatsapp.recipient(_number(session, order), config.get("country_code") or "91")
    if not to:
        raise ValidationError("{} has no phone number for WhatsApp.".format(order.customer.name))
    text = confirmation_text(order)
    try:
        message_id = whatsapp.send_template(config, token, to, config["order_template"], text["parameters"])
    except whatsapp.SendError as exc:
        log(session, user, "whatsapp_order_failed", "order", str(order.id), "Order confirmation for {} not sent: {}".format(order.order_number, exc))
        session.commit()
        raise ValidationError(str(exc))
    log(session, user, "whatsapp_order_sent", "order", str(order.id),
        "Order confirmation for {} sent on WhatsApp to {}{}".format(order.order_number, to, " (automatic)" if automatic else ""), {"message_id": message_id})
    session.commit()
    return {"sent": True, "to": to, "message_id": message_id}


def order_placed(order_id: uuid.UUID) -> None:
    """Background task after an order is placed: confirm on WhatsApp if switched on."""
    from . import inbound

    session = inbound.session_factory()
    try:
        send_order_confirmation(session, order_id, automatic=True)
    except Exception:
        session.rollback()  # recorded in the audit log when it reached WhatsApp; never blocks the order
    finally:
        session.close()
