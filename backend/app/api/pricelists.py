"""Customer price lists."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import pricelists

router = APIRouter(prefix="/api/price-lists", tags=["pricing"])


class PriceItemIn(BaseModel):
    product_id: uuid.UUID
    min_quantity: Optional[str] = "0"
    price: Optional[str] = None
    discount_percent: Optional[str] = None


class PriceListIn(BaseModel):
    name: str
    discount_percent: Optional[str] = "0"
    notes: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    is_active: Optional[bool] = None
    items: Optional[List[PriceItemIn]] = None


class ResolveLine(BaseModel):
    product_id: uuid.UUID
    quantity: Optional[str] = "1"


class ResolveIn(BaseModel):
    customer_id: Optional[uuid.UUID] = None
    lines: List[ResolveLine]


@router.get("")
def list_price_lists(include_inactive: bool = Query(default=False), db: Session = Depends(get_db)):
    """Price lists with their quantity breaks and how many customers use each."""
    return {"items": pricelists.list_all(db, include_inactive)}


@router.post("", status_code=201)
def create_price_list(payload: PriceListIn, db: Session = Depends(get_db)):
    """Create a price list: a default discount and per-product lines (fixed price
    or discount, from a minimum quantity)."""
    return pricelists.save(db, payload.model_dump(exclude_unset=False))


@router.post("/resolve")
def resolve_prices(payload: ResolveIn, db: Session = Depends(get_db)):
    """The price a customer gets on each product and quantity from their price
    list (as discount off MRP and net price), and which rule gave it."""
    return pricelists.resolve(db, payload.customer_id, [line.model_dump() for line in payload.lines])


@router.get("/{list_id}")
def get_price_list(list_id: uuid.UUID, db: Session = Depends(get_db)):
    return pricelists.get(db, list_id)


@router.put("/{list_id}")
def update_price_list(list_id: uuid.UUID, payload: PriceListIn, db: Session = Depends(get_db)):
    """Replace a price list's settings and lines."""
    return pricelists.save(db, payload.model_dump(exclude_unset=True), list_id)
