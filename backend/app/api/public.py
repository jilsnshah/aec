"""Pages customers open without signing in: their own enquiry page, reached by
a secret link. Nothing here works without a valid token."""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import portal

router = APIRouter(prefix="/api/public", tags=["public"])


class PublicLine(BaseModel):
    product_id: uuid.UUID
    quantity: float = Field(gt=0, le=1_000_000)


class PublicEnquiryIn(BaseModel):
    items: List[PublicLine] = Field(min_length=1, max_length=40)
    notes: Optional[str] = Field(default=None, max_length=1000)
    name: Optional[str] = Field(default=None, max_length=120, description="Who is asking (for site staff).")
    phone: Optional[str] = Field(default=None, max_length=32)


@router.get("/e/{token}")
def enquiry_page(token: str, db: Session = Depends(get_db)):
    return portal.page(db, token)


@router.post("/e/{token}", status_code=201)
def send_enquiry(token: str, payload: PublicEnquiryIn, db: Session = Depends(get_db)):
    return portal.send(db, token, [i.model_dump() for i in payload.items], payload.notes, payload.name, payload.phone)


@router.get("/e/{token}/orders")
def my_orders(token: str, db: Session = Depends(get_db)):
    return portal.orders(db, token)


@router.get("/e/{token}/statement")
def my_statement(token: str, db: Session = Depends(get_db)):
    return portal.statement(db, token)


@router.get("/e/{token}/invoices")
def my_invoices(token: str, db: Session = Depends(get_db)):
    return portal.invoices(db, token)


@router.get("/e/{token}/invoices/{sync_id}.pdf")
def my_invoice_pdf(token: str, sync_id: uuid.UUID, db: Session = Depends(get_db)):
    filename, content = portal.invoice_pdf(db, token, sync_id)
    return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="{}"'.format(filename)})


@router.post("/e/{token}/reorder/{order_id}", status_code=201)
def order_again(token: str, order_id: uuid.UUID, db: Session = Depends(get_db)):
    return portal.reorder(db, token, order_id)
