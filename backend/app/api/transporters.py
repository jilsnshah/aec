"""Transporters (who carries the goods), their vehicles and rate card, freight
estimates, statements, and transport bookings."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..services import transporters
from .auth import require_user

router = APIRouter(prefix="/api", tags=["transport"])


class VehicleIn(BaseModel):
    number: Optional[str] = Field(default=None, description="Registration number, e.g. GJ01AB1234.")
    vehicle_type: Optional[str] = Field(default=None, description="tempo, pickup, lcv, 6_wheeler, 10_wheeler, 12_wheeler, 14_wheeler, trailer, tractor, container or other.")
    capacity_kg: Optional[str] = None
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class RateIn(BaseModel):
    from_place: Optional[str] = Field(default=None, description="Empty for anywhere.")
    to_place: Optional[str] = Field(default=None, description="Empty for anywhere.")
    vehicle_type: Optional[str] = Field(default=None, description="Empty for any vehicle.")
    basis: Optional[str] = Field(default=None, description="trip, km, tonne, quintal, kg, unit or hour.")
    rate: Optional[str] = None
    min_charge: Optional[str] = None
    loading_included: Optional[bool] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class TransporterIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    code: Optional[str] = Field(default=None, max_length=32, description="Made automatically if omitted.")
    kind: Optional[str] = Field(default=None, description="company, fleet_owner, broker, tempo, courier or own_fleet.")
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    tally_ledger_name: Optional[str] = Field(default=None, description="Their ledger in Tally (freight bills post here).")
    service_areas: Optional[str] = Field(default=None, description="Places and routes they serve.")
    payment_terms_days: Optional[int] = Field(default=None, ge=0, le=365)
    booking_channel: Optional[str] = Field(default=None, description="How TAI/PAI books them: whatsapp, call or either.")
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    notes: Optional[str] = None
    is_active: Optional[bool] = None
    vehicles: Optional[List[VehicleIn]] = Field(default=None, description="On create: vehicles to add.")
    rates: Optional[List[RateIn]] = Field(default=None, description="On create: rate card lines to add.")


class BookingIn(BaseModel):
    transporter_id: Optional[uuid.UUID] = None
    reference_type: Optional[str] = Field(default=None, description="sales_order, purchase_order or stock_transfer: fills route, load and weight.")
    reference_id: Optional[uuid.UUID] = None
    purpose: Optional[str] = Field(default=None, description="delivery, purchase, transfer, return or other.")
    from_place: Optional[str] = None
    to_place: Optional[str] = None
    needed_at: Optional[str] = Field(default=None, description="When the vehicle is needed (ISO date-time).")
    vehicle_type: Optional[str] = None
    load: Optional[str] = None
    weight_kg: Optional[str] = None
    agreed_amount: Optional[str] = None
    vehicle_number: Optional[str] = None
    driver_phone: Optional[str] = None
    notes: Optional[str] = None
    reply: Optional[str] = None
    status: Optional[str] = Field(default=None, description="draft, requested, confirmed, declined, done or cancelled.")


@router.get("/transporters/meta")
def meta():
    """Kinds of transporter, vehicle types and rate bases."""
    return {"kinds": transporters.KINDS, "vehicles": transporters.VEHICLES, "bases": transporters.BASES}


@router.get("/transporters")
def list_transporters(search: Optional[str] = Query(default=None), include_inactive: bool = Query(default=False),
                      kind: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    """Transporters with vehicles, rates, trips and what we owe them."""
    return {"items": transporters.list_transporters(db, search, include_inactive, kind)}


@router.post("/transporters", status_code=201)
def create_transporter(payload: TransporterIn, db: Session = Depends(get_db)):
    """Add a transporter, optionally with vehicles and rate card lines."""
    data = payload.model_dump(exclude_unset=True)
    t = transporters.save(db, data)
    return transporters.detail(db, t.id)


@router.get("/transporters/estimate")
def estimate(from_place: Optional[str] = Query(default=None), to_place: Optional[str] = Query(default=None),
             vehicle_type: Optional[str] = Query(default=None), weight_kg: Optional[float] = Query(default=None),
             units: Optional[float] = Query(default=None), km: Optional[float] = Query(default=None), hours: Optional[float] = Query(default=None),
             transporter_id: Optional[uuid.UUID] = Query(default=None), db: Session = Depends(get_db)):
    """Freight from every matching rate card line, cheapest first."""
    return {"items": transporters.estimate(db, from_place, to_place, vehicle_type, weight_kg, units, km, hours, transporter_id)}


@router.get("/transporters/{transporter_id}")
def get_transporter(transporter_id: uuid.UUID, db: Session = Depends(get_db)):
    """Everything about a transporter: details, contacts, vehicles, rate card, trips, bookings and balance."""
    return transporters.detail(db, transporter_id)


@router.patch("/transporters/{transporter_id}")
def update_transporter(transporter_id: uuid.UUID, payload: TransporterIn, db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    data.pop("vehicles", None)
    data.pop("rates", None)
    transporters.save(db, data, transporter_id)
    return transporters.detail(db, transporter_id)


@router.get("/transporters/{transporter_id}/statement")
def transporter_statement(transporter_id: uuid.UUID, db: Session = Depends(get_db)):
    """Freight bills and payments with a running balance."""
    return transporters.statement(db, transporter_id)


@router.post("/transporters/{transporter_id}/vehicles", status_code=201)
def add_vehicle(transporter_id: uuid.UUID, payload: VehicleIn, db: Session = Depends(get_db)):
    return transporters.save_vehicle(db, transporter_id, payload.model_dump(exclude_unset=True))


@router.patch("/transporters/{transporter_id}/vehicles/{vehicle_id}")
def update_vehicle(transporter_id: uuid.UUID, vehicle_id: uuid.UUID, payload: VehicleIn, db: Session = Depends(get_db)):
    return transporters.save_vehicle(db, transporter_id, payload.model_dump(exclude_unset=True), vehicle_id)


@router.delete("/transporters/{transporter_id}/vehicles/{vehicle_id}")
def remove_vehicle(transporter_id: uuid.UUID, vehicle_id: uuid.UUID, db: Session = Depends(get_db)):
    return transporters.remove_child(db, transporter_id, "vehicle", vehicle_id)


@router.post("/transporters/{transporter_id}/rates", status_code=201)
def add_rate(transporter_id: uuid.UUID, payload: RateIn, db: Session = Depends(get_db)):
    return transporters.save_rate(db, transporter_id, payload.model_dump(exclude_unset=True))


@router.patch("/transporters/{transporter_id}/rates/{rate_id}")
def update_rate(transporter_id: uuid.UUID, rate_id: uuid.UUID, payload: RateIn, db: Session = Depends(get_db)):
    return transporters.save_rate(db, transporter_id, payload.model_dump(exclude_unset=True), rate_id)


@router.delete("/transporters/{transporter_id}/rates/{rate_id}")
def remove_rate(transporter_id: uuid.UUID, rate_id: uuid.UUID, db: Session = Depends(get_db)):
    return transporters.remove_child(db, transporter_id, "rate", rate_id)


@router.get("/transport-bookings")
def list_bookings(status: Optional[str] = Query(default=None), reference_id: Optional[uuid.UUID] = Query(default=None), db: Session = Depends(get_db)):
    """Vehicle bookings with transporters, newest first."""
    return {"items": transporters.list_bookings(db, status, reference_id)}


@router.post("/transport-bookings", status_code=201)
def create_booking(payload: BookingIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Book a vehicle. With reference_type/reference_id the route, load and weight come from that order, PO or transfer."""
    return transporters.save_booking(db, payload.model_dump(exclude_unset=True, mode="json"), user=user)


@router.patch("/transport-bookings/{booking_id}")
def update_booking(booking_id: uuid.UUID, payload: BookingIn, db: Session = Depends(get_db)):
    """Change a booking or move it on: requested, confirmed (with vehicle and amount), declined, done, cancelled."""
    return transporters.save_booking(db, payload.model_dump(exclude_unset=True, mode="json"), booking_id)
