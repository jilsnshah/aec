"""Money in and out: payments, receivables, payables and statements."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..services import finance
from .auth import require_user
from .pagination import PageParams, page_params

router = APIRouter(prefix="/api", tags=["finance"])


class PaymentIn(BaseModel):
    direction: str = Field(pattern="^(in|out)$", description="in: money received from a customer; out: money paid to a supplier.")
    amount: Decimal = Field(gt=0)
    paid_on: Optional[date] = Field(default=None, description="Date of the payment (YYYY-MM-DD); today if omitted.")
    customer_id: Optional[uuid.UUID] = Field(default=None, description="For money in.")
    supplier_id: Optional[uuid.UUID] = Field(default=None, description="For money out.")
    method: str = Field(default="bank", description="cash, bank, upi, cheque, card or other.")
    reference: Optional[str] = Field(default=None, max_length=128, description="Cheque number, UTR, transaction id.")
    notes: Optional[str] = None
    sales_order_id: Optional[uuid.UUID] = Field(default=None, description="Optional: the order this money is for.")
    purchase_order_id: Optional[uuid.UUID] = Field(default=None, description="Optional: the purchase order this pays for.")


class VoidIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


@router.get("/payments")
def list_payments(
    direction: Optional[str] = Query(default=None, pattern="^(in|out)$"),
    customer_id: Optional[uuid.UUID] = Query(default=None),
    supplier_id: Optional[uuid.UUID] = Query(default=None),
    start: Optional[date] = Query(default=None),
    end: Optional[date] = Query(default=None),
    search: Optional[str] = Query(default=None, description="Matches number, reference or party name."),
    include_voided: bool = Query(default=False),
    paging: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
):
    """Payments received and made, newest first."""
    filters = dict(direction=direction, customer_id=customer_id, supplier_id=supplier_id, start=start, end=end,
                   search=search, include_voided=include_voided)
    items = finance.list_payments(db, paging.limit, paging.offset, **filters)
    return paging.page([finance.payment_view(p) for p in items], finance.count_payments(db, **filters))


@router.post("/payments", status_code=201)
def record_payment(payload: PaymentIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Record money received from a customer (in) or paid to a supplier (out)."""
    payment = finance.record_payment(db, created_by_id=user.id, **payload.model_dump())
    return finance.payment_view(payment)


@router.post("/payments/{payment_id}/void")
def void_payment(payment_id: uuid.UUID, payload: Optional[VoidIn] = None, db: Session = Depends(get_db)):
    """Void a payment entered by mistake. It stays on record, marked void."""
    return finance.payment_view(finance.void_payment(db, payment_id, payload.reason if payload else None))


@router.get("/finance/receivables")
def receivables(db: Session = Depends(get_db)):
    """What each customer owes for goods delivered: open, overdue, ageing buckets
    past the due date, credit limit use; and every overdue invoice."""
    return finance.receivables(db)


@router.get("/finance/payables")
def payables(db: Session = Depends(get_db)):
    """What the business owes each supplier for goods received, with ageing and
    overdue bills."""
    return finance.payables(db)


@router.get("/finance/customers/{customer_id}/statement")
def customer_statement(customer_id: uuid.UUID, db: Session = Depends(get_db)):
    """A customer's account: invoices (deliveries) and payments with a running balance."""
    return finance.statement(db, "customer", customer_id)


@router.get("/finance/suppliers/{supplier_id}/statement")
def supplier_statement(supplier_id: uuid.UUID, db: Session = Depends(get_db)):
    """A supplier's account: bills (goods received) and payments with a running balance."""
    return finance.statement(db, "supplier", supplier_id)
