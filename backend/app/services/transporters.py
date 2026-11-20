"""Transporters: who carries the goods, in what, at what rate.

A transporter is a full party like a customer or supplier (contacts, numbers,
addresses, GSTIN, Tally ledger, payment terms), plus:

* **vehicles** -- registration number, type, capacity, driver;
* a **rate card** -- per route and vehicle type, charged per trip, km, tonne,
  quintal, kg, unit or hour, with a minimum charge and validity;
* **trips and charges** -- every delivery, goods receipt, transfer and
  booking they carried, and the freight for it;
* a **statement** -- freight owed (their bills) less payments made.

Bookings ask a transporter for a vehicle -- by a person, or by TAI (WhatsApp)
or PAI (a call) at whichever workflow step needs transport.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import begin_write
from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import (
    VEHICLE_TYPES,
    CustomerDelivery,
    GoodsReceipt,
    LandedCost,
    LandedCostCharge,
    Payment,
    StockTransfer,
    StockTransferCost,
    TransportBooking,
    Transporter,
    TransporterRate,
    TransporterVehicle,
    User,
)
from ..numeric import ZERO_MONEY, money
from .common import next_document_number

KINDS = {"company": "Transport company", "fleet_owner": "Fleet / lorry owner", "broker": "Broker", "tempo": "Tempo / small vehicle",
         "courier": "Courier", "own_fleet": "Our own vehicles"}
VEHICLES = {"tempo": "Tempo", "pickup": "Pickup", "lcv": "LCV (407)", "6_wheeler": "6-wheeler", "10_wheeler": "10-wheeler",
            "12_wheeler": "12-wheeler", "14_wheeler": "14-wheeler", "trailer": "Trailer", "tractor": "Tractor", "container": "Container", "other": "Other"}
BASES = {"trip": "per trip", "km": "per km", "tonne": "per tonne", "quintal": "per quintal", "kg": "per kg", "unit": "per unit of goods", "hour": "per hour"}
BOOKING_STATUS = ("draft", "requested", "confirmed", "declined", "done", "cancelled")
COUNTER = "transporter"
BOOKING_COUNTER = "transport_booking"


def get(session: Session, transporter_id: uuid.UUID) -> Transporter:
    row = session.get(Transporter, transporter_id)
    if row is None:
        raise NotFoundError("Transporter not found.")
    return row


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


def view(session: Session, t: Transporter, detail: bool = False) -> Dict[str, Any]:
    out = {
        "id": t.id, "code": t.code, "name": t.name, "kind": t.kind, "kind_label": KINDS.get(t.kind, t.kind),
        "contact_person": t.contact_person, "phone": t.phone, "email": t.email, "address": t.address,
        "gstin": t.gstin, "pan": t.pan, "tally_ledger_name": t.tally_ledger_name, "service_areas": t.service_areas,
        "payment_terms_days": t.payment_terms_days, "booking_channel": t.booking_channel, "rating": t.rating,
        "notes": t.notes, "is_active": t.is_active, "created_at": t.created_at,
        "vehicle_count": len([v for v in t.vehicles if v.is_active]), "rate_count": len([r for r in t.rates if r.is_active]),
        "vehicle_types": sorted({v.vehicle_type for v in t.vehicles if v.is_active} | {r.vehicle_type for r in t.rates if r.is_active and r.vehicle_type}),
    }
    if detail:
        out["vehicles"] = [vehicle_view(v) for v in t.vehicles]
        out["rates"] = [rate_view(r) for r in t.rates]
    return out


def vehicle_view(v: TransporterVehicle) -> Dict[str, Any]:
    return {"id": v.id, "number": v.number, "vehicle_type": v.vehicle_type, "vehicle_label": VEHICLES.get(v.vehicle_type, v.vehicle_type),
            "capacity_kg": float(v.capacity_kg) if v.capacity_kg is not None else None, "driver_name": v.driver_name,
            "driver_phone": v.driver_phone, "is_active": v.is_active, "notes": v.notes}


def rate_view(r: TransporterRate) -> Dict[str, Any]:
    return {"id": r.id, "from_place": r.from_place, "to_place": r.to_place, "vehicle_type": r.vehicle_type,
            "vehicle_label": VEHICLES.get(r.vehicle_type, "Any vehicle") if r.vehicle_type else "Any vehicle",
            "basis": r.basis, "basis_label": BASES.get(r.basis, r.basis), "rate": float(r.rate),
            "min_charge": float(r.min_charge) if r.min_charge is not None else None, "loading_included": r.loading_included,
            "valid_from": r.valid_from, "valid_until": r.valid_until, "notes": r.notes, "is_active": r.is_active}


def list_transporters(session: Session, search: Optional[str] = None, include_inactive: bool = False, kind: Optional[str] = None) -> List[Dict[str, Any]]:
    from . import parties

    stmt = select(Transporter).order_by(Transporter.name)
    if not include_inactive:
        stmt = stmt.where(Transporter.is_active.is_(True))
    if kind:
        stmt = stmt.where(Transporter.kind == kind)
    if search and search.strip():
        pattern = "%{}%".format(search.strip().lower())
        stmt = stmt.where(or_(func.lower(Transporter.name).like(pattern), func.lower(Transporter.code).like(pattern),
                              func.lower(func.coalesce(Transporter.service_areas, "")).like(pattern),
                              Transporter.id.in_(select(TransporterVehicle.transporter_id).where(func.lower(TransporterVehicle.number).like(pattern))),
                              parties.search_condition("transporter", search)))
    rows = session.execute(stmt).scalars().all()
    owed = balances(session)
    trips = _trip_counts(session)
    out = []
    for t in rows:
        v = view(session, t)
        v["balance"] = owed.get(t.id, 0.0)
        v["trips"] = trips.get(t.id, 0)
        out.append(v)
    return out


def _clean_kind(value: Any) -> str:
    if value not in KINDS:
        raise ValidationError("Kind must be one of: {}.".format(", ".join(KINDS)))
    return value


def save(session: Session, data: Dict[str, Any], transporter_id: Optional[uuid.UUID] = None) -> Transporter:
    from . import parties

    try:
        begin_write(session)
        t = get(session, transporter_id) if transporter_id else Transporter()
        if "name" in data or transporter_id is None:
            name = (data.get("name") or "").strip()
            if not name:
                raise ValidationError("Transporter name is required.")
            t.name = name[:255]
        if "code" in data and data["code"]:
            code = re.sub(r"\s+", "-", data["code"].strip().upper())[:32]
            clash = session.execute(select(Transporter.id).where(Transporter.code == code, Transporter.id != t.id)).first() if t.id else \
                session.execute(select(Transporter.id).where(Transporter.code == code)).first()
            if clash is not None:
                raise ConflictError("A transporter with code '{}' already exists.".format(code))
            t.code = code
        elif transporter_id is None:
            t.code = next_document_number(session, COUNTER, "TRN")
        if data.get("kind") is not None:
            t.kind = _clean_kind(data["kind"])
        elif transporter_id is None:
            t.kind = "company"
        parties.require_unique(session, "transporter", [data["phone"]] if data.get("phone") else [],
                               [data["email"]] if data.get("email") else [], data.get("gstin"), exclude_id=t.id)
        for key in ("contact_person", "phone", "email", "address", "notes", "service_areas", "tally_ledger_name"):
            if key in data:
                setattr(t, key, (data[key] or "").strip() or None)
        if data.get("payment_terms_days") is not None:
            t.payment_terms_days = max(0, int(data["payment_terms_days"]))
        elif transporter_id is None:
            t.payment_terms_days = 0
        if data.get("booking_channel") is not None:
            if data["booking_channel"] not in ("whatsapp", "call", "either"):
                raise ValidationError("Book by whatsapp, call or either.")
            t.booking_channel = data["booking_channel"]
        elif transporter_id is None:
            t.booking_channel = "whatsapp"
        if "rating" in data:
            rating = data["rating"]
            if rating is not None and not 1 <= int(rating) <= 5:
                raise ValidationError("Rating is 1 to 5.")
            t.rating = int(rating) if rating is not None else None
        if data.get("is_active") is not None:
            t.is_active = bool(data["is_active"])
        elif transporter_id is None:
            t.is_active = True
        session.add(t)
        session.flush()
        if "gstin" in data or "pan" in data:
            parties.set_identity(session, "transporter", t.id, data.get("gstin", t.gstin), data.get("pan", t.pan))
        parties.sync_from_columns(session, "transporter", t,
                                  *[(data[f] or "") if f in data else None for f in ("phone", "email", "address", "contact_person")])
        for vehicle in data.get("vehicles") or []:
            _save_vehicle(t, vehicle)
        for rate in data.get("rates") or []:
            _save_rate(t, rate)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("That transporter could not be saved (duplicate code?).") from exc
    except Exception:
        session.rollback()
        raise
    return t


def _norm_vehicle(number: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (number or "").upper())


def _save_vehicle(t: Transporter, data: Dict[str, Any], vehicle_id: Optional[uuid.UUID] = None) -> TransporterVehicle:
    row = next((v for v in t.vehicles if v.id == vehicle_id), None) if vehicle_id else TransporterVehicle()
    if row is None:
        raise NotFoundError("Vehicle not found.")
    if "number" in data or vehicle_id is None:
        number = _norm_vehicle(data.get("number") or "")
        if len(number) < 4:
            raise ValidationError("Enter the vehicle number, e.g. GJ01AB1234.")
        if any(_norm_vehicle(v.number) == number and v is not row for v in t.vehicles):
            raise ConflictError("{} is already on this transporter.".format(number))
        row.number = number
    if data.get("vehicle_type") is not None or vehicle_id is None:
        kind = data.get("vehicle_type") or "other"
        if kind not in VEHICLE_TYPES:
            raise ValidationError("Unknown vehicle type '{}'.".format(kind))
        row.vehicle_type = kind
    if "capacity_kg" in data:
        row.capacity_kg = Decimal(str(data["capacity_kg"])) if data["capacity_kg"] not in (None, "") else None
    for key in ("driver_name", "driver_phone", "notes"):
        if key in data:
            setattr(row, key, (data[key] or "").strip() or None)
    if data.get("is_active") is not None:
        row.is_active = bool(data["is_active"])
    if vehicle_id is None:
        row.is_active = True if data.get("is_active") is None else bool(data["is_active"])
        t.vehicles.append(row)
    return row


def _when(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError("Dates are YYYY-MM-DD.")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _save_rate(t: Transporter, data: Dict[str, Any], rate_id: Optional[uuid.UUID] = None) -> TransporterRate:
    row = next((r for r in t.rates if r.id == rate_id), None) if rate_id else TransporterRate()
    if row is None:
        raise NotFoundError("Rate not found.")
    for key in ("from_place", "to_place", "notes"):
        if key in data:
            setattr(row, key, (data[key] or "").strip() or None)
    if "vehicle_type" in data:
        if data["vehicle_type"] and data["vehicle_type"] not in VEHICLE_TYPES:
            raise ValidationError("Unknown vehicle type '{}'.".format(data["vehicle_type"]))
        row.vehicle_type = data["vehicle_type"] or None
    if data.get("basis") is not None or rate_id is None:
        basis = data.get("basis") or "trip"
        if basis not in BASES:
            raise ValidationError("Charge per trip, km, tonne, quintal, kg, unit or hour.")
        row.basis = basis
    if "rate" in data or rate_id is None:
        rate = money(data.get("rate") or 0, "Rate")
        if rate < 0:
            raise ValidationError("A rate cannot be negative.")
        row.rate = rate
    if "min_charge" in data:
        row.min_charge = money(data["min_charge"], "Minimum charge") if data["min_charge"] not in (None, "") else None
    if data.get("loading_included") is not None:
        row.loading_included = bool(data["loading_included"])
    elif rate_id is None:
        row.loading_included = False
    for key in ("valid_from", "valid_until"):
        if key in data:
            setattr(row, key, _when(data[key]))
    if row.valid_from and row.valid_until and row.valid_until < row.valid_from:
        raise ValidationError("The rate ends before it starts.")
    if data.get("is_active") is not None:
        row.is_active = bool(data["is_active"])
    elif rate_id is None:
        row.is_active = True
    if rate_id is None:
        t.rates.append(row)
    return row


def save_vehicle(session: Session, transporter_id: uuid.UUID, data: Dict[str, Any], vehicle_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    begin_write(session)
    try:
        t = get(session, transporter_id)
        _save_vehicle(t, data, vehicle_id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return detail(session, transporter_id)


def save_rate(session: Session, transporter_id: uuid.UUID, data: Dict[str, Any], rate_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    begin_write(session)
    try:
        t = get(session, transporter_id)
        _save_rate(t, data, rate_id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return detail(session, transporter_id)


def remove_child(session: Session, transporter_id: uuid.UUID, what: str, child_id: uuid.UUID) -> Dict[str, Any]:
    begin_write(session)
    model = TransporterVehicle if what == "vehicle" else TransporterRate
    row = session.get(model, child_id)
    if row is None or row.transporter_id != transporter_id:
        raise NotFoundError("Not found.")
    session.delete(row)
    session.commit()
    return detail(session, transporter_id)


# ---------------------------------------------------------------------------
# Estimating freight from the rate card
# ---------------------------------------------------------------------------


def _place_match(rule: Optional[str], place: Optional[str]) -> int:
    """2 for a named match, 1 for 'anywhere', 0 for no match."""
    if not rule:
        return 1
    if not place:
        return 0
    a, b = rule.strip().lower(), place.strip().lower()
    return 2 if a in b or b in a else 0


def estimate(session: Session, from_place: Optional[str] = None, to_place: Optional[str] = None, vehicle_type: Optional[str] = None,
             weight_kg: Any = None, units: Any = None, km: Any = None, hours: Any = None, transporter_id: Optional[uuid.UUID] = None,
             on: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Every rate that fits a trip, cheapest first, with the freight it gives."""
    when = on or datetime.now(timezone.utc)
    weight = Decimal(str(weight_kg)) if weight_kg not in (None, "") else None
    count = Decimal(str(units)) if units not in (None, "") else None
    distance = Decimal(str(km)) if km not in (None, "") else None
    duration = Decimal(str(hours)) if hours not in (None, "") else None
    stmt = select(TransporterRate, Transporter).join(Transporter, TransporterRate.transporter_id == Transporter.id).where(
        TransporterRate.is_active.is_(True), Transporter.is_active.is_(True))
    if transporter_id:
        stmt = stmt.where(Transporter.id == transporter_id)
    out = []
    for rate, t in session.execute(stmt).all():
        if rate.valid_from and rate.valid_from > when or rate.valid_until and rate.valid_until < when:
            continue
        if vehicle_type and rate.vehicle_type and rate.vehicle_type != vehicle_type:
            continue
        a, b = _place_match(rate.from_place, from_place), _place_match(rate.to_place, to_place)
        if not a or not b:
            continue
        quantity = {"trip": Decimal("1"), "km": distance, "tonne": weight / 1000 if weight is not None else None,
                    "quintal": weight / 100 if weight is not None else None, "kg": weight, "unit": count, "hour": duration}[rate.basis]
        if quantity is None:
            amount, note = None, "needs {}".format({"km": "the distance", "unit": "the number of units", "hour": "the hours"}.get(rate.basis, "the weight"))
        else:
            amount = money(rate.rate * quantity)
            note = None
            if rate.min_charge is not None and amount < rate.min_charge:
                amount, note = rate.min_charge, "minimum charge"
        out.append({"transporter_id": t.id, "transporter": t.name, "rate_id": rate.id, "route": "{} → {}".format(rate.from_place or "anywhere", rate.to_place or "anywhere"),
                     "vehicle_type": rate.vehicle_type, "vehicle_label": VEHICLES.get(rate.vehicle_type, "Any vehicle") if rate.vehicle_type else "Any vehicle",
                     "basis": rate.basis, "rate": float(rate.rate), "amount": float(amount) if amount is not None else None, "note": note,
                     "loading_included": rate.loading_included, "match": a + b, "rating": t.rating})
    out.sort(key=lambda r: (r["amount"] is None, -r["match"], r["amount"] or 0))
    return out


