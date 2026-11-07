"""Customer master endpoints."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..services import customers as customer_service
from .pagination import PageParams, page_params

router = APIRouter(prefix="/api/customers", tags=["customers"])


@router.get("", response_model=schemas.Page[schemas.CustomerListRow])
def list_customers(
    search: Optional[str] = Query(default=None, description="Matches name, phone or email."),
    include_inactive: bool = Query(default=False),
    sort_by: str = Query(default="name"),
    sort_dir: str = Query(default="asc", pattern="^(asc|desc)$"),
    paging: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
):
    customers = customer_service.list_customers(
        db, search, include_inactive, sort_by, sort_dir, paging.limit, paging.offset
    )
    stats = customer_service.customer_stats(db, [customer.id for customer in customers])
    items = [
        {**schemas.CustomerOut.model_validate(customer).model_dump(), **stats[customer.id]}
        for customer in customers
    ]
    return paging.page(items, customer_service.count_customers(db, search, include_inactive))


@router.post("", response_model=schemas.CustomerOut, status_code=201)
def create_customer(payload: schemas.CustomerCreate, db: Session = Depends(get_db)):
    return customer_service.create_customer(db, **payload.model_dump())


@router.get("/{customer_id}", response_model=schemas.CustomerDetailOut)
def get_customer(customer_id: uuid.UUID, db: Session = Depends(get_db)):
    customer = customer_service.get_customer(db, customer_id)
    payload = schemas.CustomerDetailOut.model_validate(customer).model_dump()
    payload["outstanding"] = customer_service.customer_outstanding(db, customer_id)
    payload["orders"] = [
        schemas.OrderOut.model_validate(order)
        for order in customer_service.customer_orders(db, customer_id)
    ]
    return payload


@router.patch("/{customer_id}", response_model=schemas.CustomerOut)
def update_customer(
    customer_id: uuid.UUID, payload: schemas.CustomerUpdate, db: Session = Depends(get_db)
):
    return customer_service.update_customer(db, customer_id, payload.model_dump(exclude_unset=True))


@router.post("/{customer_id}/archive", response_model=schemas.CustomerOut)
def archive_customer(customer_id: uuid.UUID, db: Session = Depends(get_db)):
    return customer_service.archive_customer(db, customer_id)
