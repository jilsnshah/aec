"""Party details (contacts, phone numbers and emails, addresses and delivery
sites), duplicate checks and merging, for customers and suppliers; and product
aliases, barcodes, supplier codes and units."""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..services import parties
from .auth import require_user

router = APIRouter(prefix="/api", tags=["parties"])
KIND = "{kind}"


class ContactIn(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    notes: Optional[str] = None
    is_primary: Optional[bool] = None
    is_active: Optional[bool] = None


class PointIn(BaseModel):
    kind: Optional[str] = Field(default=None, description="phone or email (when adding).")
    value: Optional[str] = None
    label: Optional[str] = Field(default=None, description="e.g. mobile, office, accounts, site.")
    contact_id: Optional[uuid.UUID] = None
    is_whatsapp: Optional[bool] = None
    is_primary: Optional[bool] = None
    is_active: Optional[bool] = None


class AddressIn(BaseModel):
    kind: Optional[str] = Field(default=None, description="billing, site, office or warehouse.")
    label: Optional[str] = Field(default=None, description="e.g. 'Sector 21 tower site'.")
    line: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    map_url: Optional[str] = None
    contact_id: Optional[uuid.UUID] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


class MergeIn(BaseModel):
    merge_id: uuid.UUID = Field(description="The duplicate record to merge into this one (it is archived).")


@router.get("/parties/{kind}/{party_id}/profile")
def get_profile(kind: str, party_id: uuid.UUID, include_inactive: bool = Query(default=False), db: Session = Depends(get_db)):
    """A customer's or supplier's full details: GSTIN, PAN, Tally ledger, contacts,
    phone numbers and emails, addresses and delivery sites. kind = customer or supplier."""
    return parties.profile(db, kind, party_id, include_inactive)


@router.post("/parties/{kind}/{party_id}/contacts", status_code=201)
def add_contact(kind: str, party_id: uuid.UUID, payload: ContactIn, db: Session = Depends(get_db)):
    """Add a person at the customer or supplier (name, role)."""
    return parties.save_contact(db, kind, party_id, payload.model_dump(exclude_unset=True))


@router.patch("/parties/{kind}/{party_id}/contacts/{contact_id}")
def update_contact(kind: str, party_id: uuid.UUID, contact_id: uuid.UUID, payload: ContactIn, db: Session = Depends(get_db)):
    """Change a contact; is_active false removes them."""
    return parties.save_contact(db, kind, party_id, payload.model_dump(exclude_unset=True), contact_id)


@router.post("/parties/{kind}/{party_id}/points", status_code=201)
def add_point(kind: str, party_id: uuid.UUID, payload: PointIn, db: Session = Depends(get_db)):
    """Add a phone number or email. A number or email can belong to one party only."""
    return parties.save_point(db, kind, party_id, payload.model_dump(exclude_unset=True))


@router.patch("/parties/{kind}/{party_id}/points/{point_id}")
def update_point(kind: str, party_id: uuid.UUID, point_id: uuid.UUID, payload: PointIn, db: Session = Depends(get_db)):
    """Change a phone number or email; is_active false removes it."""
    return parties.save_point(db, kind, party_id, payload.model_dump(exclude_unset=True), point_id)


@router.post("/parties/{kind}/{party_id}/addresses", status_code=201)
def add_address(kind: str, party_id: uuid.UUID, payload: AddressIn, db: Session = Depends(get_db)):
    """Add a billing address, office, warehouse or delivery site."""
    return parties.save_address(db, kind, party_id, payload.model_dump(exclude_unset=True))


@router.patch("/parties/{kind}/{party_id}/addresses/{address_id}")
def update_address(kind: str, party_id: uuid.UUID, address_id: uuid.UUID, payload: AddressIn, db: Session = Depends(get_db)):
    """Change an address; is_active false removes it."""
    return parties.save_address(db, kind, party_id, payload.model_dump(exclude_unset=True), address_id)


@router.get("/parties/{kind}/duplicates")
def find_duplicates(
    kind: str,
    name: Optional[str] = Query(default=None),
    phone: List[str] = Query(default=[]),
    email: List[str] = Query(default=[]),
    gstin: Optional[str] = Query(default=None),
    exclude_id: Optional[uuid.UUID] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Existing customers/suppliers that a new record may duplicate: blocking
    (same phone, email or GSTIN) and similar (similar name)."""
    return parties.duplicates(db, kind, name, phone, email, gstin, exclude_id)


@router.get("/parties/lookup")
def lookup(phone: Optional[str] = Query(default=None), email: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    """Which customer or supplier a phone number or email belongs to."""
    kind, party = parties.find_by_phone(db, phone) if phone else parties.find_by_email(db, email)
    return {"kind": kind, "id": party.id if party else None, "name": party.name if party else None}


@router.post("/parties/{kind}/{party_id}/merge")
def merge(kind: str, party_id: uuid.UUID, payload: MergeIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Merge a duplicate into this record: its orders, enquiries, payments,
    returns, calls, follow-ups, contacts, numbers and addresses move here, and
    the duplicate is archived. Recorded in the audit log."""
    return parties.merge(db, kind, party_id, payload.merge_id, user)


# --- Products ------------------------------------------------------------------


class AliasIn(BaseModel):
    kind: str = Field(default="alias", description="alias (another name), barcode or supplier_code.")
    value: str
    supplier_id: Optional[uuid.UUID] = None


class UnitIn(BaseModel):
    name: str = Field(description="e.g. tonne, bundle.")
    factor: str = Field(description="How many base units one of these holds, e.g. 20 (bags per tonne).")
    for_sales: bool = Field(default=True, description="Offered on quotes and sales orders.")
    for_purchase: bool = Field(default=True, description="Offered on purchase orders.")


@router.get("/products/{product_id}/names")
def product_names(product_id: uuid.UUID, db: Session = Depends(get_db)):
    """A product's other names (what customers call it), barcodes, supplier item codes and units."""
    return parties.product_names(db, product_id)


@router.post("/products/{product_id}/aliases", status_code=201)
def add_alias(product_id: uuid.UUID, payload: AliasIn, db: Session = Depends(get_db)):
    """Add another name, barcode or supplier item code for a product."""
    return parties.add_alias(db, product_id, payload.kind, payload.value, payload.supplier_id)


@router.delete("/products/{product_id}/aliases/{alias_id}")
def remove_alias(product_id: uuid.UUID, alias_id: uuid.UUID, db: Session = Depends(get_db)):
    return parties.remove_alias(db, product_id, alias_id)


@router.post("/products/{product_id}/units", status_code=201)
def add_unit(product_id: uuid.UUID, payload: UnitIn, db: Session = Depends(get_db)):
    """Add another unit the product is counted in, as a multiple of its base unit."""
    return parties.save_unit(db, product_id, payload.name, payload.factor, None, payload.for_sales, payload.for_purchase)


@router.put("/products/{product_id}/units/{unit_id}")
def update_unit(product_id: uuid.UUID, unit_id: uuid.UUID, payload: UnitIn, db: Session = Depends(get_db)):
    """Change a unit's name, conversion, or whether it is used for sales and purchases.
    Lines already written keep the conversion they were made with."""
    return parties.save_unit(db, product_id, payload.name, payload.factor, unit_id, payload.for_sales, payload.for_purchase)


@router.delete("/products/{product_id}/units/{unit_id}")
def remove_unit(product_id: uuid.UUID, unit_id: uuid.UUID, db: Session = Depends(get_db)):
    return parties.remove_unit(db, product_id, unit_id)


@router.get("/products/match")
def match_products(q: str = Query(min_length=1), limit: int = Query(default=8, ge=1, le=30), db: Session = Depends(get_db)):
    """Products matching free text, including other names, barcodes and supplier
    codes ("8mm sariya", a scanned code). Says what matched and other units."""
    return {"items": parties.find_products(db, q, limit)}