# ---------------------------------------------------------------------------
# Trips, charges and the statement
# ---------------------------------------------------------------------------


def charges(session: Session, transporter_id: Optional[uuid.UUID] = None) -> List[Dict[str, Any]]:
    """Freight owed to transporters: their bills, newest first."""
    rows: List[Dict[str, Any]] = []
    stmt = select(CustomerDelivery).where(CustomerDelivery.transporter_id.is_not(None))
    if transporter_id:
        stmt = stmt.where(CustomerDelivery.transporter_id == transporter_id)
    for d in session.execute(stmt).scalars():
        rows.append({"transporter_id": d.transporter_id, "date": d.created_at, "kind": "delivery", "number": d.delivery_number, "id": d.id,
                     "vehicle": d.vehicle_number, "lr_number": d.lr_number,
                     "amount": float(d.freight_amount if d.freight_paid_by == "us" else 0), "paid_by": d.freight_paid_by})
    stmt = select(GoodsReceipt).where(GoodsReceipt.transporter_id.is_not(None))
    if transporter_id:
        stmt = stmt.where(GoodsReceipt.transporter_id == transporter_id)
    receipts = {g.id: g for g in session.execute(stmt).scalars()}
    stmt = select(LandedCostCharge, LandedCost).join(LandedCost, LandedCostCharge.landed_cost_id == LandedCost.id).where(LandedCostCharge.transporter_id.is_not(None))
    if transporter_id:
        stmt = stmt.where(LandedCostCharge.transporter_id == transporter_id)
    charged_receipts = set()
    for charge, landed in session.execute(stmt).all():
        receipt = receipts.get(landed.goods_receipt_id) or session.get(GoodsReceipt, landed.goods_receipt_id)
        charged_receipts.add(landed.goods_receipt_id)
        rows.append({"transporter_id": charge.transporter_id, "date": landed.created_at, "kind": "receipt", "number": receipt.receipt_number if receipt else landed.number,
                     "id": landed.goods_receipt_id, "vehicle": receipt.vehicle_number if receipt else None, "lr_number": receipt.lr_number if receipt else None,
                     "amount": float(charge.amount), "charge": charge.kind, "bill_number": charge.bill_number})
    for g in receipts.values():
        if g.id not in charged_receipts:
            rows.append({"transporter_id": g.transporter_id, "date": g.created_at, "kind": "receipt", "number": g.receipt_number, "id": g.id,
                         "vehicle": g.vehicle_number, "lr_number": g.lr_number, "amount": 0.0})
    stmt = select(StockTransferCost, StockTransfer).join(StockTransfer, StockTransferCost.transfer_id == StockTransfer.id).where(
        StockTransferCost.transporter_id.is_not(None), StockTransfer.status.in_(("in_transit", "received")))
    if transporter_id:
        stmt = stmt.where(StockTransferCost.transporter_id == transporter_id)
    for cost, transfer in session.execute(stmt).all():
        rows.append({"transporter_id": cost.transporter_id, "date": transfer.dispatched_at or transfer.created_at, "kind": "transfer", "number": transfer.number,
                     "id": transfer.id, "vehicle": transfer.vehicle, "lr_number": transfer.lr_number, "amount": float(cost.amount), "charge": cost.kind})
    stmt = select(TransportBooking).where(TransportBooking.transporter_id.is_not(None), TransportBooking.status == "done",
                                          TransportBooking.agreed_amount.is_not(None), TransportBooking.reference_id.is_(None))
    if transporter_id:
        stmt = stmt.where(TransportBooking.transporter_id == transporter_id)
    for b in session.execute(stmt).scalars():
        rows.append({"transporter_id": b.transporter_id, "date": b.confirmed_at or b.created_at, "kind": "booking", "number": b.number, "id": b.id,
                     "vehicle": b.vehicle_number, "lr_number": None, "amount": float(b.agreed_amount or 0)})
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def _trip_counts(session: Session) -> Dict[uuid.UUID, int]:
    counts: Dict[uuid.UUID, int] = {}
    for row in charges(session):
        counts[row["transporter_id"]] = counts.get(row["transporter_id"], 0) + 1
    return counts


