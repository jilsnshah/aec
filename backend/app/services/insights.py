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
    revenue_f, cogs_f = _f(revenue), _f(cogs)
    profit = round(revenue_f - cogs_f, 2)
    decided = converted + lost
    return {
        "orders": booked[0],
        "booked_value": _f(booked[1]),
        "average_order_value": _f(Decimal(booked[1]) / booked[0]) if booked[0] else 0.0,
        "deliveries": deliveries,
        "revenue": revenue_f,
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
    return {
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
        cover_days = round(float(max(ZERO, free)) / rate, 1) if rate > 0 else None
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
        reorder = 0.0
        if rate > 0 or position < 0:
            need = rate * TARGET_COVER_DAYS - float(position)
            reorder = max(0.0, need, -float(position))
            reorder = float(math.ceil(reorder)) if reorder else 0.0
        unit_cost = _f(product.last_purchase_price) or (round(value / float(physical), 2) if physical > 0 else 0.0)
        if reorder > 0:
            flags.append("reorder")

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

    for key in ("stock_value", "dead_stock_value", "slow_stock_value", "reorder_value"):
        totals[key] = round(totals[key], 2)
    totals["age_value"] = {name: round(value, 2) for name, value in totals["age_value"].items()}
    totals["capital_at_risk"] = round(totals["dead_stock_value"] + totals["slow_stock_value"], 2)
    rows.sort(key=lambda row: (-len(row["flags"]), -row["stock_value"]))
    return {
        "as_of": now,
        "thresholds": {
            "dead_stock_days": DEAD_STOCK_DAYS,
            "slow_cover_days": SLOW_COVER_DAYS,
            "low_cover_days": LOW_COVER_DAYS,
            "target_cover_days": TARGET_COVER_DAYS,
        },
        "totals": totals,
        "products": rows,
    }


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
        "alert_counts": alert_data["counts"],
        "top_alerts": alert_data["alerts"][:8],
    }


def _qty(value: float) -> str:
    return ("{:,.3f}".format(value)).rstrip("0").rstrip(".")


def _money(value: float) -> str:
    return "₹{:,.2f}".format(value)
