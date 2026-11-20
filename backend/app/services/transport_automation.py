"""Booking transport automatically, from the "Book transport" step of a flow.

The step can sit anywhere in the sales or purchase flow and says *when* it
runs (an order is placed, its stock is ready, a purchase order is placed),
*who* asks (a person, TAI on WhatsApp, PAI on a call), *which* transporter
(cheapest on the rate card, best rated, or a fixed one), and limits for
confirming on its own (freight up to an amount, or not above the rate card
by more than a percentage).

1. The trigger creates a booking with the route, load and weight of the
   document, and the rate card's estimate.
2. In approval mode it waits as a draft for a person. Otherwise TAI sends the
   transporter a WhatsApp request, or PAI rings them.
3. The transporter's reply (WhatsApp, or what was agreed on the call) is read:
   YES with the vehicle number and rate confirms the booking if it is within
   the limits; NO declines it, and the next transporter is asked.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import TransportBooking, Transporter
from . import automation

logger = logging.getLogger(__name__)

STEP = {"sales": "sales.book_transport", "purchase": "purchase.book_transport"}
YES = re.compile(r"\b(yes|ok|okay|haan|ha|han|ji|confirm|confirmed|done|booked|hoga|thik|theek)\b", re.I)
NO = re.compile(r"\b(no|nahi|nahin|na|not available|busy|sorry|nai)\b", re.I)
VEHICLE = re.compile(r"\b([A-Z]{2}\s?-?\d{1,2}\s?-?[A-Z]{0,3}\s?-?\d{3,4})\b", re.I)
AMOUNT = re.compile(r"(?:rs\.?|₹|inr)?\s*(\d{3,6}(?:,\d{3})*(?:\.\d+)?)\s*(?:rs|rupees|/-)?", re.I)


def _candidates(session: Session, booking: TransportBooking, timing: Dict[str, Any], tried: List[uuid.UUID]) -> List[Dict[str, Any]]:
    from . import transporters

    fixed = timing.get("transporter_id")
    if fixed:
        try:
            t = session.get(Transporter, uuid.UUID(str(fixed)))
        except ValueError:
            t = None
        return [] if t is None or t.id in tried or not t.is_active else [{"transporter_id": t.id, "amount": None, "rating": t.rating}]
    hits = transporters.estimate(session, booking.from_place, booking.to_place, booking.vehicle_type, booking.weight_kg)
    best: Dict[uuid.UUID, Dict[str, Any]] = {}
    for hit in hits:
        if hit["transporter_id"] in tried or hit["amount"] is None:
            continue
        if hit["transporter_id"] not in best or hit["amount"] < best[hit["transporter_id"]]["amount"]:
            best[hit["transporter_id"]] = hit
    rows = list(best.values())
    if timing.get("choose") == "best_rated":
        rows.sort(key=lambda r: (-(r["rating"] or 0), r["amount"]))
    else:
        rows.sort(key=lambda r: r["amount"])
    return rows


def trigger(session: Session, flow: str, event: str, reference_type: str, reference_id: uuid.UUID) -> Optional[Dict[str, Any]]:
    """Run the flow's "Book transport" step for a document, if the step is on and set to this moment."""
    from . import transporters

    if STEP[flow] in automation.PARKED:  # transport is booked by hand for now
        return None
    data = automation.step(session, STEP[flow])
    if data.get("mode") == "off":
        return None
    timing = data.get("timing") or {}
    if (timing.get("when") or ("order_placed" if flow == "sales" else "po_placed")) != event:
        return None
    existing = session.execute(select(TransportBooking).where(
        TransportBooking.reference_id == reference_id, TransportBooking.status.notin_(("cancelled", "declined")))).scalars().first()
    if existing is not None:
        return None
    booking = transporters.save_booking(session, {"reference_type": reference_type, "reference_id": reference_id,
                                                  "vehicle_type": timing.get("vehicle_type") or None},
                                        requested_by="system", channel="manual")
    return ask(session, uuid.UUID(str(booking["id"])))


def ask(session: Session, booking_id: uuid.UUID, tried: Optional[List[uuid.UUID]] = None) -> Dict[str, Any]:
    """Pick the transporter and ask them, as the step allows."""
    from . import outbox, transporters

    booking = session.get(TransportBooking, booking_id)
    flow = "purchase" if booking.purpose == "purchase" else "sales"
    data = automation.step(session, STEP[flow])
    timing = data.get("timing") or {}
    tried = list(tried or [])
    if booking.transporter_id is None or booking.transporter_id in tried:
        found = _candidates(session, booking, timing, tried)
        if not found:
            booking.status = "draft"
            booking.notes = ((booking.notes or "") + "\nNo transporter on the rate card fits this trip; a person must choose.").strip()
            session.commit()
            return transporters.booking_view(booking)
        booking.transporter_id = found[0]["transporter_id"]
        if found[0]["amount"] is not None:
            booking.estimate = Decimal(str(found[0]["amount"]))
    transporter = session.get(Transporter, booking.transporter_id)
    automatic = data.get("mode") in ("auto", "limits")
    can_text = "tai" in data.get("actors", []) and "whatsapp" in (data.get("channels") or ["whatsapp"]) and transporter.booking_channel in ("whatsapp", "either")
    can_call = "pai" in data.get("actors", []) and "call" in (data.get("channels") or []) and transporter.booking_channel in ("call", "either")
    if not automatic or not transporter.phone or not (can_text or can_call):
        booking.status = "draft"
        booking.requested_by = "person"
        if not transporter.phone:
            booking.notes = ((booking.notes or "") + "\n{} has no phone number.".format(transporter.name)).strip()
        session.commit()
        return transporters.booking_view(booking)
    if can_text:
        outbox.queue(session, "whatsapp", transporter.phone, transporters.request_message(session, booking), hold=False, author="tai")
        booking.requested_by, booking.channel = "tai", "whatsapp"
        booking.status = "requested"
    else:
        from ..voice import outbound

        try:
            outbound.place_call(transporter.phone, "book", {"booking": str(booking.id)})
            booking.requested_by, booking.channel, booking.status = "pai", "call", "requested"
        except Exception as exc:  # calling not set up, or Twilio refused
            booking.status = "draft"
            booking.notes = ((booking.notes or "") + "\nPAI could not call: {}".format(exc)).strip()
    session.commit()
    return transporters.booking_view(booking)