def balances(session: Session) -> Dict[uuid.UUID, float]:
    owed: Dict[uuid.UUID, float] = {}
    for row in charges(session):
        owed[row["transporter_id"]] = round(owed.get(row["transporter_id"], 0.0) + row["amount"], 2)
    for tid, paid in session.execute(select(Payment.transporter_id, func.sum(Payment.amount)).where(
            Payment.transporter_id.is_not(None), Payment.voided_at.is_(None)).group_by(Payment.transporter_id)).all():
        owed[tid] = round(owed.get(tid, 0.0) - float(paid or 0), 2)
    return owed


def statement(session: Session, transporter_id: uuid.UUID) -> Dict[str, Any]:
    from .finance import _local_day

    t = get(session, transporter_id)
    bills = [c for c in charges(session, transporter_id) if c["amount"]]
    payments = session.execute(select(Payment).where(Payment.transporter_id == transporter_id, Payment.voided_at.is_(None)).order_by(Payment.paid_on)).scalars().all()
    entries = [{"date": _local_day(c["date"]), "kind": c["kind"], "number": c["number"], "id": c["id"], "debit": c["amount"], "credit": 0.0,
                "detail": " · ".join(x for x in (c.get("charge"), c.get("vehicle"), ("LR " + c["lr_number"]) if c.get("lr_number") else None) if x)} for c in bills]
    entries += [{"date": _local_day(p.paid_on), "kind": "payment", "number": p.number, "id": p.id, "debit": 0.0, "credit": float(p.amount),
                 "detail": " · ".join(x for x in (p.method, p.reference) if x)} for p in payments]
    entries.sort(key=lambda e: (e["date"], e["kind"] == "payment"))
    balance = 0.0
    for e in entries:
        balance = round(balance + e["debit"] - e["credit"], 2)
        e["balance"] = balance
    billed = round(sum(e["debit"] for e in entries), 2)
    paid = round(sum(e["credit"] for e in entries), 2)
    due_by = datetime.now(timezone.utc) - timedelta(days=t.payment_terms_days or 0)
    overdue = max(0.0, round(sum(c["amount"] for c in bills if c["date"] <= due_by) - paid, 2))
    return {"party": "transporter", "party_id": t.id, "name": t.name,
            "summary": {"billed": billed, "paid": paid, "balance": balance, "overdue": overdue, "payment_terms_days": t.payment_terms_days},
            "entries": entries}


