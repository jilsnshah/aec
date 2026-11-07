"""Sales order endpoints."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..services import orders as order_service
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
    payload: schemas.OrderCreate, background: BackgroundTasks, db: Session = Depends(get_db)
):
    order = order_service.create_order(
        db,
        customer_id=payload.customer_id,
        lines=[item.model_dump() for item in payload.items],
        notes=payload.notes,
    )
    # Placed: to Tally as a Sales Order and an invoice, and the invoice on to
    # the customer -- after the response, so placing the order stays fast.
    for sync_id in tally_sync.queue_sales_order(db, order):
        background.add_task(tally_sync.process, sync_id)
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
