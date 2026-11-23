"""The trigger engine: run a trigger now, the activity log and customer
feedback. Purchase enquiries have their own API (purchase_enquiries.py)."""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import NotFoundError, ValidationError
from ..models import AutomationEvent, Customer, CustomerFeedback
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


@router.get("/feedback")
def feedback(db: Session = Depends(get_db)):
    """Ratings and complaints customers gave after delivery."""
    rows = db.execute(select(CustomerFeedback).order_by(CustomerFeedback.created_at.desc()).limit(200)).scalars().all()
    names = {c.id: c.name for c in db.execute(select(Customer).where(Customer.id.in_({r.customer_id for r in rows}))).scalars()} if rows else {}
    ratings = [r.rating for r in rows if r.rating]
    return {"average": round(sum(ratings) / len(ratings), 2) if ratings else None, "complaints": sum(1 for r in rows if r.complaint),
            "items": [{"id": r.id, "customer_id": r.customer_id, "customer": names.get(r.customer_id), "rating": r.rating, "comment": r.comment,
                       "complaint": r.complaint, "task_id": r.task_id, "delivery_id": r.delivery_id, "created_at": r.created_at} for r in rows]}