def detail(session: Session, transporter_id: uuid.UUID) -> Dict[str, Any]:
    from . import parties

    t = get(session, transporter_id)
    out = view(session, t, detail=True)
    trips = charges(session, transporter_id)
    out["trips"] = [dict(r, date=r["date"]) for r in trips[:50]]
    out["statement"] = statement(session, transporter_id)["summary"]
    out["bookings"] = [booking_view(b) for b in session.execute(
        select(TransportBooking).where(TransportBooking.transporter_id == transporter_id).order_by(TransportBooking.created_at.desc()).limit(30)).scalars()]
    out["profile"] = parties.profile(session, "transporter", transporter_id)
    return out


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------


def booking_view(b: TransportBooking) -> Dict[str, Any]:
    return {"id": b.id, "number": b.number, "status": b.status, "transporter_id": b.transporter_id,
            "transporter": b.transporter.name if b.transporter else None, "purpose": b.purpose,
            "reference_type": b.reference_type, "reference_id": b.reference_id, "reference_number": b.reference_number,
            "from_place": b.from_place, "to_place": b.to_place, "needed_at": b.needed_at, "vehicle_type": b.vehicle_type,
            "vehicle_label": VEHICLES.get(b.vehicle_type, b.vehicle_type) if b.vehicle_type else None, "load": b.load,
            "weight_kg": float(b.weight_kg) if b.weight_kg is not None else None,
            "estimate": float(b.estimate) if b.estimate is not None else None, "agreed_amount": float(b.agreed_amount) if b.agreed_amount is not None else None,
            "vehicle_number": b.vehicle_number, "driver_phone": b.driver_phone, "requested_by": b.requested_by, "channel": b.channel,
            "reply": b.reply, "notes": b.notes, "created_at": b.created_at, "confirmed_at": b.confirmed_at}


