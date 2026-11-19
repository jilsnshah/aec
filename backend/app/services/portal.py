"""A customer's own enquiry page.

Each customer can be given a secret link (/e/<token>). Whoever has it sees the
business's products with that customer's prices and whether they are in stock
(not how many), and can send an enquiry, recorded as from that customer. The
link can be replaced (the old one stops working) or switched off.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import begin_write
from ..errors import NotFoundError, ValidationError
from ..models import Customer, CustomerEnquiry, Product
from . import enquiries as enquiry_service
from . import integration_settings as settings_service
from . import pricelists, reservations

MAX_PER_DAY = 20
MAX_LINES = 40


def set_link(session: Session, customer_id: uuid.UUID, enabled: bool = True) -> Dict[str, Any]:
    """Create (or replace) a customer's link, or switch it off."""
    begin_write(session)
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError("Customer not found.")
    customer.portal_token = secrets.token_urlsafe(18) if enabled else None
    session.commit()
    return link_view(customer)


def link_view(customer: Customer) -> Dict[str, Any]:
    return {"enabled": bool(customer.portal_token), "path": "/e/{}".format(customer.portal_token) if customer.portal_token else None}


def _customer(session: Session, token: str) -> Customer:
    customer = session.execute(select(Customer).where(Customer.portal_token == token)).scalar_one_or_none() if token else None
    if customer is None or not customer.is_active:
        raise NotFoundError("This link is not valid any more. Please ask us for a new one.")
    return customer


def page(session: Session, token: str) -> Dict[str, Any]:
    customer = _customer(session, token)
    seller = settings_service.get(session, settings_service.TALLY).config.get("seller_name") or "Our shop"
    products = session.execute(select(Product).where(Product.is_active.is_(True)).order_by(Product.category.nulls_last(), Product.name)).scalars().all()
    prices = {line["product_id"]: line for line in pricelists.resolve(session, customer.id, [{"product_id": p.id, "quantity": "1"} for p in products])["lines"]} if products else {}
    reserved = reservations.reserved_map(session, [p.id for p in products])
    return {
        "business": seller,
        "customer": customer.name,
        "products": [
            {"id": p.id, "name": p.name, "unit": p.unit_of_measure, "category": p.category, "mrp": float(p.mrp or 0),
             "price": prices.get(p.id, {}).get("net_price", float(p.mrp or 0)),
             "in_stock": (p.physical_stock - reserved.get(p.id, Decimal("0"))) > 0}
            for p in products
        ],
    }


def send(session: Session, token: str, items: List[Dict[str, Any]], notes: Optional[str], name: Optional[str], phone: Optional[str]) -> Dict[str, Any]:
    customer = _customer(session, token)
    since = datetime.now(timezone.utc) - timedelta(days=1)
    recent = session.execute(
        select(func.count(CustomerEnquiry.id)).where(CustomerEnquiry.customer_id == customer.id, CustomerEnquiry.source == "link", CustomerEnquiry.created_at >= since)
    ).scalar_one()
    if recent >= MAX_PER_DAY:
        raise ValidationError("Too many enquiries today from this link. Please call or WhatsApp us.")
    lines = []
    for item in (items or [])[:MAX_LINES]:
        try:
            qty = Decimal(str(item.get("quantity")))
            product_id = uuid.UUID(str(item.get("product_id")))
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError("Each line needs a product and a quantity.")
        if qty > 0:
            lines.append({"product_id": product_id, "quantity": str(qty), "discount_percent": "0"})
    if not lines:
        raise ValidationError("Add at least one product with a quantity.")
    resolved = {line["product_id"]: line for line in pricelists.resolve(session, customer.id, [{"product_id": l["product_id"], "quantity": l["quantity"]} for l in lines])["lines"]}
    for line in lines:
        hit = resolved.get(line["product_id"])
        if hit:
            line["discount_percent"] = str(hit["discount_percent"])
    note = (notes or "").strip()[:1000] or None
    enquiry = enquiry_service.create_enquiry(
        session, customer.id, lines, notes=note, source="link", source_detail="customer link",
        sender_name=(name or "").strip()[:255] or None, sender_phone=(phone or "").strip()[:32] or None,
    )
    return {"enquiry_number": enquiry.enquiry_number, "lines": len(enquiry.items), "total": float(enquiry_service.enquiry_total(enquiry))}
