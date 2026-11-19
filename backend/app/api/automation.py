"""Automation pipelines (Settings -> Automation)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..services import automation
from .auth import require_user

router = APIRouter(prefix="/api/automation", tags=["automation"])


class FlowIn(BaseModel):
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    name: Optional[str] = None


@router.get("/library")
def library():
    """Every step type the flows can use: who can do it, the modes, limits,
    AI, channels and timing it supports, and whether it is live today."""
    return automation.library()


@router.get("/flows/{key}")
def get_flow(key: str, db: Session = Depends(get_db)):
    """The sales or purchase flow: steps (nodes with their settings) and order (edges)."""
    return automation.get(db, key)


@router.put("/flows/{key}")
def save_flow(key: str, payload: FlowIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Save a flow. Steps that existing settings control (order confirmation,
    invoice timing) update those settings too."""
    return automation.save(db, key, payload.model_dump(), user)


@router.post("/flows/{key}/reset")
def reset_flow(key: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Back to the default flow."""
    return automation.reset(db, key, user)


# --- Approvals: what the agents prepared for a person ----------------------------


class ApproveIn(BaseModel):
    body: Optional[str] = None


@router.get("/approvals")
def approvals(db: Session = Depends(get_db)):
    """Replies waiting to be sent and orders the agents held for a person."""
    from sqlalchemy import select

    from ..models import AgentDraft, Customer
    from ..services import outbox

    drafts = db.execute(select(AgentDraft, Customer.name).join(Customer, AgentDraft.customer_id == Customer.id)
                        .where(AgentDraft.status == "held").order_by(AgentDraft.created_at.desc())).all()
    return {
        "messages": outbox.list_messages(db, "pending_approval"),
        "failed": outbox.list_messages(db, "failed", limit=30),
        "orders": [{"id": d.id, "customer_id": d.customer_id, "customer": name, "channel": d.channel, "sender": d.sender, "items": d.items,
                    "total": float(d.total), "note": d.note, "created_at": d.created_at} for d, name in drafts],
    }


@router.get("/messages")
def sent_messages(status: Optional[str] = None, db: Session = Depends(get_db)):
    """Messages the agents and people sent (or tried to)."""
    from ..services import outbox

    return {"items": outbox.list_messages(db, status, limit=200)}


@router.post("/messages/{message_id}/approve")
def approve_message(message_id: str, payload: Optional[ApproveIn] = None, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Send a held reply (optionally edited first), or retry a failed one."""
    import uuid as _uuid

    from ..services import outbox

    return outbox.approve(db, _uuid.UUID(message_id), user, payload.body if payload else None)


@router.post("/messages/{message_id}/discard")
def discard_message(message_id: str, db: Session = Depends(get_db)):
    import uuid as _uuid

    from ..services import outbox

    return outbox.discard(db, _uuid.UUID(message_id))


@router.post("/drafts/{draft_id}/place")
def place_draft(draft_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Place an order the agent held for approval (order controls still apply)."""
    import uuid as _uuid

    from ..errors import NotFoundError, ValidationError
    from ..models import AgentDraft
    from ..services import controls, notifications
    from ..services import orders as order_service

    draft = db.get(AgentDraft, _uuid.UUID(draft_id))
    if draft is None:
        raise NotFoundError("Draft not found.")
    if draft.status != "held":
        raise ValidationError("This order was already {}.".format(draft.status))
    lines = [{"product_id": i["product_id"], "quantity_ordered": str(i["quantity"]), "discount_percent": str(i["discount_percent"]), "unit_price": None} for i in draft.items]
    controls.enforce(db, draft.customer_id, lines, user)
    order = order_service.create_order(db, draft.customer_id, lines, notes="Taken by TAI on {}, approved by {}.".format(draft.channel, user.username))
    draft.status, draft.order_id = "placed", order.id
    db.commit()
    notifications.order_placed(order.id)
    return {"order_id": order.id, "order_number": order.order_number}


@router.post("/drafts/{draft_id}/discard")
def discard_draft(draft_id: str, db: Session = Depends(get_db)):
    import uuid as _uuid

    from ..errors import NotFoundError
    from ..models import AgentDraft

    draft = db.get(AgentDraft, _uuid.UUID(draft_id))
    if draft is None:
        raise NotFoundError("Draft not found.")
    draft.status = "cancelled"
    db.commit()
    return {"ok": True}