def list_bookings(session: Session, status: Optional[str] = None, reference_id: Optional[uuid.UUID] = None, limit: int = 100) -> List[Dict[str, Any]]:
    stmt = select(TransportBooking).order_by(TransportBooking.created_at.desc())
    if status:
        stmt = stmt.where(TransportBooking.status == status)
    if reference_id:
        stmt = stmt.where(TransportBooking.reference_id == reference_id)
    return [booking_view(b) for b in session.execute(stmt.limit(limit)).scalars()]


def _reference(session: Session, kind: Optional[str], ref_id: Optional[uuid.UUID]) -> Dict[str, Any]:
    """Route, load and weight for a document needing transport."""
    from ..models import Product, PurchaseOrder, SalesOrder, Warehouse

    if not kind or not ref_id:
        return {}
    if kind == "sales_order":
        order = session.get(SalesOrder, ref_id)
        if order is None:
            raise NotFoundError("Order not found.")
        weight = sum((Decimal(i.product.weight_kg) * i.quantity_pending for i in order.items if i.product.weight_kg is not None), Decimal("0"))
        site = None
        if order.delivery_address_id:
            from ..models import Address

            address = session.get(Address, order.delivery_address_id)
            site = ", ".join(x for x in (address.line, address.city) if x) if address else None
        default = session.execute(select(Warehouse).where(Warehouse.is_default.is_(True))).scalars().first()
        return {"purpose": "delivery", "reference_number": order.order_number, "from_place": default.address or default.name if default else None,
                "to_place": site or order.customer.address or order.customer.name,
                "load": "; ".join("{:g} {} {}".format(float(i.quantity_pending), i.product.unit_of_measure, i.product.name) for i in order.items if i.quantity_pending > 0),
                "weight_kg": weight or None}
    if kind == "purchase_order":
        po = session.get(PurchaseOrder, ref_id)
        if po is None:
            raise NotFoundError("Purchase order not found.")
        weight = sum((Decimal(i.product.weight_kg) * i.quantity_remaining for i in po.items if i.product.weight_kg is not None), Decimal("0"))
        default = session.execute(select(Warehouse).where(Warehouse.is_default.is_(True))).scalars().first()
        return {"purpose": "purchase", "reference_number": po.po_number, "from_place": po.supplier.address or po.supplier.name,
                "to_place": default.address or default.name if default else None,
                "load": "; ".join("{:g} {} {}".format(float(i.quantity_remaining), i.product.unit_of_measure, i.product.name) for i in po.items if i.quantity_remaining > 0),
                "weight_kg": weight or None}
    if kind == "stock_transfer":
        transfer = session.get(StockTransfer, ref_id)
        if transfer is None:
            raise NotFoundError("Transfer not found.")
        weight = sum((Decimal(i.product.weight_kg) * i.quantity for i in transfer.items if i.product.weight_kg is not None), Decimal("0"))
        return {"purpose": "transfer", "reference_number": transfer.number,
                "from_place": transfer.from_warehouse.address or transfer.from_warehouse.name, "to_place": transfer.to_warehouse.address or transfer.to_warehouse.name,
                "load": "; ".join("{:g} {} {}".format(float(i.quantity), i.product.unit_of_measure, i.product.name) for i in transfer.items), "weight_kg": weight or None}
    raise ValidationError("Unknown document type '{}'.".format(kind))


