"""Business controls (credit, discount, margin) and the audit log."""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import controls

router = APIRouter(prefix="/api", tags=["controls"])


class DraftLine(BaseModel):
    product_id: uuid.UUID
    quantity_ordered: float = 0
    unit_price: Optional[float] = None
    discount_percent: float = 0


class DraftIn(BaseModel):
    customer_id: Optional[uuid.UUID] = None
    items: List[DraftLine]


@router.post("/controls/check")
def check(payload: DraftIn, db: Session = Depends(get_db)):
    """Which controls a draft order would trip: holds (block, or need an admin's
    approval) and warnings. Changes nothing."""
    result = controls.evaluate(db, payload.customer_id, [line.model_dump() for line in payload.items])
    return {"mode": result["mode"], "holds": result["holds"], "warnings": result["warnings"]}


@router.get("/audit")
def audit(limit: int = Query(default=100, ge=1, le=500), action: Optional[str] = None, entity_id: Optional[str] = None, db: Session = Depends(get_db)):
    """The audit log, newest first: control overrides, stock adjustments,
    returns, voided payments."""
    return {"events": controls.audit_list(db, limit, action, entity_id)}
