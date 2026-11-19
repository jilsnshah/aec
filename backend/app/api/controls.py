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


class ControlsIn(BaseModel):
    credit_check: Optional[str] = None
    block_on_overdue: Optional[bool] = None
    overdue_grace_days: Optional[int] = None
    max_discount_percent: Optional[float] = None
    min_margin_percent: Optional[float] = None
    block_below_cost: Optional[bool] = None


@router.put("/controls/settings")
def update_controls(payload: ControlsIn, db: Session = Depends(get_db)):
    """Change the order controls: credit_check off/warn/block, block_on_overdue,
    overdue_grace_days, max_discount_percent, min_margin_percent (0 = no limit),
    block_below_cost. Only the fields sent change."""
    from ..services import integration_settings as settings_service

    row = settings_service.update(db, settings_service.CONTROLS, config=payload.model_dump(exclude_none=True))
    return row.config


@router.get("/documents/{kind}/{record_id}")
def document_link(kind: str, record_id: uuid.UUID, db: Session = Depends(get_db)):
    """A link to a printable document: kind 'quotation' (enquiry id) or
    'invoice' (sales order id, once Tally has the invoice). Share the url as a
    markdown link."""
    from ..errors import NotFoundError, ValidationError
    from ..services import enquiries as enquiry_service, tally_sync

    if kind == "quotation":
        enquiry = enquiry_service.get_enquiry(db, record_id)
        return {"title": "Quotation {}".format(enquiry.enquiry_number), "url": "/api/enquiries/{}/quotation.pdf".format(record_id)}
    if kind == "invoice":
        row = tally_sync.invoice_for_order(db, record_id)
        if row is None:
            raise NotFoundError("This order has no invoice in Tally yet.")
        return {"title": "Invoice", "url": "/api/integrations/invoices/{}.pdf".format(record_id)}
    raise ValidationError("kind must be quotation or invoice.")
