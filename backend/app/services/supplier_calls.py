"""The purchasing agent on the phone.

It calls suppliers to ask for prices on a price request (RFQ), records each
quote, and -- when the step allows and the offer is within the limits --
places the order on the same call. It can also call a supplier to confirm a
placed purchase order and the dispatch date.

What it may do is decided here, not by the voice model: the model only
reports what the supplier said (``record_quote``, ``order_now``,
``confirm_order``...), and these functions check the step settings, the price
rules and the PO approval limits before anything is ordered.
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
    order_now = cfg.get("order_on_call")
    return ("Price request {} to {} (contact: {}).{} Items:\n{}\n{}{}").format(
        rfq.number, quote.supplier.name, quote.supplier.contact_person or "the owner", needed, "\n".join(lines),
        "If a quote is above our last price, politely ask whether they can match it; never tell them any other supplier's price. "
        if cfg.get("negotiate") else "",
        "After record_quote, if it says can_order is true, offer to place the order now and use order_now once they agree."
        if order_now else "After record_quote, tell them the team will confirm the order shortly.")


def record_quote(session: Session, quote_id: uuid.UUID, args: Dict[str, Any], call_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    """Store what the supplier quoted on the call. Returns whether the order
    may be placed right away."""
    quote = session.get(SupplierQuote, quote_id)
    if quote is None:
        return {"error": "No price request on this call."}
    rfq = quote.request
    items = {n: (line, factor, unit) for n, line, _, unit, factor in _items(session, rfq, quote)}
    quote.lines.clear()
    session.flush()
    saved = []
    for row in args.get("lines") or []:
        try:
            n = int(row.get("item"))
        except (TypeError, ValueError):
            continue
        if n not in items:
            continue
        price = _dec(row.get("price"))
        if price is None or price <= 0:
            continue
        line, factor, unit = items[n]
        quote.lines.append(SupplierQuoteLine(product_id=line.product_id, price=(price / factor).quantize(Decimal("0.0001")),
                                             quantity_available=(_dec(row.get("available_quantity")) or None) and _dec(row.get("available_quantity")) * factor))
        saved.append("{} at Rs {} per {}".format(line.product.name, price, unit))
    if not saved:
        return {"error": "No usable price: give the item number and the price per unit for each item."}
    days = args.get("delivery_days")
    quote.delivery_days = int(days) if str(days or "").strip().isdigit() else quote.delivery_days
    quote.freight = _dec(args.get("freight"))
    quote.gst_included = bool(args["gst_included"]) if args.get("gst_included") is not None else None
    valid = args.get("valid_days")
    quote.valid_until = (_now().date() + timedelta(days=int(valid))) if str(valid or "").strip().isdigit() else None
    quote.status, quote.replied_at, quote.channel = "replied", _now(), "call"
    quote.phone_call_id = call_id or quote.phone_call_id
    quote.reply = "On the call: {}{}{}{}".format(
        "; ".join(saved), ", delivery in {} days".format(quote.delivery_days) if quote.delivery_days is not None else "",
        ", freight Rs {}".format(quote.freight) if quote.freight else "", ". " + str(args.get("notes")) if args.get("notes") else "")
    session.commit()
    triggers.event(session, "purchase.read_reply", "quote", "done", "{} quoted {} on the phone".format(quote.supplier.name, rfq.number),
                   party=("supplier", quote.supplier_id), subject=("rfq", rfq.id))
    ok, why = can_order_now(session, quote)
    return {"recorded": saved, "can_order": ok, "why_not": why,
            "say": "Offer to place the order now: read back items, quantities, prices and ask for the delivery date." if ok else
            "Thank them; the team will confirm the order shortly."}


def can_order_now(session: Session, quote: SupplierQuote) -> Tuple[bool, Optional[str]]:
    """May the agent order on this call? Only if the step allows it, every line
    is priced within the price rule, and the PO would be approved automatically."""
    cfg = _ask_step(session)["config"]
    if not cfg.get("order_on_call"):
        return False, "ordering on the call is off"
    rfq = quote.request
    if rfq.status != "open":
        return False, "the request is already decided"
    rule = automation.step(session, "purchase.compare_quotes")["config"]
    approve = automation.step(session, "purchase.approve_po")
    prices = {ql.product_id: ql.price for ql in quote.lines}
    lines = [line for line in rfq.lines if line.product_id in prices]
    if len(lines) < len(rfq.lines) and len({q.supplier_id for q in rfq.quotes}) > 1:
        return False, "not every item was quoted; other suppliers may have the rest"
    value, changes = Decimal("0"), []
    for line in lines:
        price = prices[line.product_id]
        last = triggers._last_paid(session, line.product_id)
        if last:
            change = float((price - last) / last * 100)
            changes.append(change)
            if rule.get("max_over_last_percent") is not None and change > float(rule["max_over_last_percent"]):
                return False, "{} is {:.0f}% above the last price".format(line.product.name, change)
        value += line.quantity * price
    if approve.get("mode") == "auto":
        return True, None
    if approve.get("mode") == "limits":
        broken = automation.within_limits(approve, {"po_value": float(value), "price_change_percent": max(changes) if changes else 0})
        return (False, broken) if broken else (True, None)
    return False, "purchase orders need a person's approval"


def order_now(session: Session, quote_id: uuid.UUID, args: Dict[str, Any], call_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    """The supplier agreed on the call: place the purchase order with this quote."""
    from . import purchasing, tally_sync

    quote = session.get(SupplierQuote, quote_id)
    if quote is None:
        return {"error": "No price request on this call."}
    ok, why = can_order_now(session, quote)
    if not ok:
        return {"ordered": False, "say": "Do not confirm the order: the team will confirm it shortly ({}).".format(why)}
    rfq = quote.request
    prices = {ql.product_id: ql.price for ql in quote.lines}
    lines = [line for line in rfq.lines if line.product_id in prices]
    expected = None
    when = str(args.get("delivery_date") or "").strip()
    if when:
        try:
            expected = datetime.combine(date.fromisoformat(when), datetime.min.time(), tzinfo=timezone.utc)
        except ValueError:
            expected = None
    if expected is None and quote.delivery_days is not None:
        expected = _now() + timedelta(days=quote.delivery_days)
    po = purchasing.create_purchase_order(
        session, quote.supplier_id, [{"product_id": line.product_id, "quantity_ordered": str(line.quantity), "unit_cost": str(prices[line.product_id])} for line in lines],
        expected_delivery_date=expected, notes="Ordered on the phone by the purchasing agent ({}).".format(rfq.number), confirm=True)
    po.confirm_status, po.confirmed_at = "confirmed", _now()
    po.confirm_note = "Agreed on the call{}.".format(". " + str(args.get("notes")) if args.get("notes") else "")
    rfq.chosen_quote_id, rfq.purchase_order_id, rfq.status = quote.id, po.id, "ordered"
    rfq.decision = "Ordered on the call from {}.".format(quote.supplier.name)
    session.commit()
    triggers.event(session, "purchase.place_po", "placed", "done", "{} placed on the phone with {}".format(po.po_number, quote.supplier.name),
                   party=("supplier", quote.supplier_id), subject=("purchase_order", po.id))
    for sync_id in tally_sync.queue_purchase_order(session, po):
        tally_sync.process(sync_id)
    triggers.send_po(session, po.id)  # the written copy on WhatsApp
    return {"ordered": True, "po_number": po.po_number,
            "say": "Confirm: order {} placed; we will send it on WhatsApp too. Thank them.".format(po.po_number)}


def cannot_quote(session: Session, quote_id: uuid.UUID, reason: str) -> Dict[str, Any]:
    quote = session.get(SupplierQuote, quote_id)
    if quote is None:
        return {"error": "No price request on this call."}
    quote.status, quote.replied_at, quote.channel = "declined", _now(), "call"
    quote.reply = "On the call: cannot supply. {}".format(reason or "")
    session.commit()
    triggers.event(session, "purchase.read_reply", "declined", "done", "{} cannot supply {}".format(quote.supplier.name, quote.request.number),
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


# ---------------------------------------------------------------------------
# Confirming a placed order by phone
# ---------------------------------------------------------------------------


def queue_order_call(session: Session, po: PurchaseOrder) -> bool:
    """Mark a placed PO for a confirmation call, when the step asks for one."""
    step = automation.step(session, "purchase.send_po")
    if step.get("mode") == "off" or not step["config"].get("confirm_by_call") or not automation.allowed(step, "pai"):
        return False
    if po.status == PurchaseOrderStatus.DRAFT or po.confirm_status in ("confirmed", "to_call", "calling"):
        return False
    po.confirm_status = "to_call"
    session.commit()
    return True


def order_brief(session: Session, po_id: uuid.UUID) -> str:
    po = session.get(PurchaseOrder, po_id)
    if po is None:
        return ""
    lines = []
    for item in po.items:
        qty, unit, factor = triggers._in_unit(session, item.product, item.quantity_ordered)
        lines.append("{} {} {} at Rs {:,.2f} per {}".format(triggers._qty(qty), unit, item.product.name, float(item.unit_cost * factor), unit))
    when = " We need it by {}.".format(po.expected_delivery_date.astimezone(triggers._zone()).strftime("%d %B")) if po.expected_delivery_date else ""
    return "Purchase order {} to {}: {}.{}".format(po.po_number, po.supplier.name, "; ".join(lines), when)


def confirm_order(session: Session, po_id: uuid.UUID, args: Dict[str, Any]) -> Dict[str, Any]:
    po = session.get(PurchaseOrder, po_id)
    if po is None:
        return {"error": "No purchase order on this call."}
    when = str(args.get("dispatch_date") or args.get("delivery_date") or "").strip()
    if when:
        try:
            po.expected_delivery_date = datetime.combine(date.fromisoformat(when), datetime.min.time(), tzinfo=timezone.utc)
        except ValueError:
            pass
    po.confirm_status, po.confirmed_at = "confirmed", _now()
    po.confirm_note = "Confirmed on the call{}{}".format(" for {}".format(when) if when else "", ". " + str(args.get("notes")) if args.get("notes") else ".")
    session.commit()
    triggers.event(session, "purchase.send_po", "confirmed", "done", "{} confirmed by {} on the phone".format(po.po_number, po.supplier.name),
                   party=("supplier", po.supplier_id), subject=("purchase_order", po.id))
    return {"ok": True, "say": "Thank them and end the call."}


def cannot_supply(session: Session, po_id: uuid.UUID, reason: str) -> Dict[str, Any]:
    from . import tasks

    po = session.get(PurchaseOrder, po_id)
    if po is None:
        return {"error": "No purchase order on this call."}
    po.confirm_status, po.confirm_note = "declined", "Supplier cannot supply: {}".format(reason or "no reason given")
    session.commit()
    tasks.create_task(session, title="{} cannot supply {}".format(po.supplier.name, po.po_number), notes=po.confirm_note,
                      priority="HIGH", source="automation", supplier_id=po.supplier_id, purchase_order_id=po.id)
    triggers.event(session, "purchase.send_po", "declined", "held", po.confirm_note, party=("supplier", po.supplier_id), subject=("purchase_order", po.id))
    return {"ok": True, "say": "Thank them; say the team will get back to them. End the call."}


def order_call_ended(session: Session, po_id: uuid.UUID, summary: str) -> None:
    po = session.get(PurchaseOrder, po_id)
    if po is None or po.confirm_status != "calling":
        return
    po.confirm_status = "to_call"
    po.confirm_note = ("Call: " + summary)[:2000] if summary else po.confirm_note
    session.commit()


def run_order_calls(session: Session) -> int:
    step = automation.step(session, "purchase.send_po")
    if step.get("mode") == "off" or not step["config"].get("confirm_by_call") or not automation.allowed(step, "pai"):
        return 0
    now = _now()
    tries = int(_ask_step(session)["config"].get("call_tries") or 2)
    for po in session.execute(select(PurchaseOrder).where(PurchaseOrder.confirm_status == "calling",
                                                          PurchaseOrder.confirm_last_call_at <= now - NO_ANSWER_AFTER)).scalars():
        po.confirm_status = "to_call"
    session.commit()
    if not triggers.in_window(_ask_step(session)["config"]):
        return 0
    placed = 0
    for po in session.execute(select(PurchaseOrder).where(PurchaseOrder.confirm_status == "to_call")).scalars().all():
        if placed >= CALLS_PER_TICK:
            break
        if po.confirm_last_call_at and now - po.confirm_last_call_at < RETRY_AFTER:
            continue
        if po.confirm_attempts >= tries or not po.supplier.phone:
            po.confirm_status = "no_answer"
            po.confirm_note = "No answer after {} calls; please confirm yourself.".format(po.confirm_attempts) if po.supplier.phone else "No phone number."
            session.commit()
            continue
        po.confirm_attempts += 1
        po.confirm_last_call_at = now
        try:
            _place(po.supplier.phone, "supplier_order", {"po": str(po.id)})
            po.confirm_status = "calling"
            placed += 1
        except Exception as exc:
            po.confirm_note = "Could not call: {}".format(exc)
        session.commit()
    return placed


def tick(session: Session) -> Dict[str, int]:
    return {"quote_calls": run_quote_calls(session), "order_calls": run_order_calls(session)}
