"""Customers and suppliers as complete parties.

A party owns contacts (people), contact points (phone numbers and emails, each
belonging to one party only), and addresses (billing, offices, delivery sites).
The party's own phone, email and address columns mirror its primary entries so
screens and integrations that show one value keep working.

This module also finds a party from a phone number or email (WhatsApp, email,
phone calls), checks for duplicates before a party is created, merges two
records of the same party, and manages product aliases and units.
"""
from __future__ import annotations

import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..database import begin_write
from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import (
    Address,
    Contact,
    ContactPoint,
    Customer,
    CustomerDelivery,
    CustomerEnquiry,
    Payment,
    PhoneCall,
    Product,
    ProductAlias,
    ProductUnit,
    PurchaseOrder,
    GoodsReceipt,
    SalesOrder,
    SalesReturn,
    Supplier,
    Task,
    User,
)

KINDS = {"customer": Customer, "supplier": Supplier}
NAME_NOISE = re.compile(
    r"\b(m/s|messrs|pvt|private|ltd|limited|llp|co|company|corp|corporation|and|&|the|traders?|trading|enterprises?|"
    r"industries|agency|agencies|sons|brothers|bros)\b\.?",
    re.I,
)


# ---------------------------------------------------------------------------
# Normalising
# ---------------------------------------------------------------------------


def norm_phone(value: Optional[str]) -> Optional[str]:
    digits = re.sub(r"\D", "", value or "")
    return digits[-10:] if len(digits) >= 6 else None


def norm_email(value: Optional[str]) -> Optional[str]:
    value = (value or "").strip().lower()
    return value if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value) else None


def norm_name(value: Optional[str]) -> str:
    text = NAME_NOISE.sub(" ", (value or "").lower())
    return re.sub(r"[^a-z0-9ऀ-෿]+", " ", text).strip()


def norm_gstin(value: Optional[str]) -> Optional[str]:
    value = re.sub(r"\s", "", (value or "")).upper()
    if not value:
        return None
    if not re.match(r"^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]$", value):
        raise ValidationError("GSTIN must be 15 characters, like 24ABCDE1234F1Z5.")
    return value


def norm_pan(value: Optional[str]) -> Optional[str]:
    value = re.sub(r"\s", "", (value or "")).upper()
    if not value:
        return None
    if not re.match(r"^[A-Z]{5}\d{4}[A-Z]$", value):
        raise ValidationError("PAN must be 10 characters, like ABCDE1234F.")
    return value


def _model(kind: str):
    if kind not in KINDS:
        raise ValidationError("Party must be customer or supplier.")
    return KINDS[kind]


def _party(session: Session, kind: str, party_id: uuid.UUID):
    record = session.get(_model(kind), party_id)
    if record is None:
        raise NotFoundError("{} not found.".format(kind.capitalize()))
    return record


def _owner(kind: str, party_id: uuid.UUID) -> Dict[str, uuid.UUID]:
    return {"customer_id": party_id} if kind == "customer" else {"supplier_id": party_id}


def _owner_col(model, kind: str):
    return model.customer_id if kind == "customer" else model.supplier_id


# ---------------------------------------------------------------------------
# Finding a party
# ---------------------------------------------------------------------------


def owner_of_point(session: Session, kind: str, value: str) -> Optional[ContactPoint]:
    normalized = norm_phone(value) if kind == "phone" else norm_email(value)
    if not normalized:
        return None
    return session.execute(
        select(ContactPoint).where(ContactPoint.kind == kind, ContactPoint.normalized == normalized, ContactPoint.is_active.is_(True))
    ).scalars().first()


def find_by_phone(session: Session, number: Optional[str]) -> Tuple[Optional[str], Optional[Any]]:
    """The customer or supplier a phone number belongs to: ("customer", record)."""
    point = owner_of_point(session, "phone", number or "")
    if point is not None:
        if point.customer_id:
            return "customer", session.get(Customer, point.customer_id)
        return "supplier", session.get(Supplier, point.supplier_id)
    return None, None


def find_by_email(session: Session, email: Optional[str]) -> Tuple[Optional[str], Optional[Any]]:
    point = owner_of_point(session, "email", email or "")
    if point is not None:
        if point.customer_id:
            return "customer", session.get(Customer, point.customer_id)
        return "supplier", session.get(Supplier, point.supplier_id)
    return None, None


