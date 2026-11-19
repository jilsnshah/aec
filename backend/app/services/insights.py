"""Business intelligence computed from live data.

Every figure here is derived from the same tables the screens use, with the
same definitions as the dashboard:

* **Booked** -- the value of orders placed (cancelled orders excluded).
* **Revenue** -- delivered quantity x the line's net price, on the day the
  goods left (a delivery).
* **Cost of goods** -- the FIFO cost of the stock allocated to those
  deliveries.
* **Stock figure** -- bought - sold: physical + on order - still to deliver.

The screens (Insights page, alerts) and the assistant call these functions
through ``/api/insights``, so they always agree.
"""
from __future__ import annotations

import math
import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import ValidationError
from ..models import (
    Customer,
    CustomerEnquiryItem,
    CustomerDelivery,
    CustomerDeliveryItem,
    CustomerEnquiry,
    EnquiryStatus,
    GoodsReceipt,
    GoodsReceiptItem,
    OrderStatus,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    SalesOrder,
    SalesOrderItem,
    StockAllocation,
    StockCostLayer,
    StockReceipt,
    Supplier,
    Task,
    TaskStatus,
)
from ..numeric import ZERO
from . import costing, reservations
from . import enquiries as enquiry_service
from .common import on_order_quantity_map, pending_quantity_map

PERIODS = ("today", "week", "month", "quarter", "year", "last_7", "last_30", "last_90")
AGE_BUCKETS: List[Tuple[str, int, Optional[int]]] = [("0-30", 0, 30), ("31-60", 31, 60), ("61-90", 61, 90), ("90+", 91, None)]

#: Thresholds used to flag stock and relationships. Kept here, not in prompts.
DEAD_STOCK_DAYS = 90  # nothing sold for this long while stock sits in the warehouse
SLOW_COVER_DAYS = 90  # free stock lasts longer than this at the current sales rate
LOW_COVER_DAYS = 14  # stock runs out within this at the current sales rate
TARGET_COVER_DAYS = 30  # reorder up to this many days of sales
DEFAULT_LEAD_TIME_DAYS = 7  # when neither the product nor its supplier says
TREND_MIN_UNITS = 5  # below this many units in both months, a trend is noise
STALE_ENQUIRY_DAYS = 7  # an open quote untouched this long needs a follow-up
DORMANT_CUSTOMER_DAYS = 60
WAITING_ORDER_DAYS = 14


def _zone() -> ZoneInfo:
    return ZoneInfo(get_settings().business_timezone)


def _now() -> datetime:
    return datetime.now(_zone())


def _f(value: Any) -> float:
    """JSON-friendly number, rounded for money and quantities."""
    if value is None:
        return 0.0
    return round(float(value), 2)


def _pct(part: float, whole: float) -> Optional[float]:
    return round(part / whole * 100, 1) if whole else None


def _change(current: float, previous: float) -> Optional[float]:
    if not previous:
        return None
    return round((current - previous) / abs(previous) * 100, 1)


def _start_of_day(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=_zone())