def save_booking(session: Session, data: Dict[str, Any], booking_id: Optional[uuid.UUID] = None, user: Optional[User] = None,
                 requested_by: str = "person", channel: str = "manual") -> Dict[str, Any]:
    begin_write(session)
    try:
        b = session.get(TransportBooking, booking_id) if booking_id else TransportBooking(
            number=next_document_number(session, BOOKING_COUNTER, "TB"), status="draft", requested_by=requested_by, channel=channel,
            created_by_id=user.id if user else None)
        if b is None:
            raise NotFoundError("Booking not found.")
        if booking_id is None and data.get("reference_type") and data.get("reference_id"):
            ref = _reference(session, data["reference_type"], uuid.UUID(str(data["reference_id"])))
            b.reference_type, b.reference_id = data["reference_type"], uuid.UUID(str(data["reference_id"]))
            for key, value in ref.items():
                if data.get(key) in (None, ""):
                    setattr(b, key, value)
        for key in ("from_place", "to_place", "load", "notes", "vehicle_number", "driver_phone", "reply"):
            if key in data and data[key] is not None:
                setattr(b, key, (str(data[key]).strip() or None))
        if data.get("purpose"):
            if data["purpose"] not in ("delivery", "purchase", "transfer", "return", "other"):
                raise ValidationError("Purpose is delivery, purchase, transfer, return or other.")
            b.purpose = data["purpose"]
        if "transporter_id" in data:
            b.transporter_id = get(session, uuid.UUID(str(data["transporter_id"]))).id if data["transporter_id"] else None
        if "vehicle_type" in data:
            if data["vehicle_type"] and data["vehicle_type"] not in VEHICLE_TYPES:
                raise ValidationError("Unknown vehicle type.")
            b.vehicle_type = data["vehicle_type"] or None
        if "needed_at" in data:
            b.needed_at = _when(data["needed_at"])
        if "weight_kg" in data and data["weight_kg"] not in (None, ""):
            b.weight_kg = Decimal(str(data["weight_kg"]))
        if "agreed_amount" in data:
            b.agreed_amount = money(data["agreed_amount"]) if data["agreed_amount"] not in (None, "") else None
        session.add(b)
        session.flush()
        if b.transporter_id:
            hits = estimate(session, b.from_place, b.to_place, b.vehicle_type, b.weight_kg, transporter_id=b.transporter_id)
            priced = [h for h in hits if h["amount"] is not None]
            b.estimate = Decimal(str(priced[0]["amount"])) if priced else b.estimate
        if data.get("status"):
            _set_status(b, data["status"])
        session.commit()
    except Exception:
        session.rollback()
        raise
    return booking_view(b)


