"""The purchasing agent on the phone.

It calls suppliers about a purchase enquiry and records each supplier's offer
(``record_quote``), or that they cannot supply or want a call back. It never
orders: the 'Pick the offer' step turns the chosen offer into the purchase order.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    PurchaseOrder, PurchaseOrderStatus, SupplierQuote, SupplierQuoteLine, SupplierQuoteRequest, SupplierQuoteRequestLine,
)
from . import automation, triggers

logger = logging.getLogger(__name__)

RETRY_AFTER = timedelta(minutes=45)
NO_ANSWER_AFTER = timedelta(minutes=15)
CALLS_PER_TICK = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dec(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("₹", "").strip())
    except InvalidOperation:
        return None


def _ask_step(session: Session) -> Dict[str, Any]:
    return automation.step(session, "purchase.ask_supplier")


def calls_on(step: Dict[str, Any]) -> bool:
    return (step["config"].get("how") or "text") in ("call", "text_then_call") and automation.allowed(step, "pai")


def _place(phone: str, mode: str, params: Dict[str, str]) -> None:
    from ..voice import outbound

    outbound.place_call(phone, mode, params)


# ---------------------------------------------------------------------------
# Price requests by phone
# ---------------------------------------------------------------------------


def _items(session: Session, rfq: SupplierQuoteRequest, quote: SupplierQuote) -> List[Tuple[int, SupplierQuoteRequestLine, Decimal, str, Decimal]]:
    """The lines this supplier is asked about: (number, line, quantity in the
    purchase unit, that unit, its factor to the base unit)."""
    lines = triggers._lines_for(session, rfq, quote.supplier) or list(rfq.lines)
    out = []
    for n, line in enumerate(lines, start=1):
        qty, unit, factor = triggers._in_unit(session, line.product, line.quantity)
        out.append((n, line, qty, unit, factor))
    return out


def quote_brief(session: Session, quote_id: uuid.UUID) -> str:
    """What the agent asks on the call, and how far it may go."""
    quote = session.get(SupplierQuote, quote_id)
    if quote is None:
        return ""
    rfq = quote.request
    cfg = _ask_step(session)["config"]
    lines = []
    for n, line, qty, unit, factor in _items(session, rfq, quote):
        spec = " ({})".format(line.product.brand) if line.product.brand else ""
        text = "{}. {}{}: {} {}".format(n, line.product.name, spec, triggers._qty(qty), unit)
        last = triggers._last_paid(session, line.product_id)
        if cfg.get("negotiate") and last:
            text += " -- our last price was Rs {:,.2f} per {}".format(float(last * factor), unit)
        lines.append(text)
    needed = " Needed by {}.".format(rfq.needed_by.astimezone(triggers._zone()).strftime("%d %B")) if rfq.needed_by else ""
    return ("Purchase enquiry {} to {} (contact: {}).{} Items:\n{}\n{}{}").format(
        rfq.number, quote.supplier.name, quote.supplier.contact_person or "the owner", needed, "\n".join(lines),
        "If a quote is above our last price, politely ask whether they can match it; never tell them any other supplier's price. "
        if cfg.get("negotiate") else "",
        "You only collect their offer. Never confirm or place an order: after record_quote, say we will send the purchase order once it is decided.")


def record_quote(session: Session, quote_id: uuid.UUID, args: Dict[str, Any], call_id: Optional[uuid.UUID] = None,
                 channel: str = "call") -> Dict[str, Any]:
    """Store what the supplier offered (on a call, or read from WhatsApp by AI).

    A later call adds to the earlier one: lines and terms not given again are
    kept. The reply lists what is still missing -- delivery days, quantity they
    can supply, GST, freight, how long the price holds -- so the agent asks for
    exactly that and records again."""
    quote = session.get(SupplierQuote, quote_id)
    if quote is None:
        return {"error": "No purchase enquiry on this call."}
    rfq = quote.request
    items = {n: (line, factor, unit) for n, line, _, unit, factor in _items(session, rfq, quote)}
    existing = {ql.product_id: ql for ql in quote.lines}
    given = 0
    for row in args.get("lines") or []:
        try:
            n = int(row.get("item"))
        except (TypeError, ValueError):
            continue
        if n not in items:
            continue
        line, factor, unit = items[n]
        price = _dec(row.get("price"))
        available = _dec(row.get("available_quantity"))
        held = existing.get(line.product_id)
        if price is not None and price > 0:
            if held is None:
                held = SupplierQuoteLine(product_id=line.product_id, price=Decimal("0"))
                quote.lines.append(held)
                existing[line.product_id] = held
            held.price = (price / factor).quantize(Decimal("0.0001"))
        if held is not None and available is not None and available >= 0:
            held.quantity_available = available * factor
        given += 1 if held is not None else 0
    if not existing:
        return {"error": "No usable price yet: give the item number and the price per unit for each item."}
    days = args.get("delivery_days")
    if str(days if days is not None else "").strip().isdigit():
        quote.delivery_days = int(days)
    if args.get("freight") is not None and _dec(args.get("freight")) is not None:
        quote.freight = _dec(args.get("freight"))
    if args.get("gst_included") is not None:
        quote.gst_included = bool(args["gst_included"])
    valid = args.get("valid_days")
    if str(valid if valid is not None else "").strip().isdigit():
        quote.valid_until = _now().astimezone(triggers._zone()).date() + timedelta(days=int(valid))
    saved, totals, checks, missing = [], [], [], []
    for n, (line, factor, unit) in items.items():
        held = existing.get(line.product_id)
        if held is None:
            missing.append("the price of item {} ({})".format(n, line.product.name))
            continue
        price = held.price * factor
        qty = line.quantity / factor
        saved.append("{} at Rs {} per {}{}".format(line.product.name, triggers._qty(price), unit, ", {} {} available".format(
            triggers._qty(held.quantity_available / factor), unit) if held.quantity_available is not None else ""))
        totals.append("{} {} x Rs {} = Rs {:,.0f}".format(triggers._qty(qty), unit, triggers._qty(price), float(qty * price)))
        if held.quantity_available is None:
            missing.append("whether they can supply all {} {} of item {} (or how many)".format(triggers._qty(qty), unit, n))
        last = triggers._last_paid(session, line.product_id)
        if last and not 0.6 <= float(price / (last * factor)) <= 1.5:
            # Far from what we paid last time: most often a total heard as a unit price, or the reverse.
            checks.append("Rs {} is far from our last price of Rs {:,.0f} per {}: ask whether Rs {} is per {} or for all {} {}".format(
                triggers._qty(price), float(last * factor), unit, triggers._qty(price), unit, triggers._qty(qty), unit))
    if quote.delivery_days is None:
        missing.append("how many days to deliver")
    if quote.gst_included is None:
        missing.append("whether GST is extra or included")
    if quote.freight is None:
        missing.append("freight or delivery charge (0 if free)")
    if quote.valid_until is None:
        missing.append("how many days the price holds")
    quote.status, quote.replied_at, quote.channel = "replied", _now(), channel
    quote.phone_call_id = call_id or quote.phone_call_id
    quote.reply = "{}: {}{}{}{}{}{}".format(
        "On the call" if channel == "call" else "Read by AI from " + channel, "; ".join(saved),
        ", GST {}".format("included" if quote.gst_included else "extra") if quote.gst_included is not None else "",
        ", delivery in {} days".format(quote.delivery_days) if quote.delivery_days is not None else "",
        ", freight {}".format("free" if quote.freight == 0 else "Rs {}".format(quote.freight)) if quote.freight is not None else "",
        ", price valid till {}".format(quote.valid_until.strftime("%d %b")) if quote.valid_until else "",
        ". " + str(args.get("notes")) if args.get("notes") else "")
    session.commit()
    triggers.event(session, "purchase.ask_supplier", "quote", "done", "{} quoted {} {}".format(
        quote.supplier.name, rfq.number, "on the phone" if channel == "call" else "on " + channel),
                   party=("supplier", quote.supplier_id), subject=("rfq", rfq.id))
    if checks:
        say = "Saved so far. First check the unit: {}. If they correct it, call record_quote again with the per-unit price.".format("; ".join(checks))
    elif missing:
        say = "Saved so far. Still missing: {}. Ask for these one at a time, then call record_quote again with the answers.".format("; ".join(missing))
    else:
        say = ("The offer is complete. Read back the per-unit prices{}; then thank them and say we will send the purchase order once it is decided.").format(
            " and, if you mention a total, use exactly: " + "; ".join(totals) if totals else "")
    return {"recorded": saved, "missing": missing, "totals": totals, "complete": not missing and not checks, "say": say}


def cannot_quote(session: Session, quote_id: uuid.UUID, reason: str) -> Dict[str, Any]:
    quote = session.get(SupplierQuote, quote_id)
    if quote is None:
        return {"error": "No price request on this call."}
    quote.status, quote.replied_at, quote.channel = "declined", _now(), "call"
    quote.reply = "On the call: cannot supply. {}".format(reason or "")
    session.commit()
    triggers.event(session, "purchase.ask_supplier", "declined", "done", "{} cannot supply {}".format(quote.supplier.name, quote.request.number),
                   party=("supplier", quote.supplier_id), subject=("rfq", quote.request_id))
    _decide_if_complete(session, quote.request)
    return {"ok": True, "say": "Thank them and end the call."}


def call_back(session: Session, quote_id: uuid.UUID, minutes: Any) -> Dict[str, Any]:
    quote = session.get(SupplierQuote, quote_id)
    if quote is None:
        return {"error": "No price request on this call."}
    try:
        wait = max(10, min(int(minutes), 24 * 60))
    except (TypeError, ValueError):
        wait = 60
    quote.status, quote.last_call_at = "asked", _now() + timedelta(minutes=wait) - RETRY_AFTER
    quote.reply = "Asked to call back in {} minutes.".format(wait)
    session.commit()
    return {"ok": True, "say": "Say you will call back then, and end the call."}


def quote_call_ended(session: Session, quote_id: uuid.UUID, summary: str) -> None:
    """The call ended. If nothing was recorded, the quote waits for the next try."""
    quote = session.get(SupplierQuote, quote_id)
    if quote is None or quote.status != "calling":
        if quote is not None and quote.status == "replied":
            _decide_if_complete(session, quote.request)
        return
    quote.status = "asked"
    quote.reply = ("Call: " + summary)[:2000] if summary else quote.reply
    session.commit()


def _decide_if_complete(session: Session, rfq: SupplierQuoteRequest) -> None:
    if rfq.status == "open" and rfq.quotes and all(q.status in ("replied", "declined", "no_reply") for q in rfq.quotes):
        triggers.decide(session, rfq.id)


def run_quote_calls(session: Session) -> int:
    """Ring suppliers for price requests: straight away ("call"), or when a
    WhatsApp request got no reply ("text_then_call"). Retries, then gives up."""
    step = _ask_step(session)
    if not calls_on(step):
        return 0
    cfg = step["config"]
    now = _now()
    tries = int(cfg.get("call_tries") or 2)
    # Calls that never connected or ended silently: back to waiting.
    for quote in session.execute(select(SupplierQuote).where(SupplierQuote.status == "calling", SupplierQuote.last_call_at <= now - NO_ANSWER_AFTER)).scalars():
        quote.status = "asked"
    session.commit()
    if not triggers.in_window(cfg):
        return 0
    how = cfg.get("how")
    after = timedelta(hours=float(cfg.get("call_after_hours") or 2))
    rows = session.execute(select(SupplierQuote).join(SupplierQuoteRequest, SupplierQuoteRequest.id == SupplierQuote.request_id)
                           .where(SupplierQuoteRequest.status == "open", SupplierQuote.status.in_(("to_ask", "asked")),
                                  SupplierQuote.call_attempts < tries)).scalars().all()
    placed = 0
    for quote in rows:
        if placed >= CALLS_PER_TICK:
            break
        if not quote.supplier.phone:
            continue
        if quote.last_call_at and now - quote.last_call_at < RETRY_AFTER:
            continue
        if how == "call":
            if quote.status not in ("to_ask", "asked"):
                continue
        else:  # text first: only once the text has had time to be answered
            if quote.status != "asked" or not quote.asked_at or now - quote.asked_at < after:
                continue
        quote.call_attempts += 1
        quote.last_call_at = now
        try:
            _place(quote.supplier.phone, "supplier_quote", {"quote": str(quote.id)})
            quote.status = "calling"
            quote.asked_at = quote.asked_at or now
            quote.channel = quote.channel or "call"
            placed += 1
            status = "sent"
        except Exception as exc:
            logger.warning("Could not call %s: %s", quote.supplier.name, exc)
            status = "failed"
        triggers.event(session, "purchase.ask_supplier", "call", status, "Calling {} for {} (try {} of {})".format(
            quote.supplier.name, quote.request.number, quote.call_attempts, tries), party=("supplier", quote.supplier_id), subject=("rfq", quote.request_id))
        session.commit()
    return placed


def tick(session: Session) -> Dict[str, int]:
    return {"quote_calls": run_quote_calls(session)}
