"""Record-level intelligence: timelines, the customer 360, price history,
order checks, payment status per order, supplier scorecards and purchase
suggestions. Read-only; the screens and the assistant share them."""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import records

router = APIRouter(prefix="/api/records", tags=["records"])


@router.get("/timeline")
def timeline(
    customer_id: Optional[uuid.UUID] = Query(default=None),
    supplier_id: Optional[uuid.UUID] = Query(default=None),
    product_id: Optional[uuid.UUID] = Query(default=None),
    order_id: Optional[uuid.UUID] = Query(default=None),
    limit: int = Query(default=60, ge=1, le=300),
    db: Session = Depends(get_db),
):
    """Everything that happened to one customer, supplier, product or order,
    newest first: orders, enquiries, deliveries, receipts, payments, stock
    movements and follow-ups. Pass exactly one id."""
    return {"events": records.timeline(db, customer_id, supplier_id, product_id, order_id, limit)}


@router.get("/customers/{customer_id}/profile")
def customer_profile(customer_id: uuid.UUID, db: Session = Depends(get_db)):
    """A customer's full picture: segment, lifetime value, order frequency,
    average discount, enquiry win rate, money owed and credit used, monthly
    spend for the last year and the products they buy most."""
    return records.customer_profile(db, customer_id)


@router.get("/products/{product_id}/prices")
def product_prices(product_id: uuid.UUID, customer_id: Optional[uuid.UUID] = Query(default=None), db: Session = Depends(get_db)):
    """A product's selling price history (optionally to one customer), average
    margin, cost from each supplier (lowest, highest, last) and top buyers."""
    return records.product_prices(db, product_id, customer_id)


class CheckLine(BaseModel):
    product_id: uuid.UUID
    quantity_ordered: float = Field(default=0, ge=0)
    unit_price: Optional[float] = Field(default=None, ge=0)
    discount_percent: float = Field(default=0, ge=0, le=100)
    unit: Optional[str] = Field(default=None, description="Unit the quantity and price are in; omit for the base unit.")


class CheckIn(BaseModel):
    customer_id: Optional[uuid.UUID] = None
    items: List[CheckLine] = Field(default_factory=list)


@router.post("/order-check")
def order_check(payload: CheckIn, db: Session = Depends(get_db)):
    """Check a draft order before placing it: credit limit and overdue money,
    price below cost, thin margin, unusual discount, price lower than last
    time, and stock shortfall. Changes nothing."""
    return records.check_order(db, payload.customer_id, [item.model_dump() for item in payload.items])


@router.get("/order-payments")
def order_payments(db: Session = Depends(get_db)):
    """Per order id: invoiced (delivered) value, paid, open, days overdue and a
    status (paid, partly_paid, unpaid, overdue). Orders with no delivery are absent."""
    return records.order_payment_status(db)


@router.get("/suppliers/{supplier_id}/scorecard")
def supplier_scorecard(supplier_id: uuid.UUID, db: Session = Depends(get_db)):
    """A supplier's score (fill rate and on-time), late orders, and each product
    bought from them with their last cost against the cheapest supplier."""
    return records.supplier_scorecard(db, supplier_id)


@router.get("/purchase-suggestions")
def purchase_suggestions(db: Session = Depends(get_db)):
    """Products to buy now or soon, grouped by the supplier to buy from, with
    estimated quantities and cost."""
    return records.purchase_suggestions(db)
