"""Purchase enquiries: what we want to buy, the suppliers asked, each supplier's
offer, and the offer that became the purchase order.

The automation raises them from the 'Need detected' trigger; a buyer can also
start one by hand. A draft waits for a person to check the suppliers before
anyone is asked. No purchase order exists until an offer is picked.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import NotFoundError, ValidationError
from ..models import Product, PurchaseOrder, Supplier, SupplierQuote, SupplierQuoteLine, SupplierQuoteRequest, SupplierQuoteRequestLine
from ..services import triggers
from ..services.common import next_document_number

router = APIRouter(prefix="/api/purchase-enquiries", tags=["purchasing"])


def _view(db: Session, rfq: SupplierQuoteRequest) -> dict:
    orders = db.execute(select(PurchaseOrder).where(PurchaseOrder.enquiry_id == rfq.id)).scalars().all()
    return {
        "id": rfq.id, "number": rfq.number, "status": rfq.status, "reason": rfq.reason, "notes": rfq.notes, "decision": rfq.decision,
        "reply_by": rfq.reply_by, "created_at": rfq.created_at, "created_by": rfq.created_by, "chosen_quote_id": rfq.chosen_quote_id,
        "orders": [{"id": o.id, "po_number": o.po_number, "supplier": o.supplier.name, "status": o.status.value if hasattr(o.status, "value") else o.status,
                    "total": float(sum((i.quantity_ordered * i.unit_cost for i in o.items), Decimal("0")))} for o in orders],
        "lines": [{"id": l.id, "product_id": l.product_id, "product": l.product.name, "unit": l.product.unit_of_measure, "quantity": float(l.quantity),
                   "why": l.why, "last_paid": float(l.product.last_purchase_price) if l.product.last_purchase_price else None} for l in rfq.lines],
        "quotes": [{"id": q.id, "supplier_id": q.supplier_id, "supplier": q.supplier.name, "phone": q.supplier.phone, "status": q.status,
                    "channel": q.channel, "source": q.source, "asked_at": q.asked_at, "replied_at": q.replied_at, "reply": q.reply,
                    "delivery_days": q.delivery_days, "freight": float(q.freight) if q.freight is not None else None, "gst_included": q.gst_included,
                    "score": float(q.score) if q.score is not None else None, "call_attempts": q.call_attempts,
                    "prices": {str(ql.product_id): float(ql.price) for ql in q.lines},
                    "available": {str(ql.product_id): float(ql.quantity_available) for ql in q.lines if ql.quantity_available is not None},
                    "total": float(sum((ql.price * next((l.quantity for l in rfq.lines if l.product_id == ql.product_id), Decimal("0")) for ql in q.lines), Decimal("0")))}
                   for q in rfq.quotes],
    }


def _get(db: Session, enquiry_id: uuid.UUID) -> SupplierQuoteRequest:
    rfq = db.get(SupplierQuoteRequest, enquiry_id)
    if rfq is None:
        raise NotFoundError("Purchase enquiry not found.")
    return rfq


@router.get("")
def list_enquiries(status: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    """Purchase enquiries, newest first."""
    stmt = select(SupplierQuoteRequest).order_by(SupplierQuoteRequest.created_at.desc()).limit(200)
    if status:
        stmt = stmt.where(SupplierQuoteRequest.status.in_(status.split(",")))
    return {"items": [_view(db, r) for r in db.execute(stmt).scalars()]}


@router.get("/{enquiry_id}")
def get_enquiry(enquiry_id: uuid.UUID, db: Session = Depends(get_db)):
    return _view(db, _get(db, enquiry_id))


class LineIn(BaseModel):
    product_id: uuid.UUID
    quantity: Decimal = Field(gt=0, description="In the product's base unit.")


class EnquiryIn(BaseModel):
    lines: List[LineIn] = Field(min_length=1)
    #: Suppliers to ask. Empty: chosen by the 'Choose suppliers' step settings.
    supplier_ids: List[uuid.UUID] = Field(default_factory=list)
    notes: Optional[str] = None
    #: Send it now; otherwise it stays a draft.
    send: bool = True


@router.post("", status_code=201)
def create_enquiry(payload: EnquiryIn, db: Session = Depends(get_db)):
    """Start a purchase enquiry by hand."""
    rfq = SupplierQuoteRequest(number=next_document_number(db, "rfq", "PE"), status="draft", reason="manual", created_by="person", notes=payload.notes)
    for line in payload.lines:
        if db.get(Product, line.product_id) is None:
            raise ValidationError("Unknown product.")
        rfq.lines.append(SupplierQuoteRequestLine(product_id=line.product_id, quantity=line.quantity, why="entered by hand"))
    for supplier_id in dict.fromkeys(payload.supplier_ids):
        if db.get(Supplier, supplier_id) is None:
            raise ValidationError("Unknown supplier.")
        rfq.quotes.append(SupplierQuote(supplier_id=supplier_id, status="to_ask", source="picked by hand"))
    db.add(rfq)
    db.commit()
    if not payload.supplier_ids:
        triggers.plan_enquiry(db, rfq.id)
    if payload.send:
        triggers.release_draft(db, rfq.id)
    db.refresh(rfq)
    return _view(db, rfq)


@router.post("/{enquiry_id}/send")
def send_enquiry(enquiry_id: uuid.UUID, db: Session = Depends(get_db)):
    """Send a draft enquiry to its suppliers."""
    rfq = _get(db, enquiry_id)
    if rfq.status != "draft":
        raise ValidationError("{} has already been sent.".format(rfq.number))
    if not rfq.quotes:
        raise ValidationError("Add at least one supplier first.")
    triggers.release_draft(db, rfq.id)
    db.refresh(rfq)
    return _view(db, rfq)


class SupplierIn(BaseModel):
    supplier_id: uuid.UUID


@router.post("/{enquiry_id}/suppliers")
def add_supplier(enquiry_id: uuid.UUID, payload: SupplierIn, db: Session = Depends(get_db)):
    """Ask one more supplier (on a draft, or an enquiry still waiting for offers)."""
    rfq = _get(db, enquiry_id)
    if rfq.status not in ("draft", "open"):
        raise ValidationError("{} is no longer collecting offers.".format(rfq.number))
    if db.get(Supplier, payload.supplier_id) is None:
        raise ValidationError("Unknown supplier.")
    if all(q.supplier_id != payload.supplier_id for q in rfq.quotes):
        rfq.quotes.append(SupplierQuote(supplier_id=payload.supplier_id, status="to_ask", source="picked by hand"))
        db.commit()
        if rfq.status == "open":
            triggers.ask_suppliers(db, rfq.id)
    db.refresh(rfq)
    return _view(db, rfq)


@router.delete("/{enquiry_id}/suppliers/{supplier_id}")
def remove_supplier(enquiry_id: uuid.UUID, supplier_id: uuid.UUID, db: Session = Depends(get_db)):
    rfq = _get(db, enquiry_id)
    if rfq.status != "draft":
        raise ValidationError("Suppliers can only be removed before the enquiry is sent.")
    for quote in list(rfq.quotes):
        if quote.supplier_id == supplier_id:
            rfq.quotes.remove(quote)
    db.commit()
    return _view(db, rfq)


class OfferIn(BaseModel):
    supplier_id: uuid.UUID
    prices: dict = Field(description="{product_id: price per base unit}")
    delivery_days: Optional[int] = None
    note: Optional[str] = None


@router.post("/{enquiry_id}/offers")
def record_offer(enquiry_id: uuid.UUID, payload: OfferIn, db: Session = Depends(get_db)):
    """Record a supplier's offer by hand (they phoned, or the reply was unclear)."""
    rfq = _get(db, enquiry_id)
    if rfq.status not in ("open", "to_choose", "decided"):
        raise ValidationError("{} is {}.".format(rfq.number, rfq.status))
    quote = next((q for q in rfq.quotes if q.supplier_id == payload.supplier_id), None)
    if quote is None:
        quote = SupplierQuote(supplier_id=payload.supplier_id, status="replied", source="entered by hand")
        rfq.quotes.append(quote)
    quote.lines.clear()
    for product_id, price in (payload.prices or {}).items():
        if price not in (None, ""):
            quote.lines.append(SupplierQuoteLine(product_id=uuid.UUID(str(product_id)), price=Decimal(str(price))))
    quote.status, quote.replied_at, quote.delivery_days = "replied", datetime.now(timezone.utc), payload.delivery_days
    if payload.note:
        quote.reply = ((quote.reply + "\n") if quote.reply else "") + payload.note
    db.commit()
    if rfq.status == "open" and all(q.status in ("replied", "declined", "no_reply") for q in rfq.quotes):
        triggers.decide(db, rfq.id)
    db.refresh(rfq)
    return _view(db, rfq)