def _set_status(b: TransportBooking, status: str) -> None:
    if status not in BOOKING_STATUS:
        raise ValidationError("Unknown status '{}'.".format(status))
    if status in ("requested", "confirmed") and not b.transporter_id:
        raise ValidationError("Choose the transporter first.")
    b.status = status
    if status == "confirmed" and b.confirmed_at is None:
        b.confirmed_at = datetime.now(timezone.utc)


def request_message(session: Session, b: TransportBooking) -> str:
    """What TAI sends a transporter to ask for a vehicle."""
    from . import integration_settings as settings_service

    business = settings_service.get(session, settings_service.TALLY).config.get("seller_name") or "us"
    parts = ["Namaste, {} here. Booking {}: we need {} {}".format(business, b.number, "a" if not b.vehicle_type else "a " + VEHICLES.get(b.vehicle_type, b.vehicle_type), "vehicle")]
    if b.needed_at:
        parts.append("on {}".format(b.needed_at.astimezone().strftime("%d %b, %I:%M %p")))
    if b.from_place or b.to_place:
        parts.append("from {} to {}".format(b.from_place or "our godown", b.to_place or "-"))
    text = " ".join(parts) + "."
    if b.load:
        text += " Load: {}".format(b.load)
        if b.weight_kg:
            text += " (about {:,.0f} kg)".format(float(b.weight_kg))
        text += "."
    if b.estimate:
        text += " Your rate card gives Rs {:,.0f}.".format(float(b.estimate))
    text += " Please reply YES with the vehicle number and rate, or NO if not available."
    return text
