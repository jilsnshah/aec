"""The trigger engine: run a trigger now, the activity log, supplier price
requests (RFQs) and customer feedback."""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import NotFoundError, ValidationError
from ..models import AutomationEvent, Customer, CustomerFeedback, SupplierQuote, SupplierQuoteLine, SupplierQuoteRequest
from ..services import triggers

router = APIRouter(prefix="/api/automation", tags=["automation"])

def _collections(session, force=True):
    from ..services import customer_agents

    return customer_agents.run_collections(session, force=force)


RUN = {"purchase": triggers.run_purchase, "outreach": triggers.run_outreach, "after_sales": triggers.run_after_sales, "collections": _collections,
       "chase": lambda session, force=True: {"sent": triggers.tick_chase(session)}, "rfqs": lambda session, force=True: {"decided": triggers.tick_rfqs(session)}}


@router.post("/run/{what}")
def run_now(what: str, db: Session = Depends(get_db)):
    """Run a trigger now, ignoring its schedule: purchase, outreach, after_sales, chase or rfqs."""
    job = RUN.get(what)
    if job is None:
        raise NotFoundError("Nothing called {}.".format(what))
    return job(db, force=True)


@router.get("/preview/{what}")
def preview(what: str, db: Session = Depends(get_db)):
    """Who or what a trigger would pick right now, without doing anything: purchase or outreach."""
    from ..services import automation

    if what == "purchase":
        cfg = automation.step(db, "purchase.need_detected")["config"]
        return {"items": [{"product_id": n["product"].id, "product": n["product"].name, "unit": n["product"].unit_of_measure,
                           "quantity": float(n["quantity"]), "why": n["why"], "value": float(n["value"])} for n in triggers.purchase_needs(db, cfg)]}
    if what == "outreach":
        cfg = automation.step(db, "sales.trigger_outreach")["config"]
        return {"items": [{"customer_id": c["customer"].id, "customer": c["customer"].name, "why": c["why"],
                           "message": triggers.outreach_text(db, c["customer"], c["why"], cfg)} for c in triggers.outreach_candidates(db, cfg)[:100]]}
    raise NotFoundError("Nothing called {}.".format(what))


@router.get("/activity")
def activity(step: Optional[str] = Query(default=None), party_id: Optional[uuid.UUID] = Query(default=None), limit: int = Query(default=100, le=500),
             db: Session = Depends(get_db)):
    """What the triggers and steps did, newest first."""
    stmt = select(AutomationEvent).order_by(AutomationEvent.created_at.desc()).limit(limit)
    if step:
        stmt = stmt.where(AutomationEvent.step == step)
    if party_id:
        stmt = stmt.where(AutomationEvent.party_id == party_id)
    return {"items": [{"id": e.id, "step": e.step, "kind": e.kind, "status": e.status, "summary": e.summary, "party_type": e.party_type,
                       "party_id": e.party_id, "subject_type": e.subject_type, "subject_id": e.subject_id, "detail": e.detail,
                       "created_at": e.created_at} for e in db.execute(stmt).scalars()]}


def _rfq_view(rfq: SupplierQuoteRequest) -> dict:
    return {
        "id": rfq.id, "number": rfq.number, "status": rfq.status, "reason": rfq.reason, "notes": rfq.notes, "decision": rfq.decision,
        "reply_by": rfq.reply_by, "purchase_order_id": rfq.purchase_order_id, "created_at": rfq.created_at, "created_by": rfq.created_by,
        "lines": [{"id": l.id, "product_id": l.product_id, "product": l.product.name, "unit": l.product.unit_of_measure, "quantity": float(l.quantity),
                   "why": l.why, "last_paid": float(l.product.last_purchase_price) if l.product.last_purchase_price else None} for l in rfq.lines],
        "quotes": [{"id": q.id, "supplier_id": q.supplier_id, "supplier": q.supplier.name, "status": q.status, "channel": q.channel, "source": q.source,
                    "asked_at": q.asked_at, "replied_at": q.replied_at, "reply": q.reply, "delivery_days": q.delivery_days,
                    "score": float(q.score) if q.score is not None else None,
                    "prices": {str(ql.product_id): float(ql.price) for ql in q.lines}} for q in rfq.quotes],
    }


@router.get("/rfqs")
def list_rfqs(status: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    """Requests for prices sent to suppliers, newest first."""
    stmt = select(SupplierQuoteRequest).order_by(SupplierQuoteRequest.created_at.desc()).limit(100)
    if status:
        stmt = stmt.where(SupplierQuoteRequest.status == status)
    return {"items": [_rfq_view(r) for r in db.execute(stmt).scalars()]}


@router.get("/rfqs/{rfq_id}")
def get_rfq(rfq_id: uuid.UUID, db: Session = Depends(get_db)):
    rfq = db.get(SupplierQuoteRequest, rfq_id)
    if rfq is None:
        raise NotFoundError("Request not found.")
    return _rfq_view(rfq)


class QuoteIn(BaseModel):
    supplier_id: uuid.UUID
    prices: dict = Field(description="{product_id: price per base unit}")
    delivery_days: Optional[int] = None
    note: Optional[str] = None


@router.post("/rfqs/{rfq_id}/quotes")
def record_quote(rfq_id: uuid.UUID, payload: QuoteIn, db: Session = Depends(get_db)):
    """Record a supplier's offer by hand (they phoned, or the reply was unclear)."""
    from datetime import datetime, timezone
    from decimal import Decimal

    rfq = db.get(SupplierQuoteRequest, rfq_id)
    if rfq is None:
        raise NotFoundError("Request not found.")
    if rfq.status != "open":
        raise ValidationError("{} is already decided.".format(rfq.number))
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
    return _rfq_view(rfq)


@router.post("/rfqs/{rfq_id}/decide")
def decide_rfq(rfq_id: uuid.UUID, db: Session = Depends(get_db)):
    """Compare the offers now and raise the purchase orders."""
    triggers.decide(db, rfq_id)
    return get_rfq(rfq_id, db)


@router.post("/rfqs/{rfq_id}/cancel")
def cancel_rfq(rfq_id: uuid.UUID, db: Session = Depends(get_db)):
    rfq = db.get(SupplierQuoteRequest, rfq_id)
    if rfq is None:
        raise NotFoundError("Request not found.")
    rfq.status = "cancelled"
    db.commit()
    return _rfq_view(rfq)


@router.get("/feedback")
def feedback(db: Session = Depends(get_db)):
    """Ratings and complaints customers gave after delivery."""
    rows = db.execute(select(CustomerFeedback).order_by(CustomerFeedback.created_at.desc()).limit(200)).scalars().all()
    names = {c.id: c.name for c in db.execute(select(Customer).where(Customer.id.in_({r.customer_id for r in rows}))).scalars()} if rows else {}
    ratings = [r.rating for r in rows if r.rating]
    return {"average": round(sum(ratings) / len(ratings), 2) if ratings else None, "complaints": sum(1 for r in rows if r.complaint),
            "items": [{"id": r.id, "customer_id": r.customer_id, "customer": names.get(r.customer_id), "rating": r.rating, "comment": r.comment,
                       "complaint": r.complaint, "task_id": r.task_id, "delivery_id": r.delivery_id, "created_at": r.created_at} for r in rows]}
