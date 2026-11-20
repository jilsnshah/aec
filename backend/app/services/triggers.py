"""The trigger engine: what starts the purchase and sales flows on its own,
and the steps that follow, each set in Settings -> Automation.

Purchase:
  Need detected (schedule + rules: customers short, below reorder point, low
  days of cover, weekly review) -> Ask suppliers (TAI on WhatsApp/email) ->
  Read replies -> Compare and pick -> Approve (limits) -> Place the PO ->
  Send the PO to the supplier -> Chase the delivery.

Sales:
  Reach out to customers (schedule + rules: dormant, due to reorder, quotes
  not converted, back in stock, chosen groups, slow stock; with audience
  filters, frequency caps and quiet hours) -> their replies come in as any
  message and go through the sales flow.
  After-sales follow-up: some time after delivery, ask how it went; a rating
  is recorded, a complaint becomes a task.

Every action is written to the activity log (AutomationEvent), which is also
what cool-downs and frequency caps are counted from.
"""
from __future__ import annotations

import logging
import math
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    AutomationEvent,
    AutomationState,
    Customer,
    CustomerDelivery,
    CustomerEnquiry,
    CustomerFeedback,
    EnquiryStatus,
    OrderStatus,
    Product,
    ProductUnit,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    SalesOrder,
    SalesOrderItem,
    Supplier,
    SupplierQuote,
    SupplierQuoteLine,
    SupplierQuoteRequest,
    SupplierQuoteRequestLine,
)
from . import automation

logger = logging.getLogger(__name__)
ZERO = Decimal("0")
EVERY = {"1h": 1, "2h": 2, "4h": 4, "6h": 6, "12h": 12, "1d": 24, "7d": 168}
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _zone() -> ZoneInfo:
    return ZoneInfo(get_settings().business_timezone)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clock(value: str, fallback: time) -> time:
    try:
        hours, minutes = (int(x) for x in (value or "").split(":")[:2])
        return time(hours, minutes)
    except ValueError:
        return fallback