def period_bounds(period: str, start: Optional[date] = None, end: Optional[date] = None) -> Dict[str, datetime]:
    """The current window and the one before it, of the same length.

    ``start``/``end`` (inclusive days) override ``period``.
    """
    today = _now().date()
    if start or end:
        first = start or today
        last = end or today
        if last < first:
            raise ValidationError("The start date is after the end date.")
        cur_start, cur_end = _start_of_day(first), _start_of_day(last + timedelta(days=1))
        length = cur_end - cur_start
        return {"start": cur_start, "end": cur_end, "prev_start": cur_start - length, "prev_end": cur_start}
    if period not in PERIODS:
        raise ValidationError("period must be one of: {}.".format(", ".join(PERIODS)))
    tomorrow = _start_of_day(today + timedelta(days=1))
    if period == "today":
        cur_start = _start_of_day(today)
        return {"start": cur_start, "end": tomorrow, "prev_start": cur_start - timedelta(days=1), "prev_end": cur_start}
    if period.startswith("last_"):
        days = int(period.split("_")[1])
        cur_start = _start_of_day(today - timedelta(days=days - 1))
        return {"start": cur_start, "end": tomorrow, "prev_start": cur_start - timedelta(days=days), "prev_end": cur_start}
    if period == "week":
        cur_start = _start_of_day(today - timedelta(days=today.weekday()))
        prev_start = cur_start - timedelta(days=7)
    elif period == "month":
        first = today.replace(day=1)
        cur_start = _start_of_day(first)
        prev_first = (first - timedelta(days=1)).replace(day=1)
        prev_start = _start_of_day(prev_first)
    elif period == "quarter":
        first = today.replace(month=(today.month - 1) // 3 * 3 + 1, day=1)
        cur_start = _start_of_day(first)
        prev_month = first.month - 3 if first.month > 3 else first.month + 9
        prev_year = first.year if first.month > 3 else first.year - 1
        prev_start = _start_of_day(date(prev_year, prev_month, 1))
    else:  # year
        cur_start = _start_of_day(today.replace(month=1, day=1))
        prev_start = _start_of_day(date(today.year - 1, 1, 1))
    # Compare like with like: the same number of days into the previous period.
    elapsed = tomorrow - cur_start
    return {"start": cur_start, "end": tomorrow, "prev_start": prev_start, "prev_end": min(prev_start + elapsed, cur_start)}


# ---------------------------------------------------------------------------
# Trading in a window
# ---------------------------------------------------------------------------


def trading(session: Session, start: datetime, end: datetime) -> Dict[str, Any]:
    """Orders, revenue, profit, enquiries and purchasing between two instants."""
    booked = session.execute(
        select(func.count(SalesOrder.id), func.coalesce(func.sum(SalesOrder.total_amount), 0))
        .where(SalesOrder.status != OrderStatus.CANCELLED, SalesOrder.created_at >= start, SalesOrder.created_at < end)
    ).one()
    revenue = session.execute(
        select(func.coalesce(func.sum(CustomerDeliveryItem.quantity * SalesOrderItem.unit_price_net), 0))
        .select_from(CustomerDeliveryItem)
        .join(CustomerDelivery, CustomerDeliveryItem.customer_delivery_id == CustomerDelivery.id)
        .join(SalesOrderItem, CustomerDeliveryItem.order_item_id == SalesOrderItem.id)
        .where(CustomerDelivery.created_at >= start, CustomerDelivery.created_at < end)
    ).scalar_one()
    cogs = session.execute(
        select(func.coalesce(func.sum(StockAllocation.cost_amount), 0))
        .select_from(StockAllocation)
        .join(CustomerDeliveryItem, StockAllocation.customer_delivery_item_id == CustomerDeliveryItem.id)
        .join(CustomerDelivery, CustomerDeliveryItem.customer_delivery_id == CustomerDelivery.id)
        .where(CustomerDelivery.created_at >= start, CustomerDelivery.created_at < end)
    ).scalar_one()
    deliveries = session.execute(
        select(func.count(CustomerDelivery.id)).where(CustomerDelivery.created_at >= start, CustomerDelivery.created_at < end)
    ).scalar_one()
    enquiries_new = session.execute(
        select(func.count(CustomerEnquiry.id)).where(CustomerEnquiry.created_at >= start, CustomerEnquiry.created_at < end)
    ).scalar_one()
    converted = session.execute(
        select(func.count(CustomerEnquiry.id)).where(CustomerEnquiry.converted_at >= start, CustomerEnquiry.converted_at < end)
    ).scalar_one()
    lost = session.execute(
        select(func.count(CustomerEnquiry.id)).where(CustomerEnquiry.lost_at >= start, CustomerEnquiry.lost_at < end)
    ).scalar_one()
    new_customers = session.execute(
        select(func.count(Customer.id)).where(Customer.created_at >= start, Customer.created_at < end)
    ).scalar_one()
    goods_in = session.execute(
        select(func.coalesce(func.sum(GoodsReceiptItem.total_cost), 0))
        .join(GoodsReceipt, GoodsReceiptItem.goods_receipt_id == GoodsReceipt.id)
        .where(GoodsReceipt.created_at >= start, GoodsReceipt.created_at < end)
    ).scalar_one()
    stock_in = session.execute(
        select(func.coalesce(func.sum(StockReceipt.total_cost), 0))
        .where(StockReceipt.created_at >= start, StockReceipt.created_at < end)
    ).scalar_one()
    po_placed = session.execute(
        select(
            func.count(func.distinct(PurchaseOrder.id)),
            func.coalesce(func.sum(PurchaseOrderItem.quantity_ordered * PurchaseOrderItem.unit_cost), 0),
        )
        .join(PurchaseOrderItem, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .where(PurchaseOrder.ordered_at >= start, PurchaseOrder.ordered_at < end)
    ).one()
    from . import returns as returns_service

    credited = returns_service.totals_between(session, start, end)
    # Returns net out of revenue; restocked units net out of cost of goods
    # (damaged ones stay as cost: the goods are gone).
    revenue_f = round(_f(revenue) - credited["amount"], 2)
    cogs_f = round(_f(cogs) - credited["restocked_cost"], 2)
    profit = round(revenue_f - cogs_f, 2)
    decided = converted + lost
    return {
        "orders": booked[0],
        "booked_value": _f(booked[1]),
        "average_order_value": _f(Decimal(booked[1]) / booked[0]) if booked[0] else 0.0,
        "deliveries": deliveries,
        "revenue": revenue_f,
        "returns_value": round(credited["amount"], 2),
        "returns": credited["count"],
        "cost_of_goods": cogs_f,
        "gross_profit": profit,
        "margin_percent": _pct(profit, revenue_f),
        "enquiries": enquiries_new,
        "enquiries_converted": converted,
        "enquiries_lost": lost,
        "conversion_rate": _pct(converted, decided),
        "new_customers": new_customers,
        "purchase_orders_placed": po_placed[0],
        "purchase_orders_value": _f(po_placed[1]),
        "goods_received_value": round(_f(goods_in) + _f(stock_in), 2),
    }


def overview(session: Session, period: str = "month", start: Optional[date] = None, end: Optional[date] = None) -> Dict[str, Any]:
    """This period against the previous one, with the change in each figure."""
    bounds = period_bounds(period, start, end)
    current = trading(session, bounds["start"], bounds["end"])
    previous = trading(session, bounds["prev_start"], bounds["prev_end"])
    changes = {
        key: _change(current[key], previous[key])
        for key, value in current.items()
        if isinstance(value, (int, float)) and key not in ("margin_percent", "conversion_rate")
    }
    changes["margin_percent"] = (
        round(current["margin_percent"] - previous["margin_percent"], 1)
        if current["margin_percent"] is not None and previous["margin_percent"] is not None
        else None
    )
    from . import finance
    from ..models import SalesTarget

    money_in = finance.collected(session, bounds["start"], bounds["end"])
    money_prev = finance.collected(session, bounds["prev_start"], bounds["prev_end"])
    current["cash_received"], current["cash_paid"] = money_in["received"], money_in["paid"]
    previous["cash_received"], previous["cash_paid"] = money_prev["received"], money_prev["paid"]
    changes["cash_received"] = _change(current["cash_received"], previous["cash_received"])
    changes["cash_paid"] = _change(current["cash_paid"], previous["cash_paid"])
    target = None
    if period == "month" and not (start or end):
        month = bounds["start"].strftime("%Y-%m")
        rows = {t.metric: float(t.amount) for t in session.execute(select(SalesTarget).where(SalesTarget.month == month)).scalars()}
        if rows:
            import calendar

            days_in_month = calendar.monthrange(bounds["start"].year, bounds["start"].month)[1]
            elapsed = (bounds["end"] - bounds["start"]).days
            target = {
                metric: {
                    "target": amount,
                    "actual": current["booked_value" if metric == "booked" else "revenue"],
                    "percent": _pct(current["booked_value" if metric == "booked" else "revenue"], amount),
                    # Where the month ends at the current daily pace (an estimate).
                    "projected": round(current["booked_value" if metric == "booked" else "revenue"] / max(elapsed, 1) * days_in_month, 2),
                    "days_elapsed": elapsed,
                    "days_in_month": days_in_month,
                }
                for metric, amount in rows.items()
            }
    return {
        "target": target,
        "period": period if not (start or end) else "custom",
        "start": bounds["start"].date(),
        "end": (bounds["end"] - timedelta(days=1)).date(),
        "previous_start": bounds["prev_start"].date(),
        "previous_end": (bounds["prev_end"] - timedelta(seconds=1)).date(),
        "current": current,
        "previous": previous,
        "change_percent": changes,
        "daily": daily_series(session, bounds["start"], bounds["end"]),
    }


def daily_series(session: Session, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    zone = get_settings().business_timezone

    def local_day(column):
        return func.date(func.timezone(zone, column))

    booked_day = local_day(SalesOrder.created_at)
    booked = dict(
        (day, (count, value))
        for day, count, value in session.execute(
            select(booked_day, func.count(SalesOrder.id), func.sum(SalesOrder.total_amount))
            .where(SalesOrder.status != OrderStatus.CANCELLED, SalesOrder.created_at >= start, SalesOrder.created_at < end)
            .group_by(booked_day)
        ).all()
    )
    delivered_day = local_day(CustomerDelivery.created_at)
    delivered = dict(
        session.execute(
            select(delivered_day, func.sum(CustomerDeliveryItem.quantity * SalesOrderItem.unit_price_net))
            .select_from(CustomerDeliveryItem)
            .join(CustomerDelivery, CustomerDeliveryItem.customer_delivery_id == CustomerDelivery.id)
            .join(SalesOrderItem, CustomerDeliveryItem.order_item_id == SalesOrderItem.id)
            .where(CustomerDelivery.created_at >= start, CustomerDelivery.created_at < end)
            .group_by(delivered_day)
        ).all()
    )
    days = (end.astimezone(_zone()).date() - start.astimezone(_zone()).date()).days
    rows = []
    for offset in range(min(days, 400)):
        day = start.astimezone(_zone()).date() + timedelta(days=offset)
        count, value = booked.get(day, (0, 0))
        rows.append({"date": day, "orders": count, "booked": _f(value), "revenue": _f(delivered.get(day))})
    return rows


# ---------------------------------------------------------------------------
# Inventory health
# ---------------------------------------------------------------------------


def _sold_since(session: Session, since: datetime) -> Dict[uuid.UUID, Decimal]:
    rows = session.execute(
        select(
            SalesOrderItem.product_id,
            func.sum(SalesOrderItem.quantity_ordered - SalesOrderItem.quantity_cancelled),
        )
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .where(SalesOrder.status != OrderStatus.CANCELLED, SalesOrder.created_at >= since)
        .group_by(SalesOrderItem.product_id)
    ).all()
    return {product_id: Decimal(value or 0) for product_id, value in rows}


def inventory_health(session: Session, include_archived: bool = False) -> Dict[str, Any]:
    """Per product: position, value, age of stock, sales rate, cover, flags and
    a reorder quantity; with totals for the whole warehouse."""
    now = _now()
    stmt = select(Product).order_by(Product.name)
    if not include_archived:
        stmt = stmt.where(Product.is_active.is_(True))
    products = list(session.execute(stmt).scalars().all())

    pending = pending_quantity_map(session)
    reserved = reservations.reserved_map(session)
    on_order = on_order_quantity_map(session)
    incoming = dict(
        session.execute(
            select(SalesOrderItem.product_id, func.sum(SalesOrderItem.quantity_incoming))
            .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
            .where(SalesOrder.status != OrderStatus.CANCELLED)
            .group_by(SalesOrderItem.product_id)
        ).all()
    )
    valuations = costing.stock_valuation_map(session)
    sold_30 = _sold_since(session, now - timedelta(days=30))
    sold_90 = _sold_since(session, now - timedelta(days=90))
    last_sale = dict(
        session.execute(
            select(SalesOrderItem.product_id, func.max(SalesOrder.created_at))
            .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
            .where(SalesOrder.status != OrderStatus.CANCELLED)
            .group_by(SalesOrderItem.product_id)
        ).all()
    )
    last_in = dict(
        session.execute(
            select(StockCostLayer.product_id, func.max(StockCostLayer.created_at)).group_by(StockCostLayer.product_id)
        ).all()
    )
    # The latest price quoted on a purchase order, for products never received.
    po_price: Dict[uuid.UUID, Decimal] = {}
    for product_id, unit_cost in session.execute(
        select(PurchaseOrderItem.product_id, PurchaseOrderItem.unit_cost)
        .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .where(PurchaseOrder.status != PurchaseOrderStatus.CANCELLED, PurchaseOrderItem.unit_cost > 0)
        .order_by(PurchaseOrder.created_at)
    ).all():
        po_price[product_id] = unit_cost
    sold_prev_30 = {
        pid: sold_90_minus - sold_30.get(pid, ZERO)
        for pid, sold_90_minus in _sold_since(session, now - timedelta(days=60)).items()
    }
    cogs_90 = dict(
        session.execute(
            select(CustomerDeliveryItem.product_id, func.sum(StockAllocation.cost_amount))
            .select_from(StockAllocation)
            .join(CustomerDeliveryItem, StockAllocation.customer_delivery_item_id == CustomerDeliveryItem.id)
            .join(CustomerDelivery, CustomerDeliveryItem.customer_delivery_id == CustomerDelivery.id)
            .where(CustomerDelivery.created_at >= now - timedelta(days=90))
            .group_by(CustomerDeliveryItem.product_id)
        ).all()
    )
    enquiry_demand = dict(
        session.execute(
            select(CustomerEnquiryItem.product_id, func.sum(CustomerEnquiryItem.quantity))
            .join(CustomerEnquiry, CustomerEnquiryItem.enquiry_id == CustomerEnquiry.id)
            .where(CustomerEnquiry.status == EnquiryStatus.OPEN)
            .group_by(CustomerEnquiryItem.product_id)
        ).all()
    )
    # What the short quantities are worth at the prices customers agreed.
    owed_price = dict(
        session.execute(
            select(SalesOrderItem.product_id,
                   func.sum(SalesOrderItem.unit_price_net * (SalesOrderItem.quantity_ordered - SalesOrderItem.quantity_fulfilled - SalesOrderItem.quantity_cancelled))
                   / func.nullif(func.sum(SalesOrderItem.quantity_ordered - SalesOrderItem.quantity_fulfilled - SalesOrderItem.quantity_cancelled), 0))
            .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
            .where(SalesOrder.status.in_([OrderStatus.PENDING, OrderStatus.PARTIALLY_FULFILLED]))
            .group_by(SalesOrderItem.product_id)
        ).all()
    )
    suppliers = {row.id: row for row in session.execute(select(Supplier)).scalars()}
    layers = defaultdict(list)
    for layer in session.execute(select(StockCostLayer).where(StockCostLayer.quantity_remaining > 0)).scalars():
        layers[layer.product_id].append(layer)

    rows = []
    totals = {
        "products": 0,
        "stock_value": 0.0,
        "age_value": {name: 0.0 for name, _, _ in AGE_BUCKETS},
        "dead_stock_value": 0.0,
        "slow_stock_value": 0.0,
        "short_quantity_products": 0,
        "low_cover_products": 0,
        "reorder_products": 0,
        "reorder_value": 0.0,
    }
    for product in products:
        physical = Decimal(str(product.physical_stock))
        pend = pending.get(product.id, ZERO)
        res = reserved.get(product.id, ZERO)
        orders_in = on_order.get(product.id, ZERO)
        inc = Decimal(incoming.get(product.id) or 0)
        short = max(ZERO, pend - res - inc)
        free = physical - res
        position = physical + orders_in - pend  # the stock figure
        value = _f((valuations.get(product.id) or {}).get("stock_value", 0))

        ages = {name: {"quantity": 0.0, "value": 0.0} for name, _, _ in AGE_BUCKETS}
        oldest_days = None
        for layer in layers.get(product.id, []):
            age = max(0, (now - layer.created_at.astimezone(_zone())).days)
            oldest_days = age if oldest_days is None else max(oldest_days, age)
            for name, low, high in AGE_BUCKETS:
                if age >= low and (high is None or age <= high):
                    ages[name]["quantity"] += _f(layer.quantity_remaining)
                    ages[name]["value"] += _f(layer.quantity_remaining * layer.unit_cost)
                    break
        for bucket in ages.values():
            bucket["quantity"], bucket["value"] = round(bucket["quantity"], 3), round(bucket["value"], 2)

        rate_90 = float(sold_90.get(product.id, ZERO)) / 90
        rate_30 = float(sold_30.get(product.id, ZERO)) / 30
        # Weight the recent month more, so a product that just picked up shows it.
        rate = round(rate_30 * 0.6 + rate_90 * 0.4, 4) if (rate_30 or rate_90) else 0.0
        # Cover counts everything bought and not yet sold: free stock plus what is
        # on order and not already promised (the stock figure).
        cover_days = round(max(0.0, float(position)) / rate, 1) if rate > 0 else None
        sold_at = last_sale.get(product.id)
        days_since_sale = (now - sold_at.astimezone(_zone())).days if sold_at else None

        flags = []
        if short > 0:
            flags.append("short")
        if physical > 0 and (days_since_sale is None or days_since_sale >= DEAD_STOCK_DAYS) and (oldest_days or 0) >= 30:
            flags.append("dead")
        elif cover_days is not None and cover_days > SLOW_COVER_DAYS and physical > 0:
            flags.append("slow")
        if rate > 0 and cover_days is not None and cover_days < LOW_COVER_DAYS:
            flags.append("low_cover")
        supplier = suppliers.get(product.preferred_supplier_id) if product.preferred_supplier_id else None
        if product.lead_time_days is not None:
            lead, lead_source = product.lead_time_days, "product"
        elif supplier is not None and supplier.lead_time_days is not None:
            lead, lead_source = supplier.lead_time_days, "supplier"
        else:
            lead, lead_source = DEFAULT_LEAD_TIME_DAYS, "assumed"
        minimum = float(product.reorder_level or 0)
        # Reorder point: what sells while a new order is on its way, plus the minimum.
        reorder_point = round(rate * lead + minimum, 3)
        if float(position) < minimum and "short" not in flags:
            flags.append("below_minimum")
        reorder = 0.0
        if rate > 0 or position < 0 or float(position) < minimum:
            need = rate * (lead + TARGET_COVER_DAYS) + minimum - float(position)
            reorder = max(0.0, need, -float(position))
            reorder = float(math.ceil(reorder)) if reorder else 0.0
        # When to place the next order so it arrives before stock runs below the minimum.
        if rate > 0:
            days_until = (float(position) - reorder_point) / rate
            order_by = (now.date() + timedelta(days=max(0, math.floor(days_until)))) if days_until < 120 else None
        else:
            order_by = now.date() if position < 0 or float(position) < minimum else None
        recent, before = float(sold_30.get(product.id, ZERO)), float(sold_prev_30.get(product.id, ZERO))
        if max(recent, before) < TREND_MIN_UNITS:
            trend, trend_change = "insufficient_data", None
        else:
            trend_change = round((recent - before) / before * 100, 1) if before else None
            trend = "rising" if before == 0 or recent >= before * 1.2 else "falling" if recent <= before * 0.8 else "steady"
        cost_90 = float(cogs_90.get(product.id) or 0)
        turnover = round(cost_90 * (365 / 90) / value, 2) if value > 0 and cost_90 > 0 else None
        days_to_clear = round(float(physical) / rate) if rate > 0 and physical > 0 else None
        price_owed = float(owed_price.get(product.id) or 0) or float(product.mrp or 0)
        unit_cost = (
            _f(product.last_purchase_price)
            or (round(value / float(physical), 2) if physical > 0 else 0.0)
            or _f(po_price.get(product.id))
        )
        if reorder > 0:
            flags.append("reorder")
        if trend == "rising" and "short" not in flags:
            flags.append("rising_demand")
        if trend == "falling":
            flags.append("falling_demand")
        liquidation = round(value * ((oldest_days or 0) / 30), 2) if ("dead" in flags or "slow" in flags) else 0.0
        open_enquiry = _f(enquiry_demand.get(product.id))
        if "short" in flags or "below_minimum" in flags or (order_by is not None and order_by <= now.date() + timedelta(days=3)):
            action = {"code": "buy", "text": "Buy {} {}{}".format(_qty(reorder), product.unit_of_measure,
                       " by {}".format(order_by.isoformat()) if order_by else " now")}
        elif "dead" in flags and (oldest_days or 0) >= 90:
            action = {"code": "liquidate", "text": "Clear it: {} idle for {} days".format(_money(value), oldest_days)}
        elif "dead" in flags or "slow" in flags:
            order_by = None  # nothing to plan: there is more than enough
            action = {"code": "do_not_reorder", "text": "Do not reorder: {}".format(
                "about {} days of sales in hand or on order".format(int(cover_days)) if cover_days else "no sales in 90 days")}
        elif order_by is not None and reorder > 0:
            action = {"code": "plan", "text": "Order {} {} by {}".format(_qty(reorder), product.unit_of_measure, order_by.isoformat())}
        elif trend == "rising":
            action = {"code": "watch", "text": "Demand rising; keep an eye on cover"}
        else:
            action = {"code": "ok", "text": "Healthy"}

        rows.append(
            {
                "product_id": product.id,
                "sku": product.sku,
                "name": product.name,
                "unit": product.unit_of_measure,
                "is_active": product.is_active,
                "physical": _f(physical),
                "reserved": _f(res),
                "free": _f(free),
                "on_order": _f(orders_in),
                "to_deliver": _f(pend),
                "short": _f(short),
                "stock_figure": _f(position),
                "stock_value": value,
                "ages": ages,
                "oldest_stock_days": oldest_days,
                "sold_30_days": _f(sold_30.get(product.id, ZERO)),
                "sold_90_days": _f(sold_90.get(product.id, ZERO)),
                "daily_sales_rate": rate,
                "days_of_cover": cover_days,
                "last_sale": sold_at,
                "days_since_last_sale": days_since_sale,
                "last_received": last_in.get(product.id),
                "reorder_quantity": reorder,
                "reorder_value": round(reorder * unit_cost, 2),
                "flags": flags,
                "category": product.category,
                "reorder_level": minimum,
                "reorder_point": reorder_point,
                "lead_time_days": lead,
                "lead_time_source": lead_source,
                "order_by": order_by,
                "preferred_supplier_id": product.preferred_supplier_id,
                "preferred_supplier_name": supplier.name if supplier else None,
                "unit_cost": unit_cost,
                "sold_prev_30_days": round(before, 3),
                "demand_trend": trend,
                "demand_change_percent": trend_change,
                "turnover_per_year": turnover,
                "holding_days": round(365 / turnover) if turnover else None,
                "days_to_clear": days_to_clear,
                "open_enquiry_quantity": open_enquiry,
                "sales_at_risk_value": round(float(short) * price_owed, 2),
                "liquidation_priority": liquidation,
                "action": action,
            }
        )
        totals["products"] += 1
        totals["stock_value"] += value
        for name in ages:
            totals["age_value"][name] += ages[name]["value"]
        if "dead" in flags:
            totals["dead_stock_value"] += value
        if "slow" in flags:
            totals["slow_stock_value"] += value
        if "short" in flags:
            totals["short_quantity_products"] += 1
        if "low_cover" in flags:
            totals["low_cover_products"] += 1
        if reorder > 0:
            totals["reorder_products"] += 1
            totals["reorder_value"] += round(reorder * unit_cost, 2)
        totals["sales_at_risk_value"] = round(totals.get("sales_at_risk_value", 0.0) + float(short) * price_owed, 2)
        totals["cost_of_goods_90_days"] = round(totals.get("cost_of_goods_90_days", 0.0) + cost_90, 2)

    for key in ("stock_value", "dead_stock_value", "slow_stock_value", "reorder_value"):
        totals[key] = round(totals[key], 2)
    totals["age_value"] = {name: round(value, 2) for name, value in totals["age_value"].items()}
    totals["capital_at_risk"] = round(totals["dead_stock_value"] + totals["slow_stock_value"], 2)
    totals.setdefault("sales_at_risk_value", 0.0)
    totals.setdefault("cost_of_goods_90_days", 0.0)
    totals["turnover_per_year"] = (
        round(totals["cost_of_goods_90_days"] * (365 / 90) / totals["stock_value"], 2) if totals["stock_value"] > 0 else None
    )
    totals["categories"] = _category_rollup(rows)
    rows.sort(key=lambda row: (-len(row["flags"]), -row["stock_value"]))
    return {
        "as_of": now,
        "thresholds": {
            "dead_stock_days": DEAD_STOCK_DAYS,
            "slow_cover_days": SLOW_COVER_DAYS,
            "low_cover_days": LOW_COVER_DAYS,
            "target_cover_days": TARGET_COVER_DAYS,
            "default_lead_time_days": DEFAULT_LEAD_TIME_DAYS,
        },
        "totals": totals,
        "products": rows,
    }


def _category_rollup(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        name = row.get("category") or "(none)"
        group = groups.setdefault(name, {"category": name, "products": 0, "stock_value": 0.0, "aged_90_value": 0.0,
                                         "capital_at_risk": 0.0, "reorder_value": 0.0, "short_products": 0})
        group["products"] += 1
        group["stock_value"] += row["stock_value"]
        group["aged_90_value"] += row["ages"]["90+"]["value"]
        if "dead" in row["flags"] or "slow" in row["flags"]:
            group["capital_at_risk"] += row["stock_value"]
        group["reorder_value"] += row["reorder_value"]
        if "short" in row["flags"]:
            group["short_products"] += 1
    out = []
    for group in groups.values():
        out.append({key: (round(value, 2) if isinstance(value, float) else value) for key, value in group.items()})
    return sorted(out, key=lambda item: -item["stock_value"])


# ---------------------------------------------------------------------------
# Sales breakdowns
# ---------------------------------------------------------------------------

GROUPS = ("product", "customer", "month", "day")


def sales_breakdown(
    session: Session,
    group_by: str = "product",
    period: str = "last_90",
    start: Optional[date] = None,
    end: Optional[date] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """Booked and delivered trade grouped by product, customer, month or day."""
    if group_by not in GROUPS:
        raise ValidationError("group_by must be one of: {}.".format(", ".join(GROUPS)))
    bounds = period_bounds(period, start, end)
    lo, hi = bounds["start"], bounds["end"]
    zone = get_settings().business_timezone

    def key_columns(order_date):
        if group_by == "product":
            return [Product.id, Product.name, Product.sku]
        if group_by == "customer":
            return [Customer.id, Customer.name]
        fmt = "YYYY-MM" if group_by == "month" else "YYYY-MM-DD"
        return [func.to_char(func.timezone(zone, order_date), fmt)]

    booked_keys = key_columns(SalesOrder.created_at)
    booked_rows = session.execute(
        select(
            *booked_keys,
            func.count(func.distinct(SalesOrder.id)),
            func.sum(SalesOrderItem.quantity_ordered - SalesOrderItem.quantity_cancelled),
            func.sum((SalesOrderItem.quantity_ordered - SalesOrderItem.quantity_cancelled) * SalesOrderItem.unit_price_net),
        )
        .select_from(SalesOrderItem)
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .join(Product, SalesOrderItem.product_id == Product.id)
        .join(Customer, SalesOrder.customer_id == Customer.id)
        .where(SalesOrder.status != OrderStatus.CANCELLED, SalesOrder.created_at >= lo, SalesOrder.created_at < hi)
        .group_by(*booked_keys)
    ).all()

    delivered_keys = key_columns(CustomerDelivery.created_at)
    delivered_rows = session.execute(
        select(
            *delivered_keys,
            func.sum(CustomerDeliveryItem.quantity),
            func.sum(CustomerDeliveryItem.quantity * SalesOrderItem.unit_price_net),
        )
        .select_from(CustomerDeliveryItem)
        .join(CustomerDelivery, CustomerDeliveryItem.customer_delivery_id == CustomerDelivery.id)
        .join(SalesOrderItem, CustomerDeliveryItem.order_item_id == SalesOrderItem.id)
        .join(Product, CustomerDeliveryItem.product_id == Product.id)
        .join(Customer, CustomerDelivery.customer_id == Customer.id)
        .where(CustomerDelivery.created_at >= lo, CustomerDelivery.created_at < hi)
        .group_by(*delivered_keys)
    ).all()
    cost_rows = session.execute(
        select(*delivered_keys, func.sum(StockAllocation.cost_amount))
        .select_from(StockAllocation)
        .join(CustomerDeliveryItem, StockAllocation.customer_delivery_item_id == CustomerDeliveryItem.id)
        .join(CustomerDelivery, CustomerDeliveryItem.customer_delivery_id == CustomerDelivery.id)
        .join(Product, CustomerDeliveryItem.product_id == Product.id)
        .join(Customer, CustomerDelivery.customer_id == Customer.id)
        .where(CustomerDelivery.created_at >= lo, CustomerDelivery.created_at < hi)
        .group_by(*delivered_keys)
    ).all()

    width = len(booked_keys)
    groups: Dict[Any, Dict[str, Any]] = {}

    def entry(row) -> Dict[str, Any]:
        key = tuple(row[:width])
        if key not in groups:
            if group_by == "product":
                label = {"product_id": key[0], "name": key[1], "sku": key[2]}
            elif group_by == "customer":
                label = {"customer_id": key[0], "name": key[1]}
            else:
                label = {"name": key[0]}
            groups[key] = dict(label, orders=0, quantity_booked=0.0, booked_value=0.0,
                               quantity_delivered=0.0, revenue=0.0, cost_of_goods=0.0)
        return groups[key]

    for row in booked_rows:
        item = entry(row)
        item["orders"] = row[width]
        item["quantity_booked"] = _f(row[width + 1])
        item["booked_value"] = _f(row[width + 2])
    for row in delivered_rows:
        item = entry(row)
        item["quantity_delivered"] = _f(row[width])
        item["revenue"] = _f(row[width + 1])
    for row in cost_rows:
        entry(row)["cost_of_goods"] = _f(row[width])
    items = list(groups.values())
    for item in items:
        item["gross_profit"] = round(item["revenue"] - item["cost_of_goods"], 2)
        item["margin_percent"] = _pct(item["gross_profit"], item["revenue"])
    total_booked = sum(item["booked_value"] for item in items)
    total_revenue = sum(item["revenue"] for item in items)
    for item in items:
        item["share_of_booked_percent"] = _pct(item["booked_value"], total_booked)
    if group_by in ("month", "day"):
        items.sort(key=lambda item: item["name"])
    else:
        items.sort(key=lambda item: (-item["booked_value"], -item["revenue"]))
    return {
        "group_by": group_by,
        "start": lo.date(),
        "end": (hi - timedelta(days=1)).date(),
        "totals": {
            "booked_value": round(total_booked, 2),
            "revenue": round(total_revenue, 2),
            "cost_of_goods": round(sum(item["cost_of_goods"] for item in items), 2),
            "gross_profit": round(sum(item["gross_profit"] for item in items), 2),
        },
        "items": items[:limit] if group_by in ("product", "customer") else items,
        "truncated": group_by in ("product", "customer") and len(items) > limit,
    }


# ---------------------------------------------------------------------------
# Enquiries
# ---------------------------------------------------------------------------


def enquiry_funnel(session: Session, period: Optional[str] = None, start: Optional[date] = None, end: Optional[date] = None) -> Dict[str, Any]:
    """How quotes turn into orders: by source, how long it takes, what is stuck."""
    stmt = select(CustomerEnquiry)
    if period or start or end:
        bounds = period_bounds(period or "last_90", start, end)
        stmt = stmt.where(CustomerEnquiry.created_at >= bounds["start"], CustomerEnquiry.created_at < bounds["end"])
    enquiries = list(session.execute(enquiry_service._with_relations(stmt)).unique().scalars().all())
    now = _now()
    open_task_enquiries = {
        row[0]
        for row in session.execute(
            select(Task.enquiry_id).where(Task.enquiry_id.is_not(None), Task.status == TaskStatus.OPEN)
        ).all()
    }

    by_source: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"total": 0, "open": 0, "converted": 0, "lost": 0, "value_converted": 0.0})
    days_to_convert: List[float] = []
    lost_reasons: Dict[str, int] = defaultdict(int)
    stale = []
    pipeline_value = 0.0
    counts = {"total": 0, "open": 0, "converted": 0, "lost": 0}
    for enquiry in enquiries:
        status = enquiry.status.value.lower()
        value = _f(enquiry_service.enquiry_total(enquiry))
        counts["total"] += 1
        counts[status] += 1
        source = by_source[enquiry.source or "manual"]
        source["total"] += 1
        source[status] += 1
        if enquiry.status == EnquiryStatus.CONVERTED:
            source["value_converted"] += value
            if enquiry.converted_at:
                days_to_convert.append((enquiry.converted_at - enquiry.created_at).total_seconds() / 86400)
        elif enquiry.status == EnquiryStatus.LOST:
            lost_reasons[(enquiry.lost_reason or "No reason given").strip()[:80]] += 1
        else:
            pipeline_value += value
            idle = (now - enquiry.updated_at.astimezone(_zone())).days
            if idle >= STALE_ENQUIRY_DAYS:
                stale.append(
                    {
                        "enquiry_id": enquiry.id,
                        "enquiry_number": enquiry.enquiry_number,
                        "customer_id": enquiry.customer_id,
                        "customer_name": enquiry.customer.name,
                        "value": value,
                        "days_idle": idle,
                        "age_days": (now - enquiry.created_at.astimezone(_zone())).days,
                        "source": enquiry.source,
                        "has_open_follow_up": enquiry.id in open_task_enquiries,
                    }
                )
    # Priority for open enquiries: bigger deals, customers who already buy,
    # fresher quotes and quotes we can fulfil from stock rank higher.
    repeat_buyers = {
        row[0] for row in session.execute(
            select(SalesOrder.customer_id).where(SalesOrder.status != OrderStatus.CANCELLED).group_by(SalesOrder.customer_id)
        ).all()
    }
    free_stock = {}
    for product in session.execute(select(Product)).scalars():
        free_stock[product.id] = float(product.physical_stock or 0)
    reserved_now = reservations.reserved_map(session)
    open_rows = [e for e in enquiries if e.status == EnquiryStatus.OPEN]
    values = sorted((_f(enquiry_service.enquiry_total(e)) for e in open_rows), reverse=True)
    top_value = values[0] if values else 0
    priorities = []
    for enquiry in open_rows:
        value = _f(enquiry_service.enquiry_total(enquiry))
        age = (now - enquiry.created_at.astimezone(_zone())).days
        idle = (now - enquiry.updated_at.astimezone(_zone())).days
        in_stock = all(free_stock.get(item.product_id, 0) - float(reserved_now.get(item.product_id, 0)) >= float(item.quantity) for item in enquiry.items)
        score, reasons = 0.0, []
        if top_value:
            score += 40 * value / top_value
            if value >= top_value * 0.5:
                reasons.append("one of the biggest open quotes")
        if enquiry.customer_id in repeat_buyers:
            score += 25
            reasons.append("customer already buys from you")
        freshness = max(0.0, 20 - age)
        score += freshness
        if age <= 3:
            reasons.append("fresh — answer while it's warm")
        elif idle >= STALE_ENQUIRY_DAYS:
            reasons.append("untouched for {} days".format(idle))
        if in_stock:
            score += 15
            reasons.append("can be supplied from stock now")
        priorities.append({
            "enquiry_id": enquiry.id, "enquiry_number": enquiry.enquiry_number, "customer_id": enquiry.customer_id,
            "customer_name": enquiry.customer.name, "phone": enquiry.customer.phone, "value": value, "age_days": age,
            "days_idle": idle, "in_stock": in_stock, "score": round(min(score, 100)), "reasons": reasons,
            "has_open_follow_up": enquiry.id in open_task_enquiries,
        })
    priorities.sort(key=lambda row: -row["score"])
    sources = []
    for name, data in sorted(by_source.items(), key=lambda item: -item[1]["total"]):
        decided = data["converted"] + data["lost"]
        sources.append(dict(data, source=name, value_converted=round(data["value_converted"], 2), conversion_rate=_pct(data["converted"], decided)))
    stale.sort(key=lambda row: (-row["value"], -row["days_idle"]))
    decided = counts["converted"] + counts["lost"]
    return {
        "counts": counts,
        "conversion_rate": _pct(counts["converted"], decided),
        "open_pipeline_value": round(pipeline_value, 2),
        "average_days_to_convert": round(sum(days_to_convert) / len(days_to_convert), 1) if days_to_convert else None,
        "by_source": sources,
        "lost_reasons": [{"reason": reason, "count": count} for reason, count in sorted(lost_reasons.items(), key=lambda item: -item[1])],
        "stale_days": STALE_ENQUIRY_DAYS,
        "stale": stale,
        "stale_without_follow_up": sum(1 for row in stale if not row["has_open_follow_up"]),
        "priorities": priorities,
        "priority_note": "Priority 0-100 = deal size (40) + existing customer (25) + freshness (20) + in stock now (15). A ranking aid, not a prediction.",
    }


# ---------------------------------------------------------------------------
# Customers and suppliers
# ---------------------------------------------------------------------------


def customer_insights(session: Session, limit: int = 100) -> Dict[str, Any]:
    """Who buys most, who still owes deliveries, and who has gone quiet."""
    now = _now()
    orders = session.execute(
        select(
            SalesOrder.customer_id,
            func.count(SalesOrder.id),
            func.coalesce(func.sum(SalesOrder.total_amount), 0),
            func.max(SalesOrder.created_at),
            func.min(SalesOrder.created_at),
        )
        .where(SalesOrder.status != OrderStatus.CANCELLED)
        .group_by(SalesOrder.customer_id)
    ).all()
    revenue = dict(
        session.execute(
            select(CustomerDelivery.customer_id, func.sum(CustomerDeliveryItem.quantity * SalesOrderItem.unit_price_net))
            .select_from(CustomerDeliveryItem)
            .join(CustomerDelivery, CustomerDeliveryItem.customer_delivery_id == CustomerDelivery.id)
            .join(SalesOrderItem, CustomerDeliveryItem.order_item_id == SalesOrderItem.id)
            .group_by(CustomerDelivery.customer_id)
        ).all()
    )
    outstanding = dict(
        session.execute(
            select(
                SalesOrder.customer_id,
                func.sum(
                    (SalesOrderItem.quantity_ordered - SalesOrderItem.quantity_fulfilled - SalesOrderItem.quantity_cancelled)
                    * SalesOrderItem.unit_price_net
                ),
            )
            .join(SalesOrderItem, SalesOrderItem.order_id == SalesOrder.id)
            .where(SalesOrder.status.in_([OrderStatus.PENDING, OrderStatus.PARTIALLY_FULFILLED]))
            .group_by(SalesOrder.customer_id)
        ).all()
    )
    open_enquiries = dict(
        session.execute(
            select(CustomerEnquiry.customer_id, func.count(CustomerEnquiry.id))
            .where(CustomerEnquiry.status == EnquiryStatus.OPEN)
            .group_by(CustomerEnquiry.customer_id)
        ).all()
    )
    names = dict(session.execute(select(Customer.id, Customer.name).where(Customer.is_active.is_(True))).all())
    rows = []
    for customer_id, count, booked, last, first in orders:
        if customer_id not in names:
            continue
        days_since = (now - last.astimezone(_zone())).days
        rows.append(
            {
                "customer_id": customer_id,
                "name": names[customer_id],
                "orders": count,
                "booked_value": _f(booked),
                "revenue": _f(revenue.get(customer_id)),
                "average_order_value": _f(Decimal(booked) / count) if count else 0.0,
                "outstanding_value": _f(outstanding.get(customer_id)),
                "open_enquiries": open_enquiries.get(customer_id, 0),
                "first_order": first,
                "last_order": last,
                "days_since_last_order": days_since,
                "dormant": days_since >= DORMANT_CUSTOMER_DAYS,
            }
        )
    rows.sort(key=lambda row: -row["booked_value"])
    total = sum(row["booked_value"] for row in rows) or 0
    running = 0.0
    for rank, row in enumerate(rows, start=1):
        running += row["booked_value"]
        row["rank"] = rank
        row["share_percent"] = _pct(row["booked_value"], total)
        row["cumulative_share_percent"] = _pct(running, total)
    never_ordered = [
        {"customer_id": cid, "name": name, "open_enquiries": open_enquiries.get(cid, 0)}
        for cid, name in names.items()
        if cid not in {row["customer_id"] for row in rows}
    ]
    return {
        "dormant_days": DORMANT_CUSTOMER_DAYS,
        "customers": rows[:limit],
        "dormant": [row for row in rows if row["dormant"]][:limit],
        "never_ordered": never_ordered[:limit],
        "top_share_percent": _pct(sum(row["booked_value"] for row in rows[: max(1, len(rows) // 5)]), total),
    }


def supplier_insights(session: Session) -> Dict[str, Any]:
    """Spend, lead time, reliability and what is still due from each supplier."""
    now = _now()
    pos = list(
        session.execute(
            select(PurchaseOrder).where(PurchaseOrder.status != PurchaseOrderStatus.DRAFT)
        ).scalars().all()
    )
    first_receipt = dict(
        session.execute(
            select(GoodsReceipt.purchase_order_id, func.min(GoodsReceipt.created_at)).group_by(GoodsReceipt.purchase_order_id)
        ).all()
    )
    last_receipt = dict(
        session.execute(
            select(GoodsReceipt.purchase_order_id, func.max(GoodsReceipt.created_at)).group_by(GoodsReceipt.purchase_order_id)
        ).all()
    )
    items = defaultdict(list)
    for item in session.execute(select(PurchaseOrderItem)).scalars():
        items[item.purchase_order_id].append(item)
    suppliers = dict(session.execute(select(Supplier.id, Supplier.name)).all())

    stats: Dict[uuid.UUID, Dict[str, Any]] = {}
    late_open = []
    for po in pos:
        data = stats.setdefault(
            po.supplier_id,
            {"supplier_id": po.supplier_id, "name": suppliers.get(po.supplier_id, "?"), "purchase_orders": 0,
             "ordered_value": 0.0, "received_value": 0.0, "quantity_ordered": 0.0, "quantity_received": 0.0,
             "open_orders": 0, "still_due_value": 0.0, "lead_times": [], "on_time": 0, "with_due_date": 0,
             "cancelled": 0},
        )
        data["purchase_orders"] += 1
        if po.status == PurchaseOrderStatus.CANCELLED:
            data["cancelled"] += 1
        lines = items.get(po.id, [])
        ordered = sum(float(item.quantity_ordered * item.unit_cost) for item in lines)
        received = sum(float(item.quantity_received * item.unit_cost) for item in lines)
        due_value = sum(float(max(ZERO, item.quantity_ordered - item.quantity_received) * item.unit_cost) for item in lines)
        data["ordered_value"] += ordered
        data["received_value"] += received
        data["quantity_ordered"] += sum(float(item.quantity_ordered) for item in lines)
        data["quantity_received"] += sum(float(item.quantity_received) for item in lines)
        is_open = po.status in (PurchaseOrderStatus.ORDERED, PurchaseOrderStatus.PARTIALLY_RECEIVED)
        if is_open:
            data["open_orders"] += 1
            data["still_due_value"] += due_value
        got = first_receipt.get(po.id)
        if got and po.ordered_at:
            data["lead_times"].append((got - po.ordered_at).total_seconds() / 86400)
        if po.expected_delivery_date:
            data["with_due_date"] += 1
            done = last_receipt.get(po.id) if po.status == PurchaseOrderStatus.RECEIVED else None
            if done and done <= po.expected_delivery_date + timedelta(days=1):
                data["on_time"] += 1
            if is_open and po.expected_delivery_date < now:
                late_open.append(
                    {
                        "purchase_order_id": po.id,
                        "po_number": po.po_number,
                        "supplier_id": po.supplier_id,
                        "supplier_name": data["name"],
                        "expected": po.expected_delivery_date.date(),
                        "days_late": (now - po.expected_delivery_date.astimezone(_zone())).days,
                        "still_due_value": round(due_value, 2),
                    }
                )
    rows = []
    for data in stats.values():
        lead = data.pop("lead_times")
        rows.append(
            dict(
                data,
                ordered_value=round(data["ordered_value"], 2),
                received_value=round(data["received_value"], 2),
                still_due_value=round(data["still_due_value"], 2),
                quantity_ordered=round(data["quantity_ordered"], 3),
                quantity_received=round(data["quantity_received"], 3),
                average_lead_days=round(sum(lead) / len(lead), 1) if lead else None,
                fill_rate_percent=_pct(data["quantity_received"], data["quantity_ordered"]),
                on_time_percent=_pct(data["on_time"], data["with_due_date"]),
            )
        )
    rows.sort(key=lambda row: -row["ordered_value"])
    late_open.sort(key=lambda row: -row["days_late"])
    return {"suppliers": rows, "late_purchase_orders": late_open}


# ---------------------------------------------------------------------------
# Alerts and the daily briefing
# ---------------------------------------------------------------------------

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def alerts(session: Session) -> Dict[str, Any]:
    """What needs attention now, most urgent first, each with where to act."""
    found: List[Dict[str, Any]] = []
    stock = inventory_health(session)
    for row in stock["products"]:
        if "short" in row["flags"]:
            found.append({
                "kind": "short_stock", "severity": "critical",
                "title": "{} is short by {} {}".format(row["name"], _qty(row["short"]), row["unit"]),
                "detail": "Sold but not in stock or on order. Buy at least {} {}.".format(_qty(max(row["short"], row["reorder_quantity"])), row["unit"]),
                "link": "/fulfilment?lane=short", "record": {"type": "product", "id": row["product_id"]},
            })
        elif "low_cover" in row["flags"]:
            found.append({
                "kind": "low_cover", "severity": "warning",
                "title": "{} runs out in about {} days".format(row["name"], int(row["days_of_cover"] or 0)),
                "detail": "Selling {} {} a day; reorder {} {}.".format(_qty(row["daily_sales_rate"]), row["unit"], _qty(row["reorder_quantity"]), row["unit"]),
                "link": "/products/{}".format(row["product_id"]), "record": {"type": "product", "id": row["product_id"]},
            })
        if "dead" in row["flags"] and row["stock_value"] > 0:
            found.append({
                "kind": "dead_stock", "severity": "info",
                "title": "{} has not sold for {}".format(row["name"], "{} days".format(row["days_since_last_sale"]) if row["days_since_last_sale"] is not None else "ever"),
                "detail": "{} {} worth {} sitting idle.".format(_qty(row["physical"]), row["unit"], _money(row["stock_value"])),
                "link": "/products/{}".format(row["product_id"]), "record": {"type": "product", "id": row["product_id"]},
            })
    for po in supplier_insights(session)["late_purchase_orders"]:
        found.append({
            "kind": "late_purchase", "severity": "warning",
            "title": "{} from {} is {} days late".format(po["po_number"], po["supplier_name"], po["days_late"]),
            "detail": "{} still due. Chase the supplier.".format(_money(po["still_due_value"])),
            "link": "/purchase-orders/{}".format(po["purchase_order_id"]), "record": {"type": "purchase_order", "id": po["purchase_order_id"]},
        })
    funnel = enquiry_funnel(session)
    for row in funnel["stale"]:
        if row["has_open_follow_up"]:
            continue
        found.append({
            "kind": "stale_enquiry", "severity": "warning" if row["value"] > 0 else "info",
            "title": "{} for {} untouched for {} days".format(row["enquiry_number"], row["customer_name"], row["days_idle"]),
            "detail": "Quote worth {} with no follow-up planned.".format(_money(row["value"])),
            "link": "/enquiries/{}".format(row["enquiry_id"]), "record": {"type": "enquiry", "id": row["enquiry_id"]},
            "suggested_action": {"tool": "create_follow_up", "enquiry_id": row["enquiry_id"], "customer_id": row["customer_id"]},
        })
    now = _now()
    waiting = session.execute(
        select(SalesOrder.id, SalesOrder.order_number, SalesOrder.created_at, Customer.name)
        .join(Customer, SalesOrder.customer_id == Customer.id)
        .where(SalesOrder.status.in_([OrderStatus.PENDING, OrderStatus.PARTIALLY_FULFILLED]),
               SalesOrder.created_at < now - timedelta(days=WAITING_ORDER_DAYS))
        .order_by(SalesOrder.created_at)
    ).all()
    for order_id, number, created, customer in waiting:
        found.append({
            "kind": "waiting_order", "severity": "warning",
            "title": "{} for {} waiting {} days".format(number, customer, (now - created.astimezone(_zone())).days),
            "detail": "Part of this order has not been delivered.",
            "link": "/orders/{}".format(order_id), "record": {"type": "order", "id": order_id},
        })
    overdue = session.execute(
        select(Task).where(Task.status == TaskStatus.OPEN, Task.due_date < _start_of_day(now.date())).order_by(Task.due_date)
    ).scalars().all()
    for task in overdue:
        found.append({
            "kind": "overdue_follow_up", "severity": "warning",
            "title": "Overdue: {}".format(task.title),
            "detail": "Was due {}.".format(task.due_date.astimezone(_zone()).date().isoformat()),
            "link": "/tasks", "record": {"type": "task", "id": task.id},
        })
    from . import finance

    money = finance.receivables(session)
    for row in money["parties"]:
        if row["overdue"] > 0:
            found.append({
                "kind": "overdue_receivable", "severity": "critical" if row["oldest_overdue_days"] > 30 else "warning",
                "title": "{} owes {} overdue".format(row["name"], _money(row["overdue"])),
                "detail": "Oldest invoice {} days past due; {} open in all.".format(row["oldest_overdue_days"], _money(row["open"])),
                "link": "/customers/{}?tab=account".format(row["party_id"]), "record": {"type": "customer", "id": row["party_id"]},
            })
        if row.get("over_credit_limit"):
            found.append({
                "kind": "over_credit_limit", "severity": "warning",
                "title": "{} is over their credit limit".format(row["name"]),
                "detail": "Owes {} against a limit of {}.".format(_money(row["open"]), _money(row["credit_limit"] or 0)),
                "link": "/customers/{}?tab=account".format(row["party_id"]), "record": {"type": "customer", "id": row["party_id"]},
            })
    bills = finance.payables(session)
    for doc in bills["overdue"][:10]:
        found.append({
            "kind": "overdue_payable", "severity": "warning",
            "title": "Pay {} {} for {}".format(doc["party_name"], _money(doc["open"]), doc["number"]),
            "detail": "{} days past due.".format(doc["days_overdue"]),
            "link": "/suppliers/{}?tab=account".format(doc["party_id"]), "record": {"type": "supplier", "id": doc["party_id"]},
        })
    for row in stock["products"]:
        if "below_minimum" in row["flags"]:
            found.append({
                "kind": "below_minimum", "severity": "warning",
                "title": "{} is below its minimum stock".format(row["name"]),
                "detail": "{} {} against a minimum of {}. {}.".format(_qty(row["stock_figure"]), row["unit"], _qty(row["reorder_level"]), row["action"]["text"]),
                "link": "/products/{}".format(row["product_id"]), "record": {"type": "product", "id": row["product_id"]},
            })
    found.sort(key=lambda alert: SEVERITY_ORDER[alert["severity"]])
    for index, alert in enumerate(found):
        alert["id"] = "{}-{}".format(alert["kind"], index)
    counts = defaultdict(int)
    for alert in found:
        counts[alert["severity"]] += 1
    return {"counts": dict(counts), "alerts": found}


def briefing(session: Session) -> Dict[str, Any]:
    """Today at a glance: what happened, what is due, what to act on."""
    from . import tasks as task_service

    today = overview(session, "today")
    month = overview(session, "month")
    alert_data = alerts(session)
    stock = inventory_health(session)["totals"]
    funnel = enquiry_funnel(session)
    from . import finance

    finance_r, finance_p = finance.receivables(session), finance.payables(session)
    return {
        "date": _now().date(),
        "today": today["current"],
        "yesterday": today["previous"],
        "month": month["current"],
        "month_change_percent": month["change_percent"],
        "follow_ups": task_service.open_counts(session),
        "stock": {
            "value": stock["stock_value"],
            "capital_at_risk": stock["capital_at_risk"],
            "products_to_reorder": stock["reorder_products"],
            "reorder_value": stock["reorder_value"],
        },
        "enquiries": {
            "open": funnel["counts"]["open"],
            "pipeline_value": funnel["open_pipeline_value"],
            "stale_without_follow_up": funnel["stale_without_follow_up"],
        },
        "receivables": {key: finance_r["totals"][key] for key in ("open", "overdue")},
        "payables": {key: finance_p["totals"][key] for key in ("open", "overdue")},
        "target": month.get("target"),
        "alert_counts": alert_data["counts"],
        "top_alerts": alert_data["alerts"][:8],
    }


def _qty(value: float) -> str:
    return ("{:,.3f}".format(value)).rstrip("0").rstrip(".")


def _money(value: float) -> str:
    return "₹{:,.2f}".format(value)


# ---------------------------------------------------------------------------
# Line-level facts, the basis of the explorer and product intelligence
# ---------------------------------------------------------------------------

MEASURES = {
    "booked_value": "Value of orders placed (net of discounts)",
    "quantity_booked": "Quantity ordered (less cancelled)",
    "orders": "Number of orders",
    "discount": "Discount given (MRP less agreed price)",
    "revenue": "Value of goods delivered",
    "quantity_delivered": "Quantity delivered",
    "cost_of_goods": "FIFO cost of goods delivered",
    "gross_profit": "Revenue less cost of goods",
}
EXPLORE_GROUPS = ("product", "category", "customer", "month", "week", "weekday", "day", "none")
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _booked_lines(session: Session, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    rows = session.execute(
        select(SalesOrder.id, SalesOrder.created_at, SalesOrder.customer_id, Customer.name, Product.id, Product.name,
               Product.category, SalesOrderItem.quantity_ordered - SalesOrderItem.quantity_cancelled,
               SalesOrderItem.unit_price_net, SalesOrderItem.unit_price)
        .join(SalesOrderItem, SalesOrderItem.order_id == SalesOrder.id)
        .join(Customer, SalesOrder.customer_id == Customer.id)
        .join(Product, SalesOrderItem.product_id == Product.id)
        .where(SalesOrder.status != OrderStatus.CANCELLED, SalesOrder.created_at >= start, SalesOrder.created_at < end)
    ).all()
    out = []
    for order_id, created, customer_id, customer, product_id, product, category, qty, net, price in rows:
        qty = float(qty or 0)
        out.append({"when": created, "order_id": order_id, "customer_id": customer_id, "customer": customer,
                    "product_id": product_id, "product": product, "category": category or "(none)",
                    "booked_value": qty * float(net or 0), "quantity_booked": qty,
                    "discount": max(0.0, qty * (float(price or 0) - float(net or 0)))})
    return out


def _delivered_lines(session: Session, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    cost = dict(
        session.execute(
            select(StockAllocation.customer_delivery_item_id, func.sum(StockAllocation.cost_amount))
            .where(StockAllocation.customer_delivery_item_id.is_not(None))
            .group_by(StockAllocation.customer_delivery_item_id)
        ).all()
    )
    rows = session.execute(
        select(CustomerDeliveryItem.id, CustomerDelivery.created_at, CustomerDelivery.customer_id, Customer.name,
               Product.id, Product.name, Product.category, CustomerDeliveryItem.quantity, SalesOrderItem.unit_price_net)
        .join(CustomerDelivery, CustomerDeliveryItem.customer_delivery_id == CustomerDelivery.id)
        .join(SalesOrderItem, CustomerDeliveryItem.order_item_id == SalesOrderItem.id)
        .join(Customer, CustomerDelivery.customer_id == Customer.id)
        .join(Product, CustomerDeliveryItem.product_id == Product.id)
        .where(CustomerDelivery.created_at >= start, CustomerDelivery.created_at < end)
    ).all()
    out = []
    for item_id, created, customer_id, customer, product_id, product, category, qty, net in rows:
        qty = float(qty or 0)
        revenue = qty * float(net or 0)
        cogs = float(cost.get(item_id) or 0)
        out.append({"when": created, "customer_id": customer_id, "customer": customer, "product_id": product_id,
                    "product": product, "category": category or "(none)", "revenue": revenue, "quantity_delivered": qty,
                    "cost_of_goods": cogs, "gross_profit": revenue - cogs})
    return out


def _key(row: Dict[str, Any], group_by: str) -> Tuple[str, str, Optional[str]]:
    """(key, label, link) for a line under a grouping."""
    local = row["when"].astimezone(_zone())
    if group_by == "product":
        return str(row["product_id"]), row["product"], "/products/{}".format(row["product_id"])
    if group_by == "customer":
        return str(row["customer_id"]), row["customer"], "/customers/{}".format(row["customer_id"])
    if group_by == "category":
        return row["category"], row["category"], None
    if group_by == "month":
        return local.strftime("%Y-%m"), local.strftime("%b %Y"), None
    if group_by == "week":
        monday = (local - timedelta(days=local.weekday())).date()
        return monday.isoformat(), "Week of {}".format(monday.strftime("%d %b")), None
    if group_by == "weekday":
        return str(local.weekday()), WEEKDAYS[local.weekday()], None
    if group_by == "day":
        return local.date().isoformat(), local.date().isoformat(), None
    return "all", "All", None


def _aggregate(booked: List[Dict[str, Any]], delivered: List[Dict[str, Any]], group_by: str) -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}

    def entry(row):
        key, label, link = _key(row, group_by)
        if key not in groups:
            groups[key] = {"key": key, "label": label, "link": link, "_orders": set(),
                           **{measure: 0.0 for measure in MEASURES if measure != "orders"}}
        return groups[key]

    for row in booked:
        item = entry(row)
        item["booked_value"] += row["booked_value"]
        item["quantity_booked"] += row["quantity_booked"]
        item["discount"] += row["discount"]
        item["_orders"].add(row["order_id"])
    for row in delivered:
        item = entry(row)
        for measure in ("revenue", "quantity_delivered", "cost_of_goods", "gross_profit"):
            item[measure] += row[measure]
    for item in groups.values():
        item["orders"] = len(item.pop("_orders"))
        for measure in MEASURES:
            item[measure] = round(item[measure], 3 if measure.startswith("quantity") else 2)
        item["margin_percent"] = _pct(item["gross_profit"], item["revenue"])
    return groups


def _apply_filters(lines: List[Dict[str, Any]], categories, product_ids, customer_ids) -> List[Dict[str, Any]]:
    out = lines
    if categories:
        out = [row for row in out if row["category"] in categories]
    if product_ids:
        out = [row for row in out if str(row["product_id"]) in product_ids]
    if customer_ids:
        out = [row for row in out if str(row["customer_id"]) in customer_ids]
    return out


def explore(
    session: Session,
    measure: str = "booked_value",
    group_by: str = "month",
    period: str = "last_90",
    start: Optional[date] = None,
    end: Optional[date] = None,
    categories: Optional[List[str]] = None,
    product_ids: Optional[List[str]] = None,
    customer_ids: Optional[List[str]] = None,
    sort: str = "value",
    limit: int = 100,
) -> Dict[str, Any]:
    """Any measure by any grouping over any window, with the previous window
    of the same length alongside for comparison."""
    if measure not in MEASURES:
        raise ValidationError("measure must be one of: {}.".format(", ".join(MEASURES)))
    if group_by not in EXPLORE_GROUPS:
        raise ValidationError("group_by must be one of: {}.".format(", ".join(EXPLORE_GROUPS)))
    bounds = period_bounds(period, start, end)
    current = _aggregate(
        _apply_filters(_booked_lines(session, bounds["start"], bounds["end"]), categories, product_ids, customer_ids),
        _apply_filters(_delivered_lines(session, bounds["start"], bounds["end"]), categories, product_ids, customer_ids),
        group_by,
    )
    previous = _aggregate(
        _apply_filters(_booked_lines(session, bounds["prev_start"], bounds["prev_end"]), categories, product_ids, customer_ids),
        _apply_filters(_delivered_lines(session, bounds["prev_start"], bounds["prev_end"]), categories, product_ids, customer_ids),
        group_by,
    )
    time_based = group_by in ("month", "week", "day", "weekday")
    rows = []
    keys = set(current) | (set() if time_based else set(previous))
    for key in keys:
        item = current.get(key) or dict(previous[key], **{m: 0.0 for m in MEASURES}, margin_percent=None)
        before = previous.get(key, {}).get(measure, 0.0) if not time_based else None
        rows.append(dict(item, value=item[measure], previous=before, change_percent=_change(item[measure], before) if before else None))
    if time_based:
        rows.sort(key=lambda row: row["key"])
    elif sort == "name":
        rows.sort(key=lambda row: row["label"])
    else:
        rows.sort(key=lambda row: -row["value"])
    total = round(sum(item[measure] for item in current.values()), 2)
    total_previous = round(sum(item[measure] for item in previous.values()), 2)
    running = 0.0
    for row in rows:
        row["share_percent"] = _pct(row["value"], total) if total else None
        if not time_based:
            running += row["value"]
            row["cumulative_percent"] = _pct(running, total) if total else None
    return {
        "measure": measure,
        "measure_label": MEASURES[measure],
        "group_by": group_by,
        "start": bounds["start"].date(),
        "end": (bounds["end"] - timedelta(days=1)).date(),
        "previous_start": bounds["prev_start"].date(),
        "previous_end": (bounds["prev_end"] - timedelta(seconds=1)).date(),
        "total": total,
        "total_previous": total_previous,
        "change_percent": _change(total, total_previous),
        "rows": rows[:limit],
        "row_count": len(rows),
    }


def heatmap(session: Session, measure: str = "booked_value", weeks: int = 12) -> Dict[str, Any]:
    """The measure by weekday and week, to see the business's rhythm."""
    if measure not in MEASURES:
        raise ValidationError("measure must be one of: {}.".format(", ".join(MEASURES)))
    weeks = max(4, min(weeks, 52))
    today = _now().date()
    first = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)
    start, end = _start_of_day(first), _start_of_day(today + timedelta(days=1))
    booked_side = measure in ("booked_value", "quantity_booked", "orders", "discount")
    lines = _booked_lines(session, start, end) if booked_side else _delivered_lines(session, start, end)
    cells: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for row in lines:
        local = row["when"].astimezone(_zone())
        week = (local.date() - timedelta(days=local.weekday())).isoformat()
        cell = cells.setdefault((week, local.weekday()), {"value": 0.0, "_orders": set()})
        if measure == "orders":
            cell["_orders"].add(row["order_id"])
        else:
            cell["value"] += row[measure]
    week_keys = [(first + timedelta(weeks=i)).isoformat() for i in range(weeks)]
    matrix = []
    for week in week_keys:
        values = []
        for day in range(7):
            cell = cells.get((week, day))
            values.append(round(len(cell["_orders"]) if measure == "orders" and cell else (cell["value"] if cell else 0.0), 2))
        matrix.append({"week": week, "values": values})
    by_weekday = [round(sum(week["values"][day] for week in matrix), 2) for day in range(7)]
    return {"measure": measure, "weekdays": WEEKDAYS, "weeks": matrix, "by_weekday": by_weekday,
            "busiest_weekday": WEEKDAYS[by_weekday.index(max(by_weekday))] if any(by_weekday) else None}


# ---------------------------------------------------------------------------
# Product intelligence
# ---------------------------------------------------------------------------

MIN_ORDERS_FOR_BASKETS = 20


def product_intelligence(session: Session, period: str = "last_90", start: Optional[date] = None, end: Optional[date] = None) -> Dict[str, Any]:
    """Which products drive the business and which hold it back: growth,
    Pareto (ABC) class, margin quadrant, enquiry conversion, and products
    bought together (only when there are enough orders to say)."""
    product_view = explore(session, "booked_value", "product", period, start, end, limit=10_000)
    bounds = period_bounds(period, start, end)
    stock = {str(row["product_id"]): row for row in inventory_health(session)["products"]}
    rows = product_view["rows"]
    revenues = sorted(row["revenue"] for row in rows if row["revenue"] > 0)
    margins = sorted(row["margin_percent"] for row in rows if row["margin_percent"] is not None)
    median_revenue = revenues[len(revenues) // 2] if revenues else 0
    median_margin = margins[len(margins) // 2] if margins else None

    enquiry_rows = session.execute(
        select(CustomerEnquiryItem.product_id, CustomerEnquiry.status, func.count(CustomerEnquiryItem.id))
        .join(CustomerEnquiry, CustomerEnquiryItem.enquiry_id == CustomerEnquiry.id)
        .where(CustomerEnquiry.created_at >= bounds["start"], CustomerEnquiry.created_at < bounds["end"])
        .group_by(CustomerEnquiryItem.product_id, CustomerEnquiry.status)
    ).all()
    enquiries: Dict[str, Dict[str, int]] = defaultdict(lambda: {"OPEN": 0, "CONVERTED": 0, "LOST": 0})
    for product_id, status, count in enquiry_rows:
        enquiries[str(product_id)][status.value] += count

    out = []
    for row in rows:
        key = row["key"]
        if row["booked_value"] >= (row.get("previous") or 0) * 1.2 and row.get("previous"):
            growth = "growing"
        elif row.get("previous") and row["booked_value"] <= row["previous"] * 0.8:
            growth = "declining"
        elif not row.get("previous"):
            growth = "new" if row["booked_value"] else "none"
        else:
            growth = "steady"
        # ABC: what came before this product decides its class, so the products
        # that make up the first 80% of value are A, the next 15% B, the rest C.
        before_share = (row.get("cumulative_percent") or 0) - (row.get("share_percent") or 0)
        abc = "A" if before_share < 80 else "B" if before_share < 95 else "C"
        quadrant = None
        if row["revenue"] > 0 and row["margin_percent"] is not None and median_margin is not None:
            high_rev = row["revenue"] >= median_revenue
            high_margin = row["margin_percent"] >= median_margin
            quadrant = {(True, True): "star", (True, False): "volume_low_margin",
                        (False, True): "niche_high_margin", (False, False): "weak"}[(high_rev, high_margin)]
        enquiry = enquiries.get(key, {"OPEN": 0, "CONVERTED": 0, "LOST": 0})
        decided = enquiry["CONVERTED"] + enquiry["LOST"]
        health = stock.get(key, {})
        out.append({
            "product_id": key, "name": row["label"], "booked_value": row["booked_value"], "previous_booked_value": row.get("previous"),
            "growth_percent": row.get("change_percent"), "growth": growth, "revenue": row["revenue"],
            "gross_profit": row["gross_profit"], "margin_percent": row["margin_percent"], "discount": row["discount"],
            "share_percent": row.get("share_percent"), "abc_class": abc, "quadrant": quadrant,
            "enquiries": sum(enquiry.values()), "enquiries_won": enquiry["CONVERTED"], "enquiries_lost": enquiry["LOST"],
            "enquiry_conversion_percent": _pct(enquiry["CONVERTED"], decided),
            "stock_flags": health.get("flags", []), "short": health.get("short", 0.0), "category": health.get("category"),
        })
    # Products asked about a lot but rarely bought.
    weak_conversion = [row for row in out if row["enquiries"] >= 2 and (row["enquiry_conversion_percent"] or 0) < 40]

    orders = session.execute(
        select(SalesOrderItem.order_id, SalesOrderItem.product_id, Product.name)
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .join(Product, SalesOrderItem.product_id == Product.id)
        .where(SalesOrder.status != OrderStatus.CANCELLED)
    ).all()
    baskets: Dict[Any, set] = defaultdict(set)
    names = {}
    for order_id, product_id, name in orders:
        baskets[order_id].add(product_id)
        names[product_id] = name
    multi = [basket for basket in baskets.values() if len(basket) > 1]
    pairs: Dict[Tuple[Any, Any], int] = defaultdict(int)
    for basket in multi:
        items = sorted(basket, key=str)
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                pairs[(items[i], items[j])] += 1
    together = None
    if len(multi) >= MIN_ORDERS_FOR_BASKETS:
        together = [{"a": names[a], "a_id": a, "b": names[b], "b_id": b, "orders": n}
                    for (a, b), n in sorted(pairs.items(), key=lambda item: -item[1])[:15] if n >= 2]
    return {
        "start": product_view["start"], "end": product_view["end"],
        "median_revenue": round(median_revenue, 2), "median_margin_percent": median_margin,
        "products": out,
        "weak_enquiry_conversion": weak_conversion,
        "bought_together": together,
        "bought_together_note": None if together is not None else
            "Needs at least {} orders with more than one product; there are {}.".format(MIN_ORDERS_FOR_BASKETS, len(multi)),
    }


# ---------------------------------------------------------------------------
# Customer segments
# ---------------------------------------------------------------------------


def customer_segments(session: Session) -> Dict[str, Any]:
    """Customers grouped by how recently, how often and how much they buy, with
    what they owe. Lifetime value is an estimate and labelled as one."""
    from . import finance

    base = customer_insights(session, limit=10_000)
    owed = {str(row["party_id"]): row for row in finance.receivables(session)["parties"]}
    dates = defaultdict(list)
    for customer_id, created in session.execute(
        select(SalesOrder.customer_id, SalesOrder.created_at).where(SalesOrder.status != OrderStatus.CANCELLED).order_by(SalesOrder.created_at)
    ).all():
        dates[customer_id].append(created)
    values = sorted((row["booked_value"] for row in base["customers"]), reverse=True)
    top_cut = values[max(0, len(values) // 5 - 1)] if values else 0
    rows = []
    counts: Dict[str, int] = defaultdict(int)
    now = _now()
    for row in base["customers"]:
        history = dates.get(row["customer_id"], [])
        gaps = [(b - a).days for a, b in zip(history, history[1:])]
        frequency = round(sum(gaps) / len(gaps), 1) if gaps else None
        span = (history[-1] - history[0]).days if len(history) > 1 else 0
        first_age = (now - history[0]).days if history else None
        recency = row["days_since_last_order"]
        orders = row["orders"]
        if first_age is not None and (first_age <= 30 or (orders == 1 and first_age <= 60)):
            segment = "new"
        elif orders >= 3 and recency <= 30 and row["booked_value"] >= top_cut:
            segment = "champion"
        elif orders >= 2 and recency <= 60:
            segment = "loyal"
        elif orders >= 2 and recency <= 120:
            segment = "at_risk"
        elif recency > DORMANT_CUSTOMER_DAYS:
            segment = "dormant"
        else:
            segment = "occasional"
        counts[segment] += 1
        annual = None
        if span >= 30:
            annual = round(row["average_order_value"] * (365 / max(frequency or 365, 1)), 2)
        money_owed = owed.get(str(row["customer_id"]), {})
        rows.append(dict(row, segment=segment, average_days_between_orders=frequency,
                         estimated_annual_value=annual, open_receivable=money_owed.get("open", 0.0),
                         overdue_receivable=money_owed.get("overdue", 0.0), over_credit_limit=money_owed.get("over_credit_limit", False)))
    month_rows: Dict[str, Dict[str, int]] = defaultdict(lambda: {"new": 0, "returning": 0})
    for customer_id, history in dates.items():
        seen_months = set()
        for index, created in enumerate(history):
            month = created.astimezone(_zone()).strftime("%Y-%m")
            if month in seen_months:
                continue
            seen_months.add(month)
            month_rows[month]["new" if index == 0 else "returning"] += 1
    repeaters = sum(1 for history in dates.values() if len(history) > 1)
    return {
        "segments": dict(counts),
        "customers": rows,
        "new_vs_returning": [{"month": month, **values} for month, values in sorted(month_rows.items())],
        "repeat_rate_percent": _pct(repeaters, len(dates)),
        "note": "Estimated annual value = average order × orders a year at the customer's own buying frequency; shown only with at least 30 days of history.",
    }