def search_condition(kind: str, search: str):
    """Extra match for party listings: any of the party's numbers or emails."""
    model = _model(kind)
    col = ContactPoint.customer_id if kind == "customer" else ContactPoint.supplier_id
    phone = norm_phone(search)
    pattern = "%{}%".format(search.strip().lower())
    conditions = [ContactPoint.normalized.like(pattern)]
    if phone:
        conditions.append(ContactPoint.normalized.like("%{}%".format(phone)))
    sub = select(col).where(ContactPoint.is_active.is_(True), or_(*conditions))
    contacts = select(Contact.customer_id if kind == "customer" else Contact.supplier_id).where(func.lower(Contact.name).like(pattern))
    return or_(model.id.in_(sub), model.id.in_(contacts))


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------


def duplicates(session: Session, kind: str, name: Optional[str] = None, phones: Iterable[str] = (), emails: Iterable[str] = (),
               gstin: Optional[str] = None, exclude_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    """Possible existing records for a new or edited party. ``blocking`` hits
    share a phone number, email or GSTIN (the same party for certain);
    ``similar`` hits only have a similar name."""
    model = _model(kind)
    blocking: List[Dict[str, Any]] = []
    for point_kind, values in (("phone", phones), ("email", emails)):
        for value in values or []:
            point = owner_of_point(session, point_kind, value)
            if point is None:
                continue
            owner_kind = "customer" if point.customer_id else "supplier"
            owner_id = point.customer_id or point.supplier_id
            if owner_kind == kind and owner_id == exclude_id:
                continue
            owner = session.get(KINDS[owner_kind], owner_id)
            blocking.append({"kind": owner_kind, "id": owner_id, "name": owner.name if owner else None,
                             "reason": "{} {} already belongs to {}".format(point_kind, value, owner.name if owner else "another record")})
    if gstin:
        try:
            normalized = norm_gstin(gstin)
        except ValidationError:
            normalized = None
        if normalized:
            for row in session.execute(select(model).where(model.gstin == normalized)).scalars():
                if row.id != exclude_id:
                    blocking.append({"kind": kind, "id": row.id, "name": row.name, "reason": "GSTIN {} already belongs to {}".format(normalized, row.name)})
    similar: List[Dict[str, Any]] = []
    words = {w for w in norm_name(name).split() if len(w) >= 3}
    if words:
        candidates = session.execute(select(model).where(or_(*[func.lower(model.name).like("%{}%".format(w)) for w in words]))).scalars()
        scored = []
        for row in candidates:
            if row.id == exclude_id or any(b["id"] == row.id for b in blocking):
                continue
            other = {w for w in norm_name(row.name).split() if len(w) >= 3}
            if not other:
                continue
            shared = words & other
            # Same name, or most of the shorter name's words appear in the other.
            score = len(shared) / min(len(words), len(other))
            if shared and score >= 0.66 and (len(shared) >= 2 or len(words) == len(other) == 1):
                scored.append((score, row))
        for score, row in sorted(scored, key=lambda item: -item[0]):
            similar.append({"kind": kind, "id": row.id, "name": row.name, "active": row.is_active, "reason": "similar name"})
    return {"blocking": blocking, "similar": similar[:5]}


def require_unique(session: Session, kind: str, phones: Iterable[str] = (), emails: Iterable[str] = (),
                   gstin: Optional[str] = None, exclude_id: Optional[uuid.UUID] = None) -> None:
    found = duplicates(session, kind, None, phones, emails, gstin, exclude_id)["blocking"]
    if found:
        hit = found[0]
        raise ConflictError("{}. Open {} instead, or merge the two.".format(hit["reason"][0].upper() + hit["reason"][1:], hit["name"]),
                            {"duplicate": {"kind": hit["kind"], "id": str(hit["id"]), "name": hit["name"]}})


# ---------------------------------------------------------------------------
# Profile: contacts, contact points, addresses
# ---------------------------------------------------------------------------


def _contact_view(row: Contact) -> Dict[str, Any]:
    return {"id": row.id, "name": row.name, "role": row.role, "is_primary": row.is_primary, "is_active": row.is_active, "notes": row.notes}


def _point_view(row: ContactPoint) -> Dict[str, Any]:
    return {"id": row.id, "kind": row.kind, "value": row.value, "label": row.label, "contact_id": row.contact_id,
            "is_whatsapp": row.is_whatsapp, "is_primary": row.is_primary, "is_active": row.is_active}


def _address_view(row: Address) -> Dict[str, Any]:
    return {"id": row.id, "kind": row.kind, "label": row.label, "line": row.line, "city": row.city, "state": row.state,
            "pincode": row.pincode, "map_url": row.map_url, "contact_id": row.contact_id, "is_default": row.is_default, "is_active": row.is_active}


def profile(session: Session, kind: str, party_id: uuid.UUID, include_inactive: bool = False) -> Dict[str, Any]:
    party = _party(session, kind, party_id)

    def rows(model):
        stmt = select(model).where(_owner_col(model, kind) == party_id)
        if not include_inactive:
            stmt = stmt.where(model.is_active.is_(True))
        return session.execute(stmt.order_by(model.created_at)).scalars().all()

    return {
        "kind": kind, "id": party.id, "name": party.name, "gstin": party.gstin, "pan": party.pan, "tally_ledger_name": party.tally_ledger_name,
        "contacts": [_contact_view(c) for c in rows(Contact)],
        "points": [_point_view(p) for p in rows(ContactPoint)],
        "addresses": [_address_view(a) for a in rows(Address)],
    }


def _mirror(session: Session, kind: str, party) -> None:
    """Keep the party's single phone/email/address columns equal to its primary entries."""
    col = _owner_col(ContactPoint, kind)
    for point_kind, attr in (("phone", "phone"), ("email", "email")):
        point = session.execute(
            select(ContactPoint).where(col == party.id, ContactPoint.kind == point_kind, ContactPoint.is_active.is_(True))
            .order_by(ContactPoint.is_primary.desc(), ContactPoint.created_at)
        ).scalars().first()
        setattr(party, attr, point.value[:32 if attr == "phone" else 255] if point else None)
    address = session.execute(
        select(Address).where(_owner_col(Address, kind) == party.id, Address.is_active.is_(True))
        .order_by((Address.kind == "billing").desc(), Address.is_default.desc(), Address.created_at)
    ).scalars().first()
    party.address = ", ".join(x for x in (address.line, address.city, address.state, address.pincode) if x) if address else None
    if kind == "supplier":
        contact = session.execute(
            select(Contact).where(Contact.supplier_id == party.id, Contact.is_active.is_(True)).order_by(Contact.is_primary.desc(), Contact.created_at)
        ).scalars().first()
        party.contact_person = contact.name if contact else None


def _one_primary(session: Session, model, kind: str, party_id: uuid.UUID, keep_id: uuid.UUID, extra=None) -> None:
    stmt = update(model).where(_owner_col(model, kind) == party_id, model.id != keep_id)
    if extra is not None:
        stmt = stmt.where(extra)
    session.execute(stmt.values(is_primary=False) if model is not Address else stmt.values(is_default=False))


def _commit(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


def save_contact(session: Session, kind: str, party_id: uuid.UUID, data: Dict[str, Any], contact_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    begin_write(session)
    party = _party(session, kind, party_id)
    row = session.get(Contact, contact_id) if contact_id else Contact(**_owner(kind, party_id))
    if row is None or (contact_id and getattr(row, kind + "_id") != party_id):
        raise NotFoundError("Contact not found.")
    for field in ("name", "role", "notes"):
        if field in data:
            setattr(row, field, (data[field] or "").strip() or None)
    if not row.name:
        raise ValidationError("A contact needs a name.")
    for flag in ("is_primary", "is_active"):
        if data.get(flag) is not None:
            setattr(row, flag, bool(data[flag]))
    session.add(row)
    session.flush()
    if row.is_primary:
        _one_primary(session, Contact, kind, party_id, row.id)
    _mirror(session, kind, party)
    _commit(session)
    return _contact_view(row)


def save_point(session: Session, kind: str, party_id: uuid.UUID, data: Dict[str, Any], point_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    begin_write(session)
    party = _party(session, kind, party_id)
    row = session.get(ContactPoint, point_id) if point_id else ContactPoint(**_owner(kind, party_id), kind=data.get("kind") or "phone")
    if row is None or (point_id and getattr(row, kind + "_id") != party_id):
        raise NotFoundError("That phone number or email was not found.")
    if row.kind not in ("phone", "email"):
        raise ValidationError("Kind must be phone or email.")
    if "value" in data:
        value = (data["value"] or "").strip()
        normalized = norm_phone(value) if row.kind == "phone" else norm_email(value)
        if not normalized:
            raise ValidationError("Enter a valid {}.".format("phone number" if row.kind == "phone" else "email address"))
        clash = owner_of_point(session, row.kind, value)
        if clash is not None and clash.id != row.id:
            owner = session.get(Customer, clash.customer_id) if clash.customer_id else session.get(Supplier, clash.supplier_id)
            raise ConflictError("{} already belongs to {}.".format(value, owner.name if owner else "another record"),
                                {"duplicate": {"kind": "customer" if clash.customer_id else "supplier", "id": str(clash.customer_id or clash.supplier_id), "name": owner.name if owner else None}})
        row.value, row.normalized = value, normalized
    if not row.value:
        raise ValidationError("Enter the number or email.")
    for field in ("label",):
        if field in data:
            row.label = (data[field] or "").strip() or None
    if "contact_id" in data:
        row.contact_id = uuid.UUID(str(data["contact_id"])) if data["contact_id"] else None
    for flag in ("is_whatsapp", "is_primary", "is_active"):
        if data.get(flag) is not None:
            setattr(row, flag, bool(data[flag]))
    session.add(row)
    session.flush()
    if row.is_primary:
        _one_primary(session, ContactPoint, kind, party_id, row.id, ContactPoint.kind == row.kind)
    _mirror(session, kind, party)
    _commit(session)
    return _point_view(row)


def save_address(session: Session, kind: str, party_id: uuid.UUID, data: Dict[str, Any], address_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    begin_write(session)
    party = _party(session, kind, party_id)
    row = session.get(Address, address_id) if address_id else Address(**_owner(kind, party_id))
    if row is None or (address_id and getattr(row, kind + "_id") != party_id):
        raise NotFoundError("Address not found.")
    for field in ("label", "line", "city", "state", "pincode", "map_url"):
        if field in data:
            setattr(row, field, (data[field] or "").strip() or None)
    if "kind" in data and data["kind"]:
        if data["kind"] not in ("billing", "site", "office", "warehouse"):
            raise ValidationError("Address kind must be billing, site, office or warehouse.")
        row.kind = data["kind"]
    if not row.line:
        raise ValidationError("Enter the address.")
    if "contact_id" in data:
        row.contact_id = uuid.UUID(str(data["contact_id"])) if data["contact_id"] else None
    for flag in ("is_default", "is_active"):
        if data.get(flag) is not None:
            setattr(row, flag, bool(data[flag]))
    session.add(row)
    session.flush()
    if row.is_default:
        _one_primary(session, Address, kind, party_id, row.id, Address.kind == row.kind)
    _mirror(session, kind, party)
    _commit(session)
    return _address_view(row)


def set_identity(session: Session, kind: str, party_id: uuid.UUID, gstin: Any = ..., pan: Any = ...) -> None:
    """Set GSTIN/PAN (called inside the party's own create/update)."""
    party = _party(session, kind, party_id)
    if gstin is not ...:
        value = norm_gstin(gstin)
        if value:
            model = _model(kind)
            clash = session.execute(select(model).where(model.gstin == value, model.id != party_id)).scalars().first()
            if clash is not None:
                raise ConflictError("GSTIN {} already belongs to {}.".format(value, clash.name),
                                    {"duplicate": {"kind": kind, "id": str(clash.id), "name": clash.name}})
        party.gstin = value
    if pan is not ...:
        party.pan = norm_pan(pan)


def sync_from_columns(session: Session, kind: str, party, phone: Optional[str] = None, email: Optional[str] = None, address: Optional[str] = None,
                      contact_person: Optional[str] = None) -> None:
    """When a party is created or edited through its single fields, record them
    as its primary contact points / address (no commit)."""
    owner = _owner(kind, party.id)
    col = lambda model: _owner_col(model, kind)  # noqa: E731
    for point_kind, value in (("phone", phone), ("email", email)):
        if value is None:
            continue
        normalized = norm_phone(value) if point_kind == "phone" else norm_email(value)
        current = session.execute(
            select(ContactPoint).where(col(ContactPoint) == party.id, ContactPoint.kind == point_kind, ContactPoint.is_active.is_(True))
            .order_by(ContactPoint.is_primary.desc(), ContactPoint.created_at)
        ).scalars().first()
        if not normalized:
            if current is not None and value == "":
                current.is_active = False
            continue
        if current is not None and current.normalized == normalized:
            current.value = value
            continue
        existing = session.execute(
            select(ContactPoint).where(col(ContactPoint) == party.id, ContactPoint.kind == point_kind, ContactPoint.normalized == normalized)
        ).scalars().first()
        if existing is not None:
            existing.is_active, existing.is_primary, existing.value = True, True, value
            target = existing
        else:
            target = ContactPoint(**owner, kind=point_kind, value=value, normalized=normalized, is_primary=True,
                                  is_whatsapp=point_kind == "phone", label="mobile" if point_kind == "phone" else "work")
            session.add(target)
        session.flush()
        _one_primary(session, ContactPoint, kind, party.id, target.id, ContactPoint.kind == point_kind)
    if address is not None:
        current = session.execute(
            select(Address).where(col(Address) == party.id, Address.kind == "billing", Address.is_active.is_(True))
        ).scalars().first()
        if address.strip():
            if current is None:
                session.add(Address(**owner, kind="billing", label="Billing", line=address.strip(), is_default=True))
            else:
                current.line, current.city, current.state, current.pincode = address.strip(), None, None, None
        elif current is not None:
            current.is_active = False
    if kind == "supplier" and contact_person is not None:
        current = session.execute(
            select(Contact).where(Contact.supplier_id == party.id, Contact.is_active.is_(True)).order_by(Contact.is_primary.desc(), Contact.created_at)
        ).scalars().first()
        if contact_person.strip():
            if current is None:
                session.add(Contact(supplier_id=party.id, name=contact_person.strip(), role="Contact", is_primary=True))
            else:
                current.name = contact_person.strip()
        elif current is not None:
            current.is_active = False
    session.flush()


# ---------------------------------------------------------------------------
# Merging two records of the same party
# ---------------------------------------------------------------------------


def merge(session: Session, kind: str, keep_id: uuid.UUID, drop_id: uuid.UUID, user: Optional[User] = None) -> Dict[str, Any]:
    """Move everything from ``drop_id`` to ``keep_id`` and archive ``drop_id``."""
    if keep_id == drop_id:
        raise ValidationError("Choose two different records.")
    begin_write(session)
    try:
        keep, drop = _party(session, kind, keep_id), _party(session, kind, drop_id)
        moved: Dict[str, int] = {}
        if kind == "customer":
            targets = [(CustomerEnquiry, CustomerEnquiry.customer_id), (SalesOrder, SalesOrder.customer_id),
                       (CustomerDelivery, CustomerDelivery.customer_id), (Payment, Payment.customer_id),
                       (SalesReturn, SalesReturn.customer_id), (Task, Task.customer_id), (PhoneCall, PhoneCall.customer_id),
                       (Contact, Contact.customer_id), (Address, Address.customer_id), (ContactPoint, ContactPoint.customer_id)]
        else:
            targets = [(PurchaseOrder, PurchaseOrder.supplier_id), (GoodsReceipt, GoodsReceipt.supplier_id), (Payment, Payment.supplier_id),
                       (Task, Task.supplier_id), (Product, Product.preferred_supplier_id), (ProductAlias, ProductAlias.supplier_id),
                       (Contact, Contact.supplier_id), (Address, Address.supplier_id), (ContactPoint, ContactPoint.supplier_id)]
        for model, column in targets:
            result = session.execute(update(model).where(column == drop_id).values({column.key: keep_id}))
            if result.rowcount:
                moved[model.__tablename__] = result.rowcount
        # The kept record keeps its own primary entries; the merged ones become secondary.
        for model, flag in ((ContactPoint, "is_primary"), (Contact, "is_primary"), (Address, "is_default")):
            ids = [r for r in session.execute(select(model.id).where(_owner_col(model, kind) == keep_id, getattr(model, flag).is_(True))).scalars()]
            if len(ids) > 1:
                for extra in ids[1:]:
                    session.execute(update(model).where(model.id == extra).values({flag: False}))
        if kind == "customer":
            for field in ("credit_limit", "price_list_id", "gstin", "pan", "tally_ledger_name"):
                if getattr(keep, field) is None and getattr(drop, field) is not None:
                    value = getattr(drop, field)
                    if field == "gstin":
                        drop.gstin = None
                        session.flush()
                    setattr(keep, field, value)
        else:
            for field in ("gstin", "pan", "tally_ledger_name", "lead_time_days"):
                if getattr(keep, field, None) is None and getattr(drop, field, None) is not None:
                    value = getattr(drop, field)
                    if field == "gstin":
                        drop.gstin = None
                        session.flush()
                    setattr(keep, field, value)
        if drop.notes:
            keep.notes = ((keep.notes or "") + "\nMerged from {}: {}".format(drop.name, drop.notes)).strip()
        drop.is_active = False
        drop.notes = ((drop.notes or "") + "\nMerged into {} ({}).".format(keep.name, keep.id)).strip()
        session.flush()
        _mirror(session, kind, keep)
        _mirror(session, kind, drop)
        from .controls import log

        log(session, user, "merge_" + kind, kind, str(keep_id),
            "Merged {} '{}' into '{}': {}".format(kind, drop.name, keep.name, ", ".join("{} {}".format(v, k.replace("_", " ")) for k, v in moved.items()) or "no records"),
            {"kept": str(keep_id), "merged": str(drop_id), "moved": moved})
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {"kept": keep_id, "merged": drop_id, "moved": moved}


# ---------------------------------------------------------------------------
# Products: aliases, barcodes, supplier codes, units
# ---------------------------------------------------------------------------


def norm_alias(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def product_names(session: Session, product_id: uuid.UUID) -> Dict[str, Any]:
    product = session.get(Product, product_id)
    if product is None:
        raise NotFoundError("Product not found.")
    aliases = session.execute(select(ProductAlias).where(ProductAlias.product_id == product_id).order_by(ProductAlias.kind, ProductAlias.value)).scalars().all()
    units = session.execute(select(ProductUnit).where(ProductUnit.product_id == product_id).order_by(ProductUnit.factor)).scalars().all()
    names = {s.id: s.name for s in session.execute(select(Supplier).where(Supplier.id.in_([a.supplier_id for a in aliases if a.supplier_id]))).scalars()} if aliases else {}
    return {
        "product_id": product_id, "base_unit": product.unit_of_measure,
        "aliases": [{"id": a.id, "kind": a.kind, "value": a.value, "supplier_id": a.supplier_id, "supplier_name": names.get(a.supplier_id)} for a in aliases],
        "units": [{"id": u.id, "name": u.name, "factor": float(u.factor), "for_sales": u.for_sales, "for_purchase": u.for_purchase} for u in units],
        "sales_unit": product.sales_unit, "purchase_unit": product.purchase_unit, "whole_units": product.whole_units,
    }


def add_alias(session: Session, product_id: uuid.UUID, kind: str, value: str, supplier_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    begin_write(session)
    if session.get(Product, product_id) is None:
        raise NotFoundError("Product not found.")
    if kind not in ("alias", "barcode", "supplier_code"):
        raise ValidationError("Kind must be alias, barcode or supplier_code.")
    normalized = norm_alias(value)
    if not normalized:
        raise ValidationError("Enter the name or code.")
    if kind == "supplier_code" and not supplier_id:
        raise ValidationError("A supplier code needs the supplier.")
    clash = session.execute(select(ProductAlias).where(ProductAlias.kind == kind, ProductAlias.normalized == normalized,
                                                       ProductAlias.supplier_id.is_(None) if supplier_id is None else ProductAlias.supplier_id == supplier_id)).scalars().first()
    if clash is not None:
        other = session.get(Product, clash.product_id)
        raise ConflictError("'{}' is already used for {}.".format(value.strip(), other.name if other else "another product"))
    row = ProductAlias(product_id=product_id, kind=kind, value=value.strip(), normalized=normalized, supplier_id=supplier_id)
    session.add(row)
    _commit(session)
    return product_names(session, product_id)


def remove_alias(session: Session, product_id: uuid.UUID, alias_id: uuid.UUID) -> Dict[str, Any]:
    begin_write(session)
    row = session.get(ProductAlias, alias_id)
    if row is None or row.product_id != product_id:
        raise NotFoundError("Alias not found.")
    session.delete(row)
    _commit(session)
    return product_names(session, product_id)


def save_unit(session: Session, product_id: uuid.UUID, name: str, factor: Any, unit_id: Optional[uuid.UUID] = None,
              for_sales: bool = True, for_purchase: bool = True) -> Dict[str, Any]:
    begin_write(session)
    product = session.get(Product, product_id)
    if product is None:
        raise NotFoundError("Product not found.")
    name = (name or "").strip()
    if not name:
        raise ValidationError("Enter the unit name, e.g. tonne.")
    if name.lower() == (product.unit_of_measure or "").lower():
        raise ValidationError("That is already the product's base unit.")
    try:
        value = Decimal(str(factor))
    except (InvalidOperation, TypeError):
        raise ValidationError("Enter how many {} one {} holds.".format(product.unit_of_measure, name))
    if value <= 0:
        raise ValidationError("The conversion must be more than zero.")
    row = session.get(ProductUnit, unit_id) if unit_id else ProductUnit(product_id=product_id)
    if row is None or row.product_id != product_id:
        raise NotFoundError("Unit not found.")
    old_name = row.name
    row.name, row.factor, row.for_sales, row.for_purchase = name, value, bool(for_sales), bool(for_purchase)
    for key in ("sales_unit", "purchase_unit"):
        if old_name and getattr(product, key) == old_name:
            setattr(product, key, name)
    if not row.for_sales and product.sales_unit == name:
        product.sales_unit = None
    if not row.for_purchase and product.purchase_unit == name:
        product.purchase_unit = None
    session.add(row)
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise ConflictError("The product already has a unit called {}.".format(name))
    return product_names(session, product_id)


def remove_unit(session: Session, product_id: uuid.UUID, unit_id: uuid.UUID) -> Dict[str, Any]:
    begin_write(session)
    row = session.get(ProductUnit, unit_id)
    if row is None or row.product_id != product_id:
        raise NotFoundError("Unit not found.")
    product = session.get(Product, product_id)
    for key in ("sales_unit", "purchase_unit"):
        if getattr(product, key) == row.name:
            setattr(product, key, None)
    session.delete(row)
    _commit(session)
    return product_names(session, product_id)


def find_products(session: Session, text: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Products matching free text: exact barcode/code/alias first, then names
    containing every word, then any alias containing the text."""
    query = norm_alias(text)
    if not query:
        return []
    hits: List[Tuple[int, Product, str]] = []
    seen = set()

    def add(rank: int, product: Optional[Product], why: str) -> None:
        if product is not None and product.is_active and product.id not in seen:
            seen.add(product.id)
            hits.append((rank, product, why))

    for alias in session.execute(select(ProductAlias).where(ProductAlias.normalized == query)).scalars():
        add(0, session.get(Product, alias.product_id), "{} '{}'".format(alias.kind.replace("_", " "), alias.value))
    for product in session.execute(select(Product).where(func.lower(Product.sku) == query)).scalars():
        add(0, product, "code")
    stmt = select(Product).where(Product.is_active.is_(True))
    for word in query.split()[:5]:
        stmt = stmt.where(or_(func.lower(Product.name).like("%{}%".format(word)), func.lower(Product.sku).like("%{}%".format(word)),
                              func.lower(func.coalesce(Product.category, "")).like("%{}%".format(word))))
    for product in session.execute(stmt.limit(limit)).scalars():
        add(1, product, "name")
    for alias in session.execute(select(ProductAlias).where(ProductAlias.normalized.like("%{}%".format(query))).limit(limit)).scalars():
        add(2, session.get(Product, alias.product_id), "{} '{}'".format(alias.kind.replace("_", " "), alias.value))
    hits.sort(key=lambda h: h[0])
    units = {}
    if hits:
        for unit in session.execute(select(ProductUnit).where(ProductUnit.product_id.in_([h[1].id for h in hits]))).scalars():
            units.setdefault(unit.product_id, []).append({"name": unit.name, "factor": float(unit.factor), "for_sales": unit.for_sales})
    return [{"product_id": p.id, "name": p.name, "sku": p.sku, "unit": p.unit_of_measure, "matched_by": why, "other_units": units.get(p.id, [])}
            for _, p, why in hits[:limit]]