def in_window(cfg: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """Inside the step's working days and hours (business time)?"""
    local = (now or _now()).astimezone(_zone())
    days = cfg.get("days")
    if days and WEEKDAYS[local.weekday()] not in days:
        return False
    start = _clock(cfg.get("window_start") or "00:00", time(0, 0))
    end = _clock(cfg.get("window_end") or "23:59", time(23, 59))
    return start <= local.time() <= end


def _state(session: Session, key: str) -> AutomationState:
    row = session.get(AutomationState, key)
    if row is None:
        row = AutomationState(key=key, data={})
        session.add(row)
        session.flush()
    return row


def due(session: Session, key: str, schedule: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """Is a scheduled trigger due: in its window and its interval passed?"""
    now = now or _now()
    if not in_window(schedule, now):
        return False
    row = _state(session, key)
    hours = EVERY.get(schedule.get("every") or "1d", 24)
    return row.last_run_at is None or now - row.last_run_at >= timedelta(hours=hours) - timedelta(minutes=2)


def _mark(session: Session, key: str) -> None:
    _state(session, key).last_run_at = _now()


def event(session: Session, step: str, kind: str, status: str = "done", summary: Optional[str] = None, party: Tuple[Optional[str], Any] = (None, None),
          subject: Tuple[Optional[str], Any] = (None, None), detail: Optional[Dict[str, Any]] = None) -> AutomationEvent:
    row = AutomationEvent(step=step, kind=kind, status=status, summary=(summary or "")[:2000] or None, party_type=party[0], party_id=party[1],
                          subject_type=subject[0], subject_id=subject[1], detail=detail)
    session.add(row)
    session.flush()
    return row


def _recent(session: Session, step: str, since: datetime, party_type: Optional[str] = None, party_id: Any = None, subject_id: Any = None,
            statuses: Iterable[str] = ("done", "sent", "held", "awaiting_reply", "replied")) -> int:
    stmt = select(func.count(AutomationEvent.id)).where(AutomationEvent.step == step, AutomationEvent.created_at >= since,
                                                        AutomationEvent.status.in_(list(statuses)))
    if party_type:
        stmt = stmt.where(AutomationEvent.party_type == party_type, AutomationEvent.party_id == party_id)
    if subject_id is not None:
        stmt = stmt.where(AutomationEvent.subject_id == subject_id)
    return session.execute(stmt).scalar_one()


def _business(session: Session) -> str:
    from . import integration_settings as settings_service

    return settings_service.get(session, settings_service.TALLY).config.get("seller_name") or "us"


def _send(session: Session, step_data: Dict[str, Any], to_phone: Optional[str], to_email: Optional[str], text: str, *,
          subject: Optional[str] = None, customer_id=None, purpose: str = "") -> Tuple[str, Optional[str]]:
    """Send as the step allows: TAI on WhatsApp (or email), held for approval
    when the step needs a person. Returns (status, channel)."""
    from . import outbox

    actors = step_data.get("actors") or []
    channels = step_data.get("channels") or ["whatsapp"]
    hold = step_data.get("mode") == "approval"
    if "tai" not in actors:
        return "skipped", None
    if to_phone and "whatsapp" in channels:
        message = outbox.queue(session, "whatsapp", to_phone, text, hold=hold, author="tai", customer_id=customer_id)
        return ("held" if message.status == "pending_approval" else "sent" if message.status == "sent" else "failed"), "whatsapp"
    if to_email and "email" in channels:
        message = outbox.queue(session, "email", to_email, text, hold=hold, author="tai", subject=subject, customer_id=customer_id)
        return ("held" if message.status == "pending_approval" else "sent" if message.status == "sent" else "failed"), "email"
    return "skipped", None


def _qty(value: Decimal) -> str:
    value = Decimal(value)
    return "{:f}".format(value.normalize()) if value == value.to_integral() else "{:f}".format(value.quantize(Decimal("0.01")).normalize())


def _in_unit(session: Session, product: Product, base_qty: Decimal, purpose: str = "purchase") -> Tuple[Decimal, str, Decimal]:
    """A base quantity shown in the product's usual purchase (or sales) unit."""
    name = product.purchase_unit if purpose == "purchase" else product.sales_unit
    if name:
        unit = session.execute(select(ProductUnit).where(ProductUnit.product_id == product.id, ProductUnit.name == name)).scalar_one_or_none()
        if unit is not None and unit.factor:
            return Decimal(base_qty) / Decimal(unit.factor), unit.name, Decimal(unit.factor)
    return Decimal(base_qty), product.unit_of_measure, Decimal("1")


# ---------------------------------------------------------------------------
# Purchase: need detected
# ---------------------------------------------------------------------------


def purchase_needs(session: Session, cfg: Dict[str, Any], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Products to buy now under the step's rules, with how much and why."""
    from . import reservations
    from .common import pending_quantity_map

    now = now or _now()
    rules, scope, qty_cfg = cfg["rules"], cfg["scope"], cfg["quantity"]
    stmt = select(Product).where(Product.is_active.is_(True))
    if scope.get("categories"):
        stmt = stmt.where(Product.category.in_(scope["categories"]))
    if scope.get("suppliers"):
        stmt = stmt.where(Product.preferred_supplier_id.in_([uuid.UUID(s) for s in scope["suppliers"]]))
    products = session.execute(stmt).scalars().all()
    if not products:
        return []
    ids = [p.id for p in products]
    pending = pending_quantity_map(session, ids)
    reserved = reservations.reserved_map(session, ids)
    on_order = dict(session.execute(
        select(PurchaseOrderItem.product_id, func.sum(PurchaseOrderItem.quantity_ordered - PurchaseOrderItem.quantity_received))
        .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .where(PurchaseOrderItem.product_id.in_(ids), PurchaseOrder.status.in_((PurchaseOrderStatus.ORDERED, PurchaseOrderStatus.PARTIALLY_RECEIVED)))
        .group_by(PurchaseOrderItem.product_id)).all())
    unallocated = dict(session.execute(
        select(SalesOrderItem.product_id, func.sum(SalesOrderItem.quantity_ordered - SalesOrderItem.quantity_fulfilled - SalesOrderItem.quantity_cancelled
                                                    - SalesOrderItem.quantity_reserved - SalesOrderItem.quantity_incoming))
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .where(SalesOrderItem.product_id.in_(ids), SalesOrder.status.in_((OrderStatus.PENDING, OrderStatus.PARTIALLY_FULFILLED)))
        .group_by(SalesOrderItem.product_id)).all())
    lookback = int(max(rules["reorder_point"].get("lookback_days") or 30, rules["days_of_cover"].get("lookback_days") or 30, 7))
    sold = dict(session.execute(
        select(SalesOrderItem.product_id, func.sum(SalesOrderItem.quantity_ordered - SalesOrderItem.quantity_cancelled))
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .where(SalesOrderItem.product_id.in_(ids), SalesOrder.status != OrderStatus.CANCELLED, SalesOrder.created_at >= now - timedelta(days=lookback))
        .group_by(SalesOrderItem.product_id)).all())
    cooldown = timedelta(hours=float(scope.get("cooldown_hours") or 0))
    review_today = rules["fixed_review"]["enabled"] and WEEKDAYS[now.astimezone(_zone()).weekday()] == rules["fixed_review"].get("day")
    needs = []
    for p in products:
        if cooldown and _recent(session, "purchase.need_detected", now - cooldown, subject_id=p.id, statuses=("done", "held", "sent")):
            continue
        rate = Decimal(sold.get(p.id) or 0) / Decimal(lookback)
        lead = Decimal(p.lead_time_days or (p.preferred_supplier.lead_time_days if p.preferred_supplier and p.preferred_supplier.lead_time_days else 7))
        short = max(Decimal(unallocated.get(p.id) or 0), ZERO)
        incoming = Decimal(on_order.get(p.id) or 0) if scope.get("skip_covered", True) else ZERO
        stock = Decimal(p.physical_stock) + incoming - Decimal(pending.get(p.id) or 0)
        reorder_point = Decimal(p.reorder_level or 0) + rate * (lead + Decimal(str(rules["reorder_point"].get("safety_days") or 0)))
        why = []
        if rules["shortage"]["enabled"] and short > Decimal(str(rules["shortage"].get("min_quantity") or 0)) and (not scope.get("skip_covered", True) or stock < 0):
            why.append("customers short {}".format(_qty(short)))
        if rules["reorder_point"]["enabled"] and reorder_point > 0 and stock < reorder_point:
            why.append("below reorder point {}".format(_qty(reorder_point)))
        if rules["days_of_cover"]["enabled"] and rate > 0 and stock / rate < Decimal(str(rules["days_of_cover"].get("days") or 0)):
            why.append("{} days of cover left".format(_qty(max(stock / rate, ZERO))))
        if review_today and p.reorder_level and stock < Decimal(p.reorder_level) * 2:
            why.append("weekly review")
        if not why:
            continue
        method = qty_cfg.get("method")
        if method == "shortage_only":
            target = ZERO
        elif method == "up_to_reorder":
            target = reorder_point
        elif method == "up_to_max":
            target = max(Decimal(p.reorder_level or 0) * 2, reorder_point)
        else:
            target = max(reorder_point, rate * Decimal(str(qty_cfg.get("cover_days") or 15)) + Decimal(p.reorder_level or 0))
        quantity = max(target - stock, short if stock < 0 else ZERO, short if method == "shortage_only" else ZERO)
        if quantity <= 0:
            continue
        if qty_cfg.get("round_to_purchase_unit") and p.purchase_unit:
            _, _, factor = _in_unit(session, p, quantity)
            if factor > 1:
                quantity = Decimal(math.ceil(quantity / factor)) * factor
        if p.whole_units:
            quantity = Decimal(math.ceil(quantity))
        price = Decimal(p.last_purchase_price or 0)
        needs.append({"product": p, "quantity": quantity, "why": "; ".join(why), "value": quantity * price,
                      "supplier_id": p.preferred_supplier_id, "rule": "shortage" if why[0].startswith("customers") else "reorder"})
    minimum = Decimal(str(qty_cfg.get("min_value") or 0))
    if minimum and sum((n["value"] for n in needs), ZERO) < minimum:
        return []
    return needs


def run_purchase(session: Session, force: bool = False) -> Dict[str, Any]:
    """The 'Need detected' trigger: find needs and start what the step says."""
    from .common import next_document_number

    data = automation.step(session, "purchase.need_detected")
    if data.get("mode") == "off" and not force:
        return {"skipped": "off"}
    cfg = data["config"]
    if not force and not due(session, "purchase.need_detected", cfg["schedule"]):
        return {"skipped": "not due"}
    needs = purchase_needs(session, cfg)
    _mark(session, "purchase.need_detected")
    if not needs:
        session.commit()
        return {"needs": 0}
    then = cfg.get("then")
    for need in needs:
        event(session, "purchase.need_detected", need["rule"], "done", "{}: {} {} ({})".format(
            need["product"].name, _qty(need["quantity"]), need["product"].unit_of_measure, need["why"]), subject=("product", need["product"].id))
    if then == "task":
        from . import tasks

        session.commit()
        lines = "\n".join("- {} {} {} ({})".format(n["product"].name, _qty(n["quantity"]), n["product"].unit_of_measure, n["why"]) for n in needs)
        task = tasks.create_task(session, "Buy {} product{}".format(len(needs), "s" if len(needs) > 1 else ""), notes=lines, priority="HIGH",
                                 source="automation")
        return {"needs": len(needs), "task": str(task.id)}
    if then == "draft_po":
        from . import purchasing

        by_supplier: Dict[Any, List[Dict[str, Any]]] = {}
        for need in needs:
            if need["supplier_id"]:
                by_supplier.setdefault(need["supplier_id"], []).append(need)
        session.commit()
        made = []
        for supplier_id, group in by_supplier.items():
            po = purchasing.create_purchase_order(session, supplier_id, [{"product_id": n["product"].id, "quantity_ordered": str(n["quantity"]),
                                                                          "unit_cost": str(n["product"].last_purchase_price or 0)} for n in group],
                                                  notes="Drafted by automation: " + "; ".join(n["why"] for n in group))
            made.append(po.po_number)
        return {"needs": len(needs), "drafts": made}
    rfq = SupplierQuoteRequest(number=next_document_number(session, "rfq", "RFQ"), status="open", reason=needs[0]["rule"], created_by="system",
                               notes="; ".join("{}: {}".format(n["product"].name, n["why"]) for n in needs))
    for need in needs:
        rfq.lines.append(SupplierQuoteRequestLine(product_id=need["product"].id, quantity=need["quantity"], why=need["why"][:120]))
    session.add(rfq)
    session.commit()
    result = ask_suppliers(session, rfq.id)
    return {"needs": len(needs), "rfq": rfq.number, **result}


# ---------------------------------------------------------------------------
# Purchase: ask suppliers, read replies, compare, decide
# ---------------------------------------------------------------------------


def _candidates(session: Session, product: Product, who: str, how_many: int) -> List[Tuple[Supplier, str]]:
    found: List[Tuple[Supplier, str]] = []
    if product.preferred_supplier and product.preferred_supplier.is_active:
        found.append((product.preferred_supplier, "usual supplier"))
    if who == "preferred":
        return found
    history = session.execute(
        select(PurchaseOrder.supplier_id, func.count(PurchaseOrderItem.id), func.min(PurchaseOrderItem.unit_cost))
        .join(PurchaseOrderItem, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .where(PurchaseOrderItem.product_id == product.id, PurchaseOrder.status != PurchaseOrderStatus.CANCELLED)
        .group_by(PurchaseOrder.supplier_id).order_by(func.count(PurchaseOrderItem.id).desc())
    ).all()
    for supplier_id, _, _ in history:
        supplier = session.get(Supplier, supplier_id)
        if supplier and supplier.is_active and all(s.id != supplier.id for s, _ in found):
            found.append((supplier, "bought from before"))
    if who == "all_category" and product.category:
        rows = session.execute(
            select(PurchaseOrder.supplier_id).join(PurchaseOrderItem, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
            .join(Product, PurchaseOrderItem.product_id == Product.id).where(Product.category == product.category).distinct()
        ).scalars().all()
        for supplier_id in rows:
            supplier = session.get(Supplier, supplier_id)
            if supplier and supplier.is_active and all(s.id != supplier.id for s, _ in found):
                found.append((supplier, "sells {}".format(product.category)))
    return found if who == "all_category" else found[:max(1, int(how_many))]


def _lines_for(session: Session, rfq: SupplierQuoteRequest, supplier: Supplier) -> List[SupplierQuoteRequestLine]:
    data = automation.step(session, "purchase.ask_supplier")
    cfg = data["config"]
    return [line for line in rfq.lines if any(s.id == supplier.id for s, _ in _candidates(session, line.product, cfg["who"], cfg["how_many"]))]


def request_text(session: Session, rfq: SupplierQuoteRequest, supplier: Supplier) -> str:
    from . import agent_text

    items = []
    for n, line in enumerate(_lines_for(session, rfq, supplier) or list(rfq.lines), start=1):
        qty, unit, _ = _in_unit(session, line.product, line.quantity)
        items.append("{}. {} {} {}".format(n, _qty(qty), unit, line.product.name))
    fallback = ("Namaste {}, {} here. Request {}: please send your best rate (per unit, before GST) and how many days to deliver for: {}. "
                "You can reply here, e.g. \"340, 2 days\".".format(supplier.contact_person or supplier.name, _business(session), rfq.number, "; ".join(items)))
    return agent_text.write(session, "purchasing", "ask a supplier for their best rate per unit (before GST), GST, freight and delivery days for these items",
                            {"supplier": supplier.contact_person or supplier.name, "request_number": rfq.number, "items": items,
                             "needed_by": rfq.needed_by.astimezone(_zone()).strftime("%d %b") if rfq.needed_by else None},
                            fallback, must_keep=[rfq.number])


def ask_suppliers(session: Session, rfq_id: uuid.UUID) -> Dict[str, Any]:
    """Choose whom to ask for each line, and ask them (or buy on a running contract)."""
    from . import rate_contracts

    rfq = session.get(SupplierQuoteRequest, rfq_id)
    data = automation.step(session, "purchase.ask_supplier")
    cfg = data["config"]
    contract_lines = []
    if cfg.get("use_contract"):
        for line in list(rfq.lines):
            supplier = line.product.preferred_supplier
            hit = rate_contracts.supplier_rate(session, supplier.id, line.product_id, line.quantity) if supplier else None
            if hit is not None:
                contract_lines.append((line, supplier, hit))
    asked = 0
    wanted: Dict[uuid.UUID, Tuple[Supplier, str]] = {}
    contract_ids = {line.id for line, _, _ in contract_lines}
    for line in rfq.lines:
        if line.id in contract_ids:
            continue
        for supplier, why in _candidates(session, line.product, cfg["who"], cfg["how_many"]):
            wanted.setdefault(supplier.id, (supplier, why))
    for line, supplier, (rate, contract) in contract_lines:
        quote = next((q for q in rfq.quotes if q.supplier_id == supplier.id), None) or SupplierQuote(supplier_id=supplier.id, status="replied", source="rate contract")
        quote.status, quote.replied_at, quote.reply = "replied", _now(), "Rate contract {}".format(contract.number)
        quote.lines.append(SupplierQuoteLine(product_id=line.product_id, price=rate))
        if quote not in rfq.quotes:
            rfq.quotes.append(quote)
    rfq.reply_by = _now() + timedelta(hours=float(cfg.get("wait_hours") or 6))
    for supplier, why in wanted.values():
        quote = SupplierQuote(supplier_id=supplier.id, status="to_ask", source=why)
        rfq.quotes.append(quote)
    session.flush()
    window_ok = in_window(cfg)
    from . import supplier_calls

    by_phone = (cfg.get("how") == "call") and supplier_calls.calls_on(data)
    for quote in rfq.quotes:
        if quote.status != "to_ask":
            continue
        if not window_ok:
            continue  # asked on the next tick inside working hours
        if by_phone and quote.supplier.phone:
            continue  # the purchasing agent rings them (supplier_calls.run_quote_calls)
        status, channel = _send(session, data, quote.supplier.phone, quote.supplier.email, request_text(session, rfq, quote.supplier),
                                subject="Request for quotation {}".format(rfq.number))
        if status in ("sent", "held"):
            quote.status, quote.channel, quote.asked_at = "asked", channel, _now()
            asked += 1
        event(session, "purchase.ask_supplier", "rfq", status, "{} asked for {}".format(quote.supplier.name, rfq.number),
              party=("supplier", quote.supplier_id), subject=("rfq", rfq.id))
    session.commit()
    if all(q.status == "replied" for q in rfq.quotes) and rfq.quotes:
        decide(session, rfq.id)
    return {"asked": asked, "contract_lines": len(contract_lines)}


PRICE = re.compile(r"(?:rs\.?|₹|inr|@)?\s*(\d{1,6}(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:/-|rs|rupees|per|/)?", re.I)
DAYS = re.compile(r"(\d{1,2})\s*(?:days?|din|dino|working days)", re.I)
DECLINE = re.compile(r"\b(not available|no stock|nahi|nahin|na hai|sorry|can'?t|cannot|out of stock)\b", re.I)


def parse_supplier_reply(text: str, products: List[Product]) -> Dict[str, Any]:
    """Prices per product (in the unit asked), days to deliver, or a refusal."""
    text = text or ""
    if DECLINE.search(text) and not PRICE.search(re.sub(DAYS, " ", text)):
        return {"declined": True}
    days = None
    match = DAYS.search(text)
    if match:
        days = int(match.group(1))
    elif re.search(r"\b(today|aaj)\b", text, re.I):
        days = 0
    elif re.search(r"\b(tomorrow|kal)\b", text, re.I):
        days = 1
    stripped = DAYS.sub(" ", text)
    prices: Dict[uuid.UUID, Decimal] = {}
    if len(products) == 1:
        numbers = [Decimal(m.group(1).replace(",", "")) for m in PRICE.finditer(stripped)]
        numbers = [n for n in numbers if n > 0]
        if numbers:
            prices[products[0].id] = numbers[0]
    else:
        for segment in re.split(r"[\n;,]+", stripped):
            low = segment.lower()
            for product in products:
                words = [w for w in re.split(r"\W+", product.name.lower()) if len(w) >= 3]
                if words and any(w in low for w in words) and product.id not in prices:
                    numbers = [Decimal(m.group(1).replace(",", "")) for m in PRICE.finditer(re.sub(r"\d+\s*mm", " ", segment, flags=re.I))]
                    numbers = [n for n in numbers if n > 0]
                    if numbers:
                        prices[product.id] = numbers[-1]
    return {"prices": prices, "days": days}


def _ai_supplier_reply(session: Session, quote: SupplierQuote, text: str) -> Optional[str]:
    """The purchasing agent reads the reply with AI: records the quote, asks
    back for what is missing, orders straight away when allowed. None when
    AI is not available (the word-matching reader is used instead)."""
    from . import agent_text, supplier_calls

    rfq = quote.request
    supplier = quote.supplier
    items = []
    for n, line in enumerate(_lines_for(session, rfq, supplier) or list(rfq.lines), start=1):
        qty, unit, factor = _in_unit(session, line.product, line.quantity)
        last = _last_paid(session, line.product_id)
        items.append({"item": n, "product": line.product.name, "quantity": float(qty), "unit": unit,
                      "last_price": float(last * factor) if last else None})
    known = {"delivery_days": quote.delivery_days, "gst_included": quote.gst_included, "freight": float(quote.freight) if quote.freight is not None else None,
             "prices": [{"product": ql.product.name, "price_per_base_unit": float(ql.price)} for ql in quote.lines]} if quote.status == "replied" else {}
    read = agent_text.read_supplier_reply(session, items, text, known)
    if read is None:
        return None
    data = automation.step(session, "purchase.ask_supplier")
    quote.reply = ((quote.reply + "\n") if quote.reply else "") + text
    session.commit()
    if read["kind"] == "decline":
        supplier_calls.cannot_quote(session, quote.id, text[:300])
        return "rfq_reply"
    if read["lines"]:
        result = supplier_calls.record_quote(session, quote.id, {**read, "notes": "; ".join(read.get("missing") or [])}, channel="whatsapp")
        if result.get("can_order"):
            supplier_calls.order_now(session, quote.id, {}, channel="whatsapp")
            return "rfq_reply"
    elif quote.status == "replied":
        # Only new terms for a quote we have: keep the prices, update the rest.
        if read.get("delivery_days") is not None:
            quote.delivery_days = int(read["delivery_days"])
        if read.get("gst_included") is not None:
            quote.gst_included = bool(read["gst_included"])
        if read.get("freight") is not None:
            quote.freight = Decimal(str(read["freight"]))
        session.commit()
    ask_back = str(read.get("ask_back") or "").strip()
    waiting = False
    if ask_back and (read["kind"] in ("question", "other") or read.get("missing")):
        status, _ = _send(session, data, supplier.phone, supplier.email, ask_back)
        waiting = status in ("sent", "held")
        event(session, "purchase.read_reply", "asked_back", status, "Asked {}: {}".format(supplier.name, ask_back[:200]),
              party=("supplier", supplier.id), subject=("rfq", rfq.id))
    elif not read["lines"] and quote.status != "replied":
        event(session, "purchase.read_reply", "unclear", "held", "{} replied on {} but no price was given; a person should read it.".format(supplier.name, rfq.number),
              party=("supplier", supplier.id), subject=("rfq", rfq.id), detail={"reply": text[:500]})
    session.commit()
    compare_cfg = automation.step(session, "purchase.compare_quotes")["config"]
    session.refresh(rfq)
    if rfq.status == "open" and not waiting:  # when we asked back, wait for the answer (or the deadline)
        open_quotes = [q for q in rfq.quotes if q.status in ("asked", "to_ask", "calling")]
        if not open_quotes or (compare_cfg.get("decide_when") == "first_good" and quote.status == "replied"):
            decide(session, rfq.id)
    return "rfq_reply"


def on_supplier_message(session: Session, supplier: Supplier, text: str) -> Optional[str]:
    """A message from a supplier: the answer to a price request, or to a chase."""
    quote = session.execute(
        select(SupplierQuote).join(SupplierQuoteRequest, SupplierQuote.request_id == SupplierQuoteRequest.id)
        .where(SupplierQuote.supplier_id == supplier.id, SupplierQuote.status == "asked", SupplierQuoteRequest.status == "open")
        .order_by(SupplierQuote.asked_at.desc())
    ).scalars().first()
    if quote is None:
        # A later message about a quote already given (e.g. "GST extra"): update its terms.
        quote = session.execute(
            select(SupplierQuote).join(SupplierQuoteRequest, SupplierQuote.request_id == SupplierQuoteRequest.id)
            .where(SupplierQuote.supplier_id == supplier.id, SupplierQuote.status == "replied", SupplierQuoteRequest.status == "open",
                   SupplierQuote.replied_at >= _now() - timedelta(days=2))
            .order_by(SupplierQuote.replied_at.desc())
        ).scalars().first()
    if quote is not None:
        handled = _ai_supplier_reply(session, quote, text)
        if handled:
            return handled
    if quote is not None and quote.status == "replied":
        return "rfq_reply"
    if quote is not None:
        rfq = quote.request
        lines = _lines_for(session, rfq, supplier) or list(rfq.lines)
        parsed = parse_supplier_reply(text, [l.product for l in lines])
        quote.reply = ((quote.reply + "\n") if quote.reply else "") + text
        quote.replied_at = _now()
        if parsed.get("declined"):
            quote.status = "declined"
            event(session, "purchase.read_reply", "declined", "replied", "{} cannot supply ({})".format(supplier.name, rfq.number),
                  party=("supplier", supplier.id), subject=("rfq", rfq.id))
        elif parsed.get("prices"):
            for line in lines:
                if line.product_id in parsed["prices"]:
                    _, _, factor = _in_unit(session, line.product, line.quantity)
                    quote.lines.append(SupplierQuoteLine(product_id=line.product_id, price=(parsed["prices"][line.product_id] / factor).quantize(Decimal("0.0001"))))
            quote.delivery_days = parsed.get("days")
            quote.status = "replied"
            event(session, "purchase.read_reply", "quote", "replied", "{} quoted on {}".format(supplier.name, rfq.number),
                  party=("supplier", supplier.id), subject=("rfq", rfq.id), detail={"reply": text[:500]})
        else:
            event(session, "purchase.read_reply", "unclear", "held", "{} replied on {} but the price is not clear; a person should read it.".format(supplier.name, rfq.number),
                  party=("supplier", supplier.id), subject=("rfq", rfq.id), detail={"reply": text[:500]})
        session.commit()
        compare_cfg = automation.step(session, "purchase.compare_quotes")["config"]
        open_quotes = [q for q in rfq.quotes if q.status in ("asked", "to_ask")]
        if not open_quotes or (compare_cfg.get("decide_when") == "first_good" and quote.status == "replied"):
            decide(session, rfq.id)
        return "rfq_reply"
    return on_chase_reply(session, supplier, text)


def _last_paid(session: Session, product_id: uuid.UUID) -> Optional[Decimal]:
    product = session.get(Product, product_id)
    return Decimal(product.last_purchase_price) if product and product.last_purchase_price else None


def _supplier_score(session: Session, supplier_id: uuid.UUID) -> float:
    from . import insights

    try:
        row = next((r for r in insights.supplier_insights(session)["suppliers"] if r["supplier_id"] == supplier_id), None)
    except Exception:  # pragma: no cover
        row = None
    if not row:
        return 50.0
    return float((row.get("on_time_percent") or 50) * 0.5 + (row.get("fill_rate_percent") or 50) * 0.5)


def decide(session: Session, rfq_id: uuid.UUID) -> Dict[str, Any]:
    """Pick the best offer for each line and raise purchase orders (draft or
    placed, as the approval step allows)."""
    from . import purchasing

    rfq = session.get(SupplierQuoteRequest, rfq_id)
    if rfq.status != "open":
        return {"status": rfq.status}
    cfg = automation.step(session, "purchase.compare_quotes")["config"]
    approve = automation.step(session, "purchase.approve_po")
    picks: Dict[uuid.UUID, List[Tuple[SupplierQuoteRequestLine, Decimal]]] = {}
    notes = []
    for line in rfq.lines:
        offers = []
        for quote in rfq.quotes:
            if quote.status != "replied":
                continue
            price = next((ql.price for ql in quote.lines if ql.product_id == line.product_id), None)
            if price is None:
                continue
            last = _last_paid(session, line.product_id)
            if last and cfg.get("max_over_last_percent") and price > last * (1 + Decimal(str(cfg["max_over_last_percent"])) / 100):
                notes.append("{}: {} at {} is too far above the last price {}".format(line.product.name, quote.supplier.name, price, last))
                continue
            offers.append((quote, price))
        if not offers:
            notes.append("{}: no acceptable offer".format(line.product.name))
            continue
        low = min(p for _, p in offers)
        fastest = min((q.delivery_days if q.delivery_days is not None else 30) for q, _ in offers)
        best, best_score = None, -1.0
        for quote, price in offers:
            days = quote.delivery_days if quote.delivery_days is not None else 30
            if cfg["rule"] == "lowest_price":
                score = float(low / price)
            elif cfg["rule"] == "fastest":
                score = (fastest + 1) / (days + 1)
            else:
                score = (float(low / price) * cfg["weight_price"] + (fastest + 1) / (days + 1) * cfg["weight_delivery"]
                         + _supplier_score(session, quote.supplier_id) / 100 * cfg["weight_score"]) / max(cfg["weight_price"] + cfg["weight_delivery"] + cfg["weight_score"], 1)
            quote.score = Decimal(str(round(score * 100, 2)))
            if score > best_score:
                best, best_score = (quote, price), score
        picks.setdefault(best[0].supplier_id, []).append((line, best[1]))
        notes.append("{}: {} at {} per {}".format(line.product.name, best[0].supplier.name, best[1], line.product.unit_of_measure))
    rfq.decision = "\n".join(notes)
    if not picks:
        rfq.status = "decided"
        event(session, "purchase.compare_quotes", "no_offer", "held", "{}: no acceptable offer; a person must buy.".format(rfq.number), subject=("rfq", rfq.id))
        session.commit()
        return {"orders": []}
    rfq.status = "decided"
    session.commit()
    orders = []
    for supplier_id, lines in picks.items():
        value = sum((line.quantity * price for line, price in lines), ZERO)
        changes = []
        for line, price in lines:
            last = _last_paid(session, line.product_id)
            if last:
                changes.append(float((price - last) / last * 100))
        facts = {"po_value": float(value), "price_change_percent": max(changes) if changes else 0}
        broken = automation.within_limits(approve, facts) if approve.get("mode") == "limits" else None
        place = approve.get("mode") == "auto" or (approve.get("mode") == "limits" and not broken)
        po = purchasing.create_purchase_order(session, supplier_id, [{"product_id": line.product_id, "quantity_ordered": str(line.quantity), "unit_cost": str(price)}
                                                                     for line, price in lines],
                                              notes="From {} ({}).".format(rfq.number, "placed automatically" if place else "needs approval: " + (broken or "approval required")),
                                              confirm=place)
        orders.append(po.po_number)
        rfq.purchase_order_id = po.id
        event(session, "purchase.approve_po", "placed" if place else "approval", "done" if place else "held",
              "{} {} for {} (Rs {:,.0f}){}".format(po.po_number, "placed" if place else "drafted", session.get(Supplier, supplier_id).name, float(value),
                                                  "" if place else ": " + (broken or "needs approval")),
              party=("supplier", supplier_id), subject=("purchase_order", po.id))
        if place:
            from . import tally_sync

            for sync_id in tally_sync.queue_purchase_order(session, po):
                tally_sync.process(sync_id)
            send_po(session, po.id)
    rfq.status = "ordered"
    session.commit()
    return {"orders": orders}


def tick_rfqs(session: Session) -> int:
    """Ask the ones not yet asked, remind the quiet ones, decide when the wait is over."""
    cfg = automation.step(session, "purchase.ask_supplier")["config"]
    data = automation.step(session, "purchase.ask_supplier")
    done = 0
    for rfq in session.execute(select(SupplierQuoteRequest).where(SupplierQuoteRequest.status == "open")).scalars().all():
        if any(q.status == "to_ask" for q in rfq.quotes) and in_window(cfg):
            ask_suppliers(session, rfq.id)
        remind = timedelta(hours=float(cfg.get("remind_after_hours") or 0))
        for quote in rfq.quotes:
            if remind and quote.status == "asked" and quote.reminded_at is None and quote.asked_at and _now() - quote.asked_at >= remind and in_window(cfg):
                _send(session, data, quote.supplier.phone, quote.supplier.email, "Reminder for {}: {}".format(rfq.number, request_text(session, rfq, quote.supplier)))
                quote.reminded_at = _now()
        if rfq.reply_by and _now() >= rfq.reply_by:
            for quote in rfq.quotes:
                if quote.status in ("asked", "to_ask"):
                    quote.status = "no_reply"
            session.commit()
            decide(session, rfq.id)
            done += 1
    session.commit()
    return done


# ---------------------------------------------------------------------------
# Purchase: send the PO, chase the delivery
# ---------------------------------------------------------------------------


def po_text(session: Session, po: PurchaseOrder, template: Optional[str] = None) -> str:
    items = []
    for item in po.items:
        qty, unit, factor = _in_unit(session, item.product, item.quantity_ordered)
        items.append("{} {} {} @ Rs {:,.2f}".format(_qty(qty), unit, item.product.name, float(item.unit_cost * factor)))
    head = (template or "Purchase order {po}").replace("{po}", po.po_number)
    due_text = " Needed by {}.".format(po.expected_delivery_date.astimezone(_zone()).strftime("%d %b")) if po.expected_delivery_date else ""
    return "{} -- {}: {}.{}".format(head, _business(session), "; ".join(items), due_text)


def send_po(session: Session, po_id: uuid.UUID) -> Optional[str]:
    """The 'Send the PO to the supplier' step, when the PO is placed."""
    from . import supplier_calls

    placed_po = session.get(PurchaseOrder, po_id)
    if placed_po is not None:
        supplier_calls.queue_order_call(session, placed_po)
    data = automation.step(session, "purchase.send_po")
    if data.get("mode") != "auto" or data["config"].get("send_on") != "placed":
        return None
    po = session.get(PurchaseOrder, po_id)
    if po is None or po.status == PurchaseOrderStatus.DRAFT:
        return None
    if _recent(session, "purchase.send_po", _now() - timedelta(days=365), subject_id=po.id):
        return None
    text = po_text(session, po, data["config"].get("message"))
    from . import outbox

    status = "skipped"
    if po.supplier.phone:
        message = outbox.queue(session, "whatsapp", po.supplier.phone, text, hold=False, author="system")
        status = "sent" if message.status == "sent" else "failed"
    elif po.supplier.email:
        message = outbox.queue(session, "email", po.supplier.email, text, hold=False, author="system", subject="Purchase order {}".format(po.po_number))
        status = "sent" if message.status == "sent" else "failed"
    event(session, "purchase.send_po", "sent", status, "{} sent to {}".format(po.po_number, po.supplier.name) if status == "sent" else
          "{} not sent to {} ({})".format(po.po_number, po.supplier.name, "no phone or email" if status == "skipped" else "sending failed"),
          party=("supplier", po.supplier_id), subject=("purchase_order", po.id))
    session.commit()
    return status


def tick_chase(session: Session) -> int:
    """Confirm before the due date, ask on the day, ask again while late, then a task."""
    data = automation.step(session, "purchase.chase_delivery")
    if data.get("mode") == "off":
        return 0
    cfg = data["config"]
    if not in_window(cfg):
        return 0
    today = _now().astimezone(_zone()).date()
    sent = 0
    pos = session.execute(select(PurchaseOrder).where(PurchaseOrder.status.in_((PurchaseOrderStatus.ORDERED, PurchaseOrderStatus.PARTIALLY_RECEIVED)),
                                                      PurchaseOrder.expected_delivery_date.is_not(None))).scalars().all()
    for po in pos:
        due_day = po.expected_delivery_date.astimezone(_zone()).date()
        days_to_due = (due_day - today).days
        asked = session.execute(select(AutomationEvent).where(AutomationEvent.step == "purchase.chase_delivery", AutomationEvent.subject_id == po.id)
                                .order_by(AutomationEvent.created_at.desc())).scalars().all()
        reminders = [e for e in asked if e.kind == "reminder"]
        if any(e.created_at.astimezone(_zone()).date() == today for e in asked):
            continue
        kind = None
        if days_to_due == int(cfg.get("before_days") or 0) and days_to_due > 0 and not any(e.detail and e.detail.get("stage") == "before" for e in reminders):
            kind, stage, text = "reminder", "before", "Namaste, {} here. Our order {} is due on {}. Please confirm it will reach us on time.".format(
                _business(session), po.po_number, due_day.strftime("%d %b"))
        elif days_to_due == 0 and cfg.get("on_due_day") and not any(e.detail and e.detail.get("stage") == "due" for e in reminders):
            kind, stage, text = "reminder", "due", "Namaste, our order {} is due today. When will the vehicle reach us?".format(po.po_number)
        elif days_to_due < 0:
            late = [e for e in reminders if e.detail and e.detail.get("stage") == "late"]
            last = max((e.created_at for e in late), default=None)
            every = timedelta(days=float(cfg.get("overdue_every_days") or 1))
            if len(late) >= int(cfg.get("max_reminders") or 3):
                if cfg.get("escalate") and not any(e.kind == "escalated" for e in asked):
                    from . import tasks

                    session.commit()
                    tasks.create_task(session, "{} from {} is {} days late".format(po.po_number, po.supplier.name, -days_to_due),
                                      notes="Reminded {} times; no delivery yet.".format(len(late)), priority="HIGH", source="automation",
                                      purchase_order_id=po.id, supplier_id=po.supplier_id)
                    event(session, "purchase.chase_delivery", "escalated", "done", "{} late: task for the buyer".format(po.po_number),
                          party=("supplier", po.supplier_id), subject=("purchase_order", po.id))
                continue
            if last is None or _now() - last >= every:
                kind, stage, text = "reminder", "late", "Namaste, our order {} was due on {} and has not arrived. When will you send it?".format(
                    po.po_number, due_day.strftime("%d %b"))
        if not kind:
            continue
        status, _ = _send(session, data, po.supplier.phone, po.supplier.email, text, subject="Order {}".format(po.po_number))
        event(session, "purchase.chase_delivery", "reminder", "awaiting_reply" if status == "sent" else status, "{}: {}".format(po.po_number, stage),
              party=("supplier", po.supplier_id), subject=("purchase_order", po.id), detail={"stage": stage})
        sent += 1
    session.commit()
    return sent


def parse_date_reply(text: str, today: date) -> Optional[date]:
    text = (text or "").lower()
    if re.search(r"\b(today|aaj)\b", text):
        return today
    if re.search(r"\b(day after tomorrow|parso|parson)\b", text):
        return today + timedelta(days=2)
    if re.search(r"\b(tomorrow|kal)\b", text):
        return today + timedelta(days=1)
    match = re.search(r"(\d{1,2})\s*(?:days?|din)", text)
    if match:
        return today + timedelta(days=int(match.group(1)))
    match = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?\b", text)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        year = int(match.group(3)) if match.group(3) else today.year
        year = year + 2000 if year < 100 else year
        try:
            found = date(year, month, day)
            return found if found >= today - timedelta(days=1) else date(year + 1, month, day)
        except ValueError:
            return None
    return None


def on_chase_reply(session: Session, supplier: Supplier, text: str) -> Optional[str]:
    cfg = automation.step(session, "purchase.chase_delivery")["config"]
    asked = session.execute(select(AutomationEvent).where(
        AutomationEvent.step == "purchase.chase_delivery", AutomationEvent.party_id == supplier.id, AutomationEvent.status == "awaiting_reply",
        AutomationEvent.created_at >= _now() - timedelta(days=3)).order_by(AutomationEvent.created_at.desc())).scalars().first()
    if asked is None:
        return None
    po = session.get(PurchaseOrder, asked.subject_id)
    from . import agent_text

    today = _now().astimezone(_zone()).date()
    read = agent_text.read_date_reply(session, text, today.strftime("%A %d %B %Y"))
    found = None
    if read is not None:
        try:
            found = date.fromisoformat(str(read.get("date"))) if read.get("date") not in (None, "", "null") else None
        except ValueError:
            found = None
        if read.get("problem") and po is not None:
            from . import tasks

            tasks.create_task(session, "{}: {} says {}".format(po.po_number, supplier.name, str(read["problem"])[:120]), notes=text[:1000],
                              priority="HIGH", source="automation", supplier_id=supplier.id, purchase_order_id=po.id)
    else:
        found = parse_date_reply(text, today)
    asked.status = "replied"
    asked.detail = dict(asked.detail or {}, reply=text[:500])
    if found and cfg.get("update_date") and po is not None:
        po.expected_delivery_date = datetime.combine(found, time(18, 0), tzinfo=_zone())
        event(session, "purchase.chase_delivery", "new_date", "done", "{}: supplier says {}".format(po.po_number, found.strftime("%d %b")),
              party=("supplier", supplier.id), subject=("purchase_order", po.id))
    session.commit()
    return "chase_reply"


# ---------------------------------------------------------------------------
# Sales: reach out to customers
# ---------------------------------------------------------------------------


def outreach_candidates(session: Session, cfg: Dict[str, Any], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Customers to contact under the step's rules and filters, with why."""
    from . import finance, groups

    now = now or _now()
    rules, audience = cfg["rules"], cfg["audience"]
    customers = {c.id: c for c in session.execute(select(Customer).where(Customer.is_active.is_(True))).scalars()}
    if not customers:
        return []
    figures = groups.metrics(session, list(customers))
    orders = session.execute(select(SalesOrder.customer_id, SalesOrder.created_at).where(SalesOrder.status != OrderStatus.CANCELLED)
                             .order_by(SalesOrder.created_at)).all()
    history: Dict[uuid.UUID, List[datetime]] = {}
    for customer_id, created in orders:
        history.setdefault(customer_id, []).append(created)
    found: Dict[uuid.UUID, List[str]] = {}

    def add(customer_id, why):
        if customer_id in customers:
            found.setdefault(customer_id, []).append(why)

    if rules["dormant"]["enabled"]:
        for cid, dates in history.items():
            if len(dates) >= int(rules["dormant"].get("min_orders") or 1) and now - dates[-1] >= timedelta(days=float(rules["dormant"].get("days") or 60)):
                add(cid, "dormant")
    if rules["reorder_due"]["enabled"]:
        for cid, dates in history.items():
            if len(dates) >= 3:
                gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
                if gaps:
                    usual = sorted(gaps)[len(gaps) // 2]
                    if (now - dates[-1]).days > usual * (1 + float(rules["reorder_due"].get("grace_percent") or 0) / 100):
                        add(cid, "reorder_due")
    if rules["quote_followup"]["enabled"]:
        cutoff = now - timedelta(days=float(rules["quote_followup"].get("days") or 2))
        for enquiry in session.execute(select(CustomerEnquiry).where(CustomerEnquiry.status == EnquiryStatus.OPEN, CustomerEnquiry.customer_id.is_not(None),
                                                                     CustomerEnquiry.created_at <= cutoff, CustomerEnquiry.created_at >= cutoff - timedelta(days=30))).scalars():
            add(enquiry.customer_id, "quote_followup:{}".format(enquiry.enquiry_number))
    if rules["back_in_stock"]["enabled"]:
        from ..models import StockCostLayer

        since = now - timedelta(days=float(rules["back_in_stock"].get("days") or 2))
        arrived = set(session.execute(select(StockCostLayer.product_id).where(StockCostLayer.created_at >= since)).scalars())
        if arrived:
            for cid, pid in session.execute(select(SalesOrder.customer_id, SalesOrderItem.product_id).join(SalesOrderItem, SalesOrderItem.order_id == SalesOrder.id)
                                            .where(SalesOrderItem.product_id.in_(arrived)).distinct()).all():
                add(cid, "back_in_stock")
    if rules["group_members"]["enabled"] and rules["group_members"].get("groups"):
        from ..models import CustomerGroupMember

        for (cid,) in session.execute(select(CustomerGroupMember.customer_id).where(
                CustomerGroupMember.group_id.in_([uuid.UUID(g) for g in rules["group_members"]["groups"]]), CustomerGroupMember.source != "excluded")).all():
            add(cid, "group")
    if rules["clear_stock"]["enabled"]:
        for cid in list(history):
            add(cid, "clear_stock")
    skip_groups = set()
    if audience.get("skip_groups"):
        from ..models import CustomerGroupMember

        skip_groups = set(session.execute(select(CustomerGroupMember.customer_id).where(
            CustomerGroupMember.group_id.in_([uuid.UUID(g) for g in audience["skip_groups"]]), CustomerGroupMember.source != "excluded")).scalars())
    out = []
    for cid, why in found.items():
        customer = customers[cid]
        figure = figures.get(cid, {})
        if cid in skip_groups or (audience.get("skip_segments") and figure.get("segment") in audience["skip_segments"]):
            continue
        if audience.get("min_spend") and float(figure.get("spend_12m") or 0) < float(audience["min_spend"]):
            continue
        if audience.get("skip_overdue_days") and float(figure.get("oldest_overdue_days") or 0) > float(audience["skip_overdue_days"]):
            continue
        if not customer.phone:
            continue
        out.append({"customer": customer, "why": why})
    return out


def outreach_text(session: Session, customer: Customer, why: List[str], cfg: Dict[str, Any]) -> str:
    from . import pricelists, reservations

    offer = cfg["offer"]
    quote = next((w.split(":", 1)[1] for w in why if w.startswith("quote_followup:")), None)
    name = customer.name.split()[0] if customer.name else ""
    if quote:
        from . import agent_text

        fallback = "Namaste {}, {} here. Did you have a chance to look at our quotation {}? Prices are held for now and stock is available. Reply to confirm or ask anything.".format(
            name, _business(session), quote)
        return agent_text.write(session, "outreach", "follow up on a quotation the customer has not answered", {"customer": name, "quotation": quote},
                                fallback, must_keep=[quote])
    if offer["pitch"] == "their_products":
        rows = session.execute(select(SalesOrderItem.product_id, func.sum(SalesOrderItem.quantity_ordered)).join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
                               .where(SalesOrder.customer_id == customer.id).group_by(SalesOrderItem.product_id)
                               .order_by(func.sum(SalesOrderItem.quantity_ordered).desc()).limit(5)).all()
        product_ids = [r[0] for r in rows]
    else:
        product_ids = [p.id for p in session.execute(select(Product).where(Product.is_active.is_(True), Product.physical_stock > 0)
                                                     .order_by(Product.physical_stock.desc()).limit(5)).scalars()]
    reserved = reservations.reserved_map(session, product_ids) if product_ids else {}
    products = [p for p in (session.get(Product, i) for i in product_ids) if p is not None and p.physical_stock - reserved.get(p.id, ZERO) > 0][:3]
    pieces = []
    if products:
        prices = {l["product_id"]: l for l in pricelists.resolve(session, customer.id, [{"product_id": p.id, "quantity": "1"} for p in products])["lines"]}
        for p in products:
            if offer.get("with_prices") and p.id in prices:
                _, unit, factor = _in_unit(session, p, Decimal("1"), "sales")
                pieces.append("{} at Rs {:,.0f}/{}".format(p.name, prices[p.id]["net_price"] * float(factor), unit))
            else:
                pieces.append(p.name)
    opener = "it has been a while" if "dormant" in why else "you may be due for your next order" if "reorder_due" in why else "good news"
    stock = (" In stock now: " + ", ".join(pieces) + ".") if pieces else ""
    fallback = "Namaste {}, {} here -- {}.{} Reply with what you need and we will send it.".format(name, _business(session), opener, stock)
    from . import agent_text

    reason = {"dormant": "they have not ordered for a while", "reorder_due": "they are usually due to reorder about now"}
    return agent_text.write(session, "outreach", "invite a customer to order again: {}".format("; ".join(reason.get(w, w) for w in why if not w.startswith("quote_followup")) or "share what is in stock"),
                            {"customer": name, "in_stock_with_prices": pieces}, fallback)


def run_outreach(session: Session, force: bool = False) -> Dict[str, Any]:
    from ..voice import outbound

    data = automation.step(session, "sales.trigger_outreach")
    if data.get("mode") == "off" and not force:
        return {"skipped": "off"}
    cfg = data["config"]
    if not force and not due(session, "sales.trigger_outreach", cfg["schedule"]):
        return {"skipped": "not due"}
    now = _now()
    _mark(session, "sales.trigger_outreach")
    candidates = outreach_candidates(session, cfg, now)
    caps = cfg["caps"]
    sent_today = _recent(session, "sales.trigger_outreach", now - timedelta(hours=24), statuses=("sent", "held"))
    room = max(0, int(caps.get("max_per_day") or 0) - sent_today)
    contacted = 0
    for item in candidates:
        if contacted >= room:
            break
        customer = item["customer"]
        if _recent(session, "sales.trigger_outreach", now - timedelta(days=float(caps.get("once_every_days") or 14)), "customer", customer.id,
                   statuses=("sent", "held")):
            continue
        text = outreach_text(session, customer, item["why"], cfg)
        if "pai" in (data.get("actors") or []) and "call" in (data.get("channels") or []) and data.get("mode") != "approval":
            try:
                outbound.place_call(customer.phone, "pitch")
                status = "sent"
            except Exception as exc:
                status = "failed"
                text = "Call failed: {}".format(exc)
        else:
            status, _ = _send(session, data, customer.phone, customer.email, text, customer_id=customer.id)
        event(session, "sales.trigger_outreach", item["why"][0].split(":")[0], status, text, party=("customer", customer.id),
              detail={"rules": item["why"]})
        if status in ("sent", "held"):
            contacted += 1
    session.commit()
    return {"candidates": len(candidates), "contacted": contacted}


# ---------------------------------------------------------------------------
# Sales: after-sales follow-up
# ---------------------------------------------------------------------------


def run_after_sales(session: Session, force: bool = False) -> Dict[str, Any]:
    data = automation.step(session, "sales.after_sales")
    if data.get("mode") == "off" and not force:
        return {"skipped": "off"}
    cfg = data["config"]
    if not force and not in_window(cfg):
        return {"skipped": "outside hours"}
    now = _now()
    delay = timedelta(hours=float(cfg.get("delay_hours") or 24))
    deliveries = session.execute(select(CustomerDelivery).where(CustomerDelivery.created_at <= now - delay,
                                                                CustomerDelivery.created_at >= now - delay - timedelta(days=7))).scalars().all()
    asked = 0
    for delivery in deliveries:
        if _recent(session, "sales.after_sales", now - timedelta(days=60), subject_id=delivery.id, statuses=("sent", "held", "awaiting_reply", "replied", "skipped")):
            continue
        customer = delivery.customer
        order = delivery.sales_order
        value = sum((float(l.quantity * l.order_item.unit_price_net) for l in delivery.items), 0.0)
        if cfg.get("who") == "first_orders":
            count = session.execute(select(func.count(SalesOrder.id)).where(SalesOrder.customer_id == customer.id, SalesOrder.status != OrderStatus.CANCELLED)).scalar_one()
            if count > 1:
                continue
        if cfg.get("who") == "big" and value < float(cfg.get("min_value") or 0):
            continue
        if _recent(session, "sales.after_sales", now - timedelta(days=float(cfg.get("skip_days") or 0)), "customer", customer.id,
                   statuses=("sent", "held", "awaiting_reply", "replied")):
            event(session, "sales.after_sales", "skipped", "skipped", "{}: asked recently".format(delivery.delivery_number),
                  party=("customer", customer.id), subject=("delivery", delivery.id))
            continue
        if not customer.phone:
            continue
        if cfg.get("how") == "call" and automation.allowed(data, "pai"):
            from . import customer_agents

            task = customer_agents.care_call(session, delivery, cfg)
            event(session, "sales.after_sales", "call", "awaiting_reply" if task else "skipped",
                  "Customer care agent will call {} about {}".format(customer.name, delivery.delivery_number) if task else "{}: a call is already planned".format(customer.name),
                  party=("customer", customer.id), subject=("delivery", delivery.id), detail={"order_id": str(order.id)})
            asked += 1 if task else 0
            continue
        from . import agent_text

        rating = " How would you rate it, 1 (poor) to 5 (excellent)?" if cfg.get("ask_rating") else ""
        fallback = "Namaste {}, {} here. Your delivery {} (order {}) should have reached you. Was everything right -- quantity, quality, on time?{} Reply here if anything was wrong and we will sort it out.".format(
            customer.name.split()[0], _business(session), delivery.delivery_number, order.order_number, rating)
        text = agent_text.write(session, "care", "check that a delivery arrived right (quantity, quality, on time){}".format("; ask for a rating from 1 to 5" if cfg.get("ask_rating") else ""),
                                {"customer": customer.name.split()[0], "delivery": delivery.delivery_number, "order": order.order_number,
                                 "items": ["{} {}".format(_qty(l.quantity), l.order_item.product.name) for l in delivery.items[:5]]},
                                fallback, must_keep=[delivery.delivery_number])
        status, _ = _send(session, data, customer.phone, customer.email, text, customer_id=customer.id)
        event(session, "sales.after_sales", "asked", "awaiting_reply" if status == "sent" else status, text, party=("customer", customer.id),
              subject=("delivery", delivery.id), detail={"order_id": str(order.id)})
        asked += 1
    session.commit()
    return {"asked": asked}


def on_customer_message(session: Session, customer: Customer, text: str) -> Optional[str]:
    """A customer's reply to the after-sales question: a rating and/or a complaint."""
    asked = session.execute(select(AutomationEvent).where(
        AutomationEvent.step == "sales.after_sales", AutomationEvent.party_id == customer.id, AutomationEvent.status == "awaiting_reply",
        AutomationEvent.created_at >= _now() - timedelta(days=4)).order_by(AutomationEvent.created_at.desc())).scalars().first()
    if asked is None:
        return None
    cfg = automation.step(session, "sales.after_sales")["config"]
    from . import agent_text, customer_agents

    read = agent_text.read_feedback(session, text)
    if read is not None:
        if not read.get("answer"):
            return None  # not an answer to us: the Sales agent handles it
        rating = read.get("rating") if isinstance(read.get("rating"), int) and 1 <= read["rating"] <= 5 else None
        complaint = bool(read.get("complaint")) or (rating is not None and rating <= int(cfg.get("low_rating") or 2))
    else:
        low = (text or "").lower()
        match = re.search(r"\b([1-5])\b(?:\s*/\s*5)?", low) if len(low) < 120 else None
        rating = int(match.group(1)) if match else None
        words = [w.strip().lower() for w in (cfg.get("complaint_words") or "").split(",") if w.strip()]
        complaint = any(re.search(r"\b{}\b".format(re.escape(w)), low) for w in words) or (rating is not None and rating <= int(cfg.get("low_rating") or 2))
        positive = re.search(r"\b(ok|okay|good|fine|thanks|thank you|received|all good|perfect|badhiya|sab theek|mil gaya)\b", low)
        if rating is None and not complaint and not positive:
            return None  # not an answer to us: let TAI handle it
    delivery = session.get(CustomerDelivery, asked.subject_id)
    asked.status = "replied"
    asked.detail = dict(asked.detail or {}, rating=rating, complaint=bool(complaint))
    customer_agents.save_feedback(session, customer, asked.subject_id, rating, text, bool(complaint),
                                  priority="HIGH" if cfg.get("complaint_priority") == "high" else "NORMAL")
    from . import outbox

    if complaint:
        outbox.queue(session, "whatsapp", customer.phone, "Sorry about that. We have noted it and someone from our team will call you shortly.", hold=False, author="tai",
                     customer_id=customer.id)
    else:
        outbox.queue(session, "whatsapp", customer.phone, "Thank you! Glad it went well. Message us any time you need more.", hold=False, author="tai", customer_id=customer.id)
    event(session, "sales.after_sales", "complaint" if complaint else "rating", "done",
          "{}: {}{}".format(customer.name, "rated {}/5".format(rating) if rating else "replied", "; complaint -> task" if complaint else ""),
          party=("customer", customer.id), subject=("delivery", asked.subject_id))
    session.commit()
    return "feedback"


# ---------------------------------------------------------------------------
# Follow-up calls by PAI
# ---------------------------------------------------------------------------

#: An unanswered call is tried this many times, this far apart.
CALL_TRIES = 3
RETRY_AFTER = timedelta(minutes=30)
NO_ANSWER_AFTER = timedelta(minutes=15)


def run_ai_calls(session: Session, force: bool = False) -> Dict[str, Any]:
    """Follow-ups given to PAI: ring at their time and follow their instructions."""
    from ..models import Task, TaskStatus
    from ..voice import outbound
    from . import tasks as task_service

    now = _now()
    placed = 0
    # Calls that never connected (no answer, busy): try again, then hand back.
    for task in session.execute(select(Task).where(Task.doer == "pai", Task.ai_status == "calling", Task.status == TaskStatus.OPEN,
                                                   Task.last_call_at <= now - NO_ANSWER_AFTER)).scalars():
        if task.call_attempts < CALL_TRIES:
            task.ai_status, task.due_at = "scheduled", now + RETRY_AFTER
            task.ai_result = "No answer (try {} of {}); calling again at {}.".format(task.call_attempts, CALL_TRIES, task.due_at.astimezone(_zone()).strftime("%I:%M %p"))
        else:
            task.ai_status = "no_answer"
            task.ai_result = "No answer after {} tries. Please call yourself.".format(task.call_attempts)
            task.doer = "person"
    session.commit()
    due_tasks = session.execute(select(Task).where(Task.doer == "pai", Task.status == TaskStatus.OPEN, Task.ai_status == "scheduled",
                                                   Task.due_at <= now)).scalars().all()
    for task in due_tasks:
        phone = task_service.phone_for(session, task)
        task.call_attempts += 1
        task.last_call_at = now
        if not phone:
            task.ai_status, task.ai_result = "failed", "No number to ring."
            continue
        try:
            outbound.place_call(phone, "task", {"task": str(task.id)})
            task.ai_status = "calling"
            placed += 1
        except Exception as exc:
            task.ai_status, task.ai_result = "failed", "PAI could not call: {}".format(exc)
        event(session, "tasks.pai_call", "call", "sent" if task.ai_status == "calling" else "failed", "{}: {}".format(task.title, phone),
              subject=("task", task.id))
    session.commit()
    return {"placed": placed}


def call_brief(session: Session, task_id: uuid.UUID) -> str:
    """What PAI must do on a follow-up call."""
    from ..models import Task

    task = session.get(Task, task_id)
    if task is None:
        return ""
    who = task.customer.name if task.customer else task.supplier.name if task.supplier else ""
    context = []
    if task.sales_order:
        context.append("order {}".format(task.sales_order.order_number))
    if task.enquiry:
        context.append("quotation {}".format(task.enquiry.enquiry_number))
    if task.purchase_order:
        context.append("purchase order {}".format(task.purchase_order.po_number))
    return "Follow-up: {}.{}{} Instructions: {}".format(task.title, " Calling {}.".format(who) if who else "",
                                                       " About {}.".format(", ".join(context)) if context else "",
                                                       task.instructions or task.notes or "Find out how we can help and note it.")


def finish_call(session: Session, task_id: uuid.UUID, outcome: str, summary: str, call_id: Optional[uuid.UUID] = None) -> None:
    """PAI's report at the end of a follow-up call."""
    from ..models import Task, TaskStatus

    task = session.get(Task, task_id)
    if task is None:
        return
    task.ai_result = summary[:4000]
    task.phone_call_id = call_id or task.phone_call_id
    if outcome == "done":
        task.ai_status, task.status, task.completed_at = "done", TaskStatus.DONE, _now()
    elif outcome == "call_back":
        task.ai_status, task.due_at = "scheduled", _now() + timedelta(hours=2)
    else:
        task.ai_status, task.doer = "needs_person", "person"
    session.commit()


# ---------------------------------------------------------------------------
# The tick
# ---------------------------------------------------------------------------


def tick() -> int:
    """Background: run every trigger and step that is due. Each in its own try."""
    from . import inbound

    session = inbound.session_factory()
    done = 0
    try:
        from . import customer_agents, supplier_calls

        for job in (run_ai_calls, run_purchase, tick_rfqs, supplier_calls.tick, tick_chase, run_outreach, run_after_sales, customer_agents.run_collections):
            try:
                result = job(session)
                done += 1 if result else 0
            except Exception:
                session.rollback()
                logger.exception("Automation job %s failed", job.__name__)
    finally:
        session.close()
    return done