@router.post("/{enquiry_id}/compare")
def compare_now(enquiry_id: uuid.UUID, db: Session = Depends(get_db)):
    """Stop waiting for offers and run 'Pick the offer' now."""
    rfq = _get(db, enquiry_id)
    if rfq.status != "open":
        raise ValidationError("{} is {}.".format(rfq.number, rfq.status))
    for quote in rfq.quotes:
        if quote.status in ("to_ask", "asked", "calling"):
            quote.status = "no_reply"
    db.commit()
    triggers.decide(db, rfq.id)
    db.refresh(rfq)
    return _view(db, rfq)


class OrderIn(BaseModel):
    #: Order from this supplier's offer; empty orders the recommended offers.
    supplier_id: Optional[uuid.UUID] = None


@router.post("/{enquiry_id}/order")
def order(enquiry_id: uuid.UUID, payload: OrderIn, db: Session = Depends(get_db)):
    """Pick the offer: the purchase order is created now and sent to the supplier."""
    rfq = _get(db, enquiry_id)
    result = triggers.order_from(db, rfq.id, payload.supplier_id, who="person")
    if result.get("error"):
        raise ValidationError(result["error"])
    db.refresh(rfq)
    return _view(db, rfq)


@router.post("/{enquiry_id}/cancel")
def cancel(enquiry_id: uuid.UUID, db: Session = Depends(get_db)):
    rfq = _get(db, enquiry_id)
    if rfq.status == "ordered":
        raise ValidationError("{} is already ordered.".format(rfq.number))
    rfq.status = "cancelled"
    db.commit()
    return _view(db, rfq)
