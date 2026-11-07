"""Product master endpoints."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..services import products as product_service
from .pagination import PageParams, page_params

router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("", response_model=schemas.Page[schemas.ProductOut])
def list_products(
    search: Optional[str] = Query(default=None, description="Matches SKU or name."),
    include_inactive: bool = Query(default=False),
    sort_by: str = Query(default="name"),
    sort_dir: str = Query(default="asc", pattern="^(asc|desc)$"),
    paging: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
):
    items = product_service.list_products(
        db, search, include_inactive, sort_by, sort_dir, paging.limit, paging.offset
    )
    return paging.page(items, product_service.count_products(db, search, include_inactive))


@router.post("", response_model=schemas.ProductOut, status_code=201)
def create_product(payload: schemas.ProductCreate, db: Session = Depends(get_db)):
    product = product_service.create_product(
        db,
        sku=payload.sku,
        name=payload.name,
        unit_of_measure=payload.unit_of_measure,
        mrp=payload.mrp,
        description=payload.description,
        opening_stock=payload.opening_stock,
        opening_unit_cost=payload.opening_unit_cost,
    )
    return product_service.product_view(db, product)


@router.get("/{product_id}", response_model=schemas.ProductOut)
def get_product(product_id: uuid.UUID, db: Session = Depends(get_db)):
    return product_service.product_view(db, product_service.get_product(db, product_id))


@router.patch("/{product_id}", response_model=schemas.ProductOut)
def update_product(
    product_id: uuid.UUID, payload: schemas.ProductUpdate, db: Session = Depends(get_db)
):
    product = product_service.update_product(
        db, product_id, payload.model_dump(exclude_unset=True)
    )
    return product_service.product_view(db, product)


@router.post("/{product_id}/archive", response_model=schemas.ProductOut)
def archive_product(product_id: uuid.UUID, db: Session = Depends(get_db)):
    return product_service.product_view(db, product_service.archive_product(db, product_id))