def _parse(text: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if NO.search(text) and not YES.search(text):
        out["answer"] = "no"
    elif YES.search(text):
        out["answer"] = "yes"
    vehicle = VEHICLE.search(text)
    if vehicle:
        out["vehicle_number"] = re.sub(r"[\s-]", "", vehicle.group(1)).upper()
    cleaned = VEHICLE.sub(" ", text)
    amounts = [Decimal(m.group(1).replace(",", "")) for m in AMOUNT.finditer(cleaned)]
    amounts = [a for a in amounts if a >= 100]
    if amounts:
        out["amount"] = max(amounts)
    phone = re.search(r"\b(\+?91[\s-]?)?([6-9]\d{9})\b", cleaned)
    if phone:
        out["driver_phone"] = phone.group(2)
    return out


def settle(session: Session, booking: TransportBooking, answer: str, amount: Optional[Decimal] = None, vehicle_number: Optional[str] = None,
           driver_phone: Optional[str] = None, reply: Optional[str] = None, via: str = "tai") -> Dict[str, Any]:
    """Apply a transporter's yes or no to a booking, within the step's limits."""
    from . import outbox, transporters

    flow = "purchase" if booking.purpose == "purchase" else "sales"
    data = automation.step(session, STEP[flow])
    transporter = session.get(Transporter, booking.transporter_id) if booking.transporter_id else None
    booking.reply = ((booking.reply + "\n") if booking.reply else "") + (reply or answer)
    if answer == "no":
        booking.status = "declined"
        session.commit()
        tried = [b.transporter_id for b in session.execute(select(TransportBooking).where(
            TransportBooking.reference_id == booking.reference_id)).scalars() if b.transporter_id] if booking.reference_id else [booking.transporter_id]
        if booking.reference_id and data.get("mode") in ("auto", "limits"):
            follow = transporters.save_booking(session, {"reference_type": booking.reference_type, "reference_id": booking.reference_id,
                                                         "vehicle_type": booking.vehicle_type}, requested_by="system")
            return ask(session, uuid.UUID(str(follow["id"])), tried)
        return transporters.booking_view(booking)
    if vehicle_number:
        booking.vehicle_number = vehicle_number
    if driver_phone:
        booking.driver_phone = driver_phone
    if amount is not None:
        booking.agreed_amount = amount
    agreed = booking.agreed_amount or booking.estimate
    facts = {"freight_amount": float(agreed) if agreed is not None else None,
             "over_estimate_percent": round(float((agreed - booking.estimate) / booking.estimate * 100), 2) if agreed is not None and booking.estimate else None}
    broken = automation.within_limits(data, facts) if data.get("mode") == "limits" else None
    if data.get("mode") == "approval" or broken:
        booking.notes = ((booking.notes or "") + "\nTransporter said yes{}; needs a person: {}.".format(
            " at Rs {:,.0f}".format(float(agreed)) if agreed else "", broken or "approval required")).strip()
        session.commit()
        return transporters.booking_view(booking)
    if booking.agreed_amount is None and booking.estimate is not None:
        booking.agreed_amount = booking.estimate
    booking.status = "confirmed"
    booking.confirmed_at = datetime.now(timezone.utc)
    if via == "tai" and transporter and transporter.phone:
        outbox.queue(session, "whatsapp", transporter.phone, "Thank you, {} is confirmed{}{}.".format(
            booking.number, " for Rs {:,.0f}".format(float(booking.agreed_amount)) if booking.agreed_amount else "",
            ", vehicle {}".format(booking.vehicle_number) if booking.vehicle_number else ""), hold=False, author="tai")
    session.commit()
    return transporters.booking_view(booking)


def handle_reply(session: Session, transporter: Transporter, text: str) -> Optional[Dict[str, Any]]:
    """A WhatsApp message from a transporter: the answer to their latest request."""
    if automation.PARKED >= set(STEP.values()):  # parked: nobody asked a transporter, so nothing to read
        return None
    booking = session.execute(select(TransportBooking).where(
        TransportBooking.transporter_id == transporter.id, TransportBooking.status == "requested").order_by(TransportBooking.created_at.desc())).scalars().first()
    if booking is None:
        return None
    parsed = _parse(text or "")
    if "answer" not in parsed:
        booking.reply = ((booking.reply + "\n") if booking.reply else "") + text
        booking.notes = ((booking.notes or "") + "\nReply not clear; a person should read it.").strip()
        session.commit()
        from .transporters import booking_view

        return booking_view(booking)
    return settle(session, booking, parsed["answer"], parsed.get("amount"), parsed.get("vehicle_number"), parsed.get("driver_phone"), text, via="tai")
