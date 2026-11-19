"""Stock adjustments and physical stock counts."""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..services import adjustments
from .auth import require_user

router = APIRouter(prefix="/api/stock-adjustments", tags=["stock"])


class AdjustmentLine(BaseModel):
    product_id: uuid.UUID
    counted_quantity: Optional[str] = Field(default=None, description="What is on the shelf (for a count).")
    quantity_change: Optional[str] = Field(default=None, description="Plus or minus, when not counting.")
    reason: Optional[str] = Field(default=None, description="count, damaged, lost, expired, found, sample or correction.")
    unit_cost: Optional[str] = Field(default=None, description="For increases; defaults to the average cost.")
    note: Optional[str] = None
    warehouse_id: Optional[uuid.UUID] = Field(default=None, description="Warehouse counted or adjusted; omit for the whole stock (increases go to the default warehouse).")


class AdjustmentIn(BaseModel):
    lines: List[AdjustmentLine]
    as_count: bool = Field(default=False, description="Post as one physical stock count (shared count number).")


@router.get("")
def list_adjustments(
    product_id: Optional[uuid.UUID] = Query(default=None),
    reason: Optional[str] = Query(default=None),
    count_number: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Stock adjustments, newest first, with totals by reason (value at cost)."""
    return adjustments.list_adjustments(db, limit, offset, product_id=product_id, reason=reason, count_number=count_number)


@router.get("/count-sheet")
def count_sheet(category: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    """Products to count, with the quantity the books expect, what is set aside
    for customers, average cost and when each was last counted."""
    return {"products": adjustments.count_sheet(db, category), "reasons": adjustments.REASONS}


@router.post("", status_code=201)
def post_adjustments(payload: AdjustmentIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Post a stock count (counted quantities) or adjustments (plus or minus
    with a reason). Decreases are valued at FIFO cost; if stock falls below what
    is set aside, the newest orders become short. Increases are reserved for
    customers already waiting."""
    return adjustments.post(db, [line.model_dump() for line in payload.lines], user.id, payload.as_count)


@router.get("/{adjustment_id}")
def get_adjustment(adjustment_id: uuid.UUID, db: Session = Depends(get_db)):
    return adjustments.get(db, adjustment_id)
