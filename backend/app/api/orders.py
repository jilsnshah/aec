"""Sales order endpoints."""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..models import User
from ..services import controls, notifications
from ..services import orders as order_service
from .auth import require_user
from ..services import tally_sync
from .pagination import PageParams, page_params

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _detail(db: Session, order) -> dict:
    payload = schemas.OrderDetailOut.model_validate(order).model_dump()
    payload["allocations"] = order_service.order_allocations(db, order.id)
    payload["financials"] = order_service.order_financials(db, order)
    payload["enquiry_number"] = order.enquiry.enquiry_number if order.enquiry else None
    return payload


@router.get("", response_model=schemas.Page[schemas.OrderOut])
def list_orders(
    search: Optional[str] = Query(default=None, description="Matches order number or customer."),
    status: Optional[str] = Query(default=None),
    customer_id: Optional[uuid.UUID] = Query(default=None),
    product_id: Optional[uuid.UUID] = Query(default=None),
    sort_by: str = Query(default="created_at", description="created_at, order_number or total_amount."),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    paging: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
):
    items = order_service.list_orders(
        db, search, status, customer_id, product_id, sort_by, sort_dir, paging.limit, paging.offset
    )
    total = order_service.count_orders(db, search, status, customer_id, product_id)
    return paging.page(items, total)


@router.post("", response_model=schemas.OrderDetailOut, status_code=201)
def create_order(
    payload: schemas.OrderCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    override: bool = Query(default=False, description="Admin approval of an order on hold (needs override_reason)."),
    override_reason: Optional[str] = Query(default=None),
):
    lines = [item.model_dump() for item in payload.items]
    controls.enforce(db, payload.customer_id, lines, user, override, override_reason, "a new order")
    order = order_service.create_order(
        db,
        customer_id=payload.customer_id,
        lines=[item.model_dump() for item in payload.items],
        notes=payload.notes,
        contact_id=payload.contact_id,
        delivery_address_id=payload.delivery_address_id,
    )
    # Placed: to Tally as a Sales Order and an invoice, and the invoice on to
    # the customer -- after the response, so placing the order stays fast.
    for sync_id in tally_sync.queue_sales_order(db, order):
        background.add_task(tally_sync.process, sync_id)
    background.add_task(notifications.order_placed, order.id)
    return _detail(db, order)


@router.get("/{order_id}", response_model=schemas.OrderDetailOut)
def get_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
    return _detail(db, order_service.get_order(db, order_id))


@router.post("/{order_id}/cancel", response_model=schemas.OrderDetailOut)
def cancel_order(
    order_id: uuid.UUID,
    payload: Optional[schemas.CancelRequest] = None,
    db: Session = Depends(get_db),
):
    reason = payload.reason if payload else None
    return _detail(db, order_service.cancel_order(db, order_id, reason))


@router.post("/{order_id}/cancel-remaining", response_model=schemas.OrderDetailOut)
def cancel_remaining(
    order_id: uuid.UUID,
    payload: Optional[schemas.CancelRequest] = None,
    db: Session = Depends(get_db),
):
    reason = payload.reason if payload else None
    return _detail(db, order_service.cancel_remaining(db, order_id, reason))


# ---------------------------------------------------------------------------
# Returns (credit notes)
# ---------------------------------------------------------------------------
from pydantic import BaseModel as _BaseModel, Field as _Field  # noqa: E402

from ..services import returns as return_service  # noqa: E402


class ReturnLineIn(_BaseModel):
    order_item_id: uuid.UUID
    quantity: str
    restock: bool = _Field(default=True, description="False when the goods are damaged and cannot be sold again.")


class ReturnIn(_BaseModel):
    reason: str = _Field(description="damaged, wrong_item, quality, excess or other.")
    note: Optional[str] = None
    lines: List[ReturnLineIn]
    warehouse_id: Optional[uuid.UUID] = _Field(default=None, description="Where restocked goods go; the default warehouse if omitted.")


@router.get("/{order_id}/returnable")
def returnable_lines(order_id: uuid.UUID, db: Session = Depends(get_db)):
    """Each line of an order: delivered, already returned and still returnable."""
    return {"lines": return_service.returnable(db, order_id), "reasons": return_service.REASONS}


@router.post("/{order_id}/returns", status_code=201)
def create_return(order_id: uuid.UUID, payload: ReturnIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Record goods a customer sent back (a credit note). The value is credited
    to the customer's account; lines with restock true go back into stock at the
    cost they were delivered at."""
    record = return_service.create_return(db, order_id, [line.model_dump() for line in payload.lines], payload.reason, payload.note, user.id, payload.warehouse_id)
    return return_service.view(record)


@router.get("/{order_id}/returns")
def order_returns(order_id: uuid.UUID, db: Session = Depends(get_db)):
    return return_service.list_returns(db, order_id=order_id)



@router.get("/{order_id}/confirmation")
def confirmation_preview(order_id: uuid.UUID, db: Session = Depends(get_db)):
    """The order confirmation text, as it would go on WhatsApp."""
    return notifications.confirmation_text(order_service.get_order(db, order_id))


@router.post("/{order_id}/send-confirmation")
def send_confirmation(order_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Send the order confirmation on WhatsApp now (needs the approved template)."""
    return notifications.send_order_confirmation(db, order_id, user)
