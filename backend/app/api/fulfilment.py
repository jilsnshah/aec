"""Customer fulfilment: what is owed, and handing it over."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..services import deliveries as delivery_service
from .pagination import PageParams, page_params

router = APIRouter(prefix="/api", tags=["fulfilment"])


@router.get("/orders/{order_id}/fulfilment", response_model=schemas.OrderFulfilmentOut)
def order_fulfilment(order_id: uuid.UUID, db: Session = Depends(get_db)):
    """Per line: ordered, delivered, reserved, unallocated and deliverable now."""
    return delivery_service.order_fulfilment(db, order_id)


@router.post("/orders/{order_id}/deliveries", response_model=schemas.DeliveryResult, status_code=201)
def create_delivery(
    order_id: uuid.UUID, payload: schemas.DeliveryRequest, db: Session = Depends(get_db)
):
    """Hand reserved goods to the customer.

    Only reserved quantity can be delivered, and only up to what is still
    outstanding. Physical stock falls, the reservation is released and the cost
    of goods is taken from the FIFO cost layers -- all in one transaction.
    """
    return delivery_service.create_delivery(
        db,
        order_id=order_id,
        lines=[line.model_dump() for line in payload.lines],
        reference=payload.reference,
        notes=payload.notes,
        idempotency_key=payload.idempotency_key,
    )


@router.get("/deliveries", response_model=schemas.Page[schemas.DeliveryRow])
def list_deliveries(
    search: Optional[str] = Query(default=None),
    customer_id: Optional[uuid.UUID] = Query(default=None),
    order_id: Optional[uuid.UUID] = Query(default=None),
    paging: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
):
    items = delivery_service.list_deliveries(
        db, search, customer_id, order_id, paging.limit, paging.offset
    )
    return paging.page(items, delivery_service.count_deliveries(db, search, customer_id, order_id))


@router.get("/inventory/pending-commitments", response_model=schemas.PendingCommitmentsOut)
def pending_commitments(
    search: Optional[str] = Query(default=None, description="Order number, customer or product."),
    customer_id: Optional[uuid.UUID] = Query(default=None),
    product_id: Optional[uuid.UUID] = Query(default=None),
    order_id: Optional[uuid.UUID] = Query(default=None),
    created_from: Optional[datetime] = Query(default=None),
    created_to: Optional[datetime] = Query(default=None),
    only_unallocated: bool = Query(default=False, description="Only lines still awaiting stock."),
    only_reserved: bool = Query(default=False, description="Only lines with stock set aside."),
    db: Session = Depends(get_db),
):
    """What the business still owes customers, oldest order first."""
    return delivery_service.pending_commitments(
        db,
        customer_id=customer_id,
        product_id=product_id,
        order_id=order_id,
        search=search,
        created_from=created_from,
        created_to=created_to,
        only_unallocated=only_unallocated,
        only_reserved=only_reserved,
    )
