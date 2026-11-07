"""Customer enquiry endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..services import tally_sync
from ..services import enquiries as enquiry_service
from .orders import _detail
from .pagination import PageParams, page_params

router = APIRouter(prefix="/api/enquiries", tags=["enquiries"])


@router.get("", response_model=schemas.Page[schemas.EnquiryOut])
def list_enquiries(
    search: Optional[str] = Query(default=None, description="Matches enquiry number or customer."),
    status: Optional[str] = Query(default=None, description="OPEN, CONVERTED or LOST."),
    customer_id: Optional[uuid.UUID] = Query(default=None),
    created_from: Optional[datetime] = Query(default=None),
    created_to: Optional[datetime] = Query(default=None),
    paging: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
):
    items = [
        enquiry_service.to_view(enquiry)
        for enquiry in enquiry_service.list_enquiries(
            db, search, status, customer_id, created_from, created_to, paging.limit, paging.offset
        )
    ]
    total = enquiry_service.count_enquiries(
        db, search, status, customer_id, created_from, created_to
    )
    return paging.page(items, total)


@router.post("", response_model=schemas.EnquiryOut, status_code=201)
def create_enquiry(payload: schemas.EnquiryCreate, db: Session = Depends(get_db)):
    """Open an enquiry. Each line is priced from the product master's MRP."""
    enquiry = enquiry_service.create_enquiry(
        db,
        customer_id=payload.customer_id,
        items=[item.model_dump() for item in payload.items],
        notes=payload.notes,
    )
    return enquiry_service.to_view(enquiry)


@router.get("/{enquiry_id}", response_model=schemas.EnquiryOut)
def get_enquiry(enquiry_id: uuid.UUID, db: Session = Depends(get_db)):
    return enquiry_service.to_view(enquiry_service.get_enquiry(db, enquiry_id))


@router.patch("/{enquiry_id}", response_model=schemas.EnquiryOut)
def update_enquiry(
    enquiry_id: uuid.UUID, payload: schemas.EnquiryUpdate, db: Session = Depends(get_db)
):
    """Edit an OPEN enquiry. A converted or lost enquiry is read-only."""
    changes = payload.model_dump(exclude_unset=True)
    if "items" in changes and changes["items"] is not None:
        changes["items"] = [dict(item) for item in changes["items"]]
    return enquiry_service.to_view(enquiry_service.update_enquiry(db, enquiry_id, changes))


@router.post("/{enquiry_id}/convert", response_model=schemas.EnquiryConversionResult, status_code=201)
def convert_enquiry(enquiry_id: uuid.UUID, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Win the deal: create the sales order and close the enquiry.

    The order is created by the Phase 1 service in the same transaction, so
    stock allocation and pending quantities behave exactly as they do for an
    order entered directly. Converting the same enquiry twice returns 409 and
    never creates a second order.
    """
    result = enquiry_service.convert_enquiry(db, enquiry_id)
    for sync_id in tally_sync.queue_sales_order(db, result["order"]):
        background.add_task(tally_sync.process, sync_id)
    return {
        "enquiry": enquiry_service.to_view(result["enquiry"]),
        "order": _detail(db, result["order"]),
    }


@router.post("/{enquiry_id}/mark-lost", response_model=schemas.EnquiryOut)
def mark_lost(
    enquiry_id: uuid.UUID,
    payload: Optional[schemas.MarkLostRequest] = None,
    db: Session = Depends(get_db),
):
    """Close an enquiry that did not become a deal. No order, no stock movement."""
    reason = payload.reason if payload else None
    return enquiry_service.to_view(enquiry_service.mark_lost(db, enquiry_id, reason))
