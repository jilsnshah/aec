"""Stock adjustments and physical stock counts.

A count compares what is on the shelf with the books and posts the difference;
an adjustment records damage, loss or stock found. Both keep the three stock
truths in step: the ledger (a movement), the cached physical stock, and the
FIFO cost layers.

* A decrease draws from the oldest cost layers, so the loss is valued at what
  those units cost. If the shelf now holds less than is set aside for
  customers, the newest orders lose their reservation first (they become
  short again) so the customers who ordered earliest keep their goods.
* An increase opens a cost layer at the current average cost (or the last
  purchase price) and, like any stock arriving, is reserved for customers
  already waiting, oldest order first.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..database import begin_write
from ..errors import NotFoundError, ValidationError
from ..models import (
    AllocationSource,
    MovementType,
    OrderStatus,
    Product,
    SalesOrder,
    SalesOrderItem,
    StockAdjustment,
    StockCostLayer,
)
from ..numeric import ZERO, ZERO_MONEY, money, quantity as to_quantity, unit_cost
from . import costing, reservations
from .common import count_matching, lock_product, next_document_number, record_movement, windowed

REASONS = {
    "count": "Stock count",
    "damaged": "Damaged",
    "lost": "Lost or stolen",
    "expired": "Expired",
    "found": "Found",
    "sample": "Sample or own use",
    "correction": "Correction",
}
ADJUSTMENT_COUNTER = "stock_adjustment"
COUNT_COUNTER = "stock_count"


def _draw_layers(session: Session, product: Product, amount: Decimal, warehouse_id: Optional[uuid.UUID] = None) -> Decimal:
    """Take ``amount`` out of the oldest cost layers (of one warehouse if given); return its cost."""
    remaining = amount
    value = ZERO_MONEY
    for layer in costing._open_layers(session, product.id, warehouse_id):
        if remaining <= ZERO:
            break
        take = min(layer.quantity_remaining, remaining)
        layer.quantity_remaining = layer.quantity_remaining - take
        value = value + money(take * layer.unit_cost)
        remaining = remaining - take
    if remaining > ZERO:  # layers short of the ledger: value at the last price
        value = value + money(remaining * (product.last_purchase_price or ZERO))
    return value


def _release_newest(session: Session, product: Product, amount: Decimal) -> Decimal:
    """Take back ``amount`` of reserved stock, newest orders first."""
    lines = session.execute(
        select(SalesOrderItem)
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .where(SalesOrderItem.product_id == product.id, SalesOrderItem.quantity_reserved > 0, SalesOrder.status != OrderStatus.CANCELLED)
        .order_by(SalesOrder.created_at.desc(), SalesOrderItem.line_number.desc())
    ).scalars().all()
    released = ZERO
    for line in lines:
        if released >= amount:
            break
        take = min(line.quantity_reserved, amount - released)
        released = released + sum((qty for _, qty in reservations.consume(session, line, take)), ZERO)
    return released


def _post_one(session: Session, line: Dict[str, Any], count_number: Optional[str], user_id: Optional[uuid.UUID]) -> Optional[StockAdjustment]:
    try:
        product_id = uuid.UUID(str(line.get("product_id")))
    except (TypeError, ValueError):
        raise ValidationError("Choose a product for every line.")
    product = lock_product(session, product_id)
    reason = line.get("reason") or ("count" if line.get("counted_quantity") is not None else "correction")
    if reason not in REASONS:
        raise ValidationError("Unknown reason '{}'.".format(reason))
    from . import warehouses as warehouse_service

    where = warehouse_service.resolve(session, line.get("warehouse_id")) if line.get("warehouse_id") else None
    system = warehouse_service.on_hand(session, product.id, where) if where else product.physical_stock - warehouse_service.on_hand(session, product.id, warehouse_service.transit_id(session))
    counted = None
    if line.get("counted_quantity") is not None and line.get("counted_quantity") != "":
        counted = to_quantity(line["counted_quantity"], "Counted quantity")
        if counted < ZERO:
            raise ValidationError("A counted quantity cannot be negative.")
        change = counted - system
    else:
        change = to_quantity(line.get("quantity_change"), "Quantity change")
    if change == ZERO:
        return None
    if system + change < ZERO:
        raise ValidationError("{} has only {} in stock{}; it cannot go below zero.".format(product.name, system, " there" if where else ""))
    note = (line.get("note") or "").strip() or None
    number = next_document_number(session, ADJUSTMENT_COUNTER, "ADJ")
    adjustment = StockAdjustment(
        number=number, count_number=count_number, product_id=product.id, reason=reason, warehouse_id=where,
        system_quantity=system, counted_quantity=counted, quantity_change=change, note=note, created_by_id=user_id,
    )
    session.add(adjustment)
    session.flush()
    label = "{}: {}".format(REASONS[reason], note) if note else REASONS[reason]
    if change < ZERO:
        lost = -change
        reserved = reservations.reserved_for_product(session, product.id)
        free = product.physical_stock - reserved
        if lost > free:
            adjustment.released_to_short = _release_newest(session, product, lost - max(free, ZERO))
        value = _draw_layers(session, product, lost, where)
        adjustment.value_change = -value
        adjustment.unit_cost = unit_cost(value / lost) if lost > ZERO else ZERO
        record_movement(session, product, MovementType.ADJUSTMENT, change, "stock_adjustment", adjustment.id, label, warehouse_id=where)
    else:
        given = line.get("unit_cost")
        cost = unit_cost(given, "Unit cost") if given not in (None, "") else None
        if cost is None:
            cost = costing.stock_valuation(session, product.id)["average_cost"] or product.last_purchase_price or ZERO
        into = where or warehouse_service.default_id(session)
        adjustment.warehouse_id = into
        layer = StockCostLayer(product_id=product.id, source=MovementType.ADJUSTMENT, source_id=adjustment.id,
                               unit_cost=cost, quantity=change, quantity_remaining=change, note=label, warehouse_id=into)
        session.add(layer)
        adjustment.unit_cost = cost
        adjustment.value_change = money(change * cost)
        record_movement(session, product, MovementType.ADJUSTMENT, change, "stock_adjustment", adjustment.id, label, warehouse_id=into)
        waiting = reservations.unallocated_total(reservations.fifo_unallocated_items(session, product.id))
        if waiting > ZERO:
            reservations.allocate_available_stock(session, product, min(change, waiting), AllocationSource.ADJUSTMENT, label="adjustment")
    session.flush()
    return adjustment


def post(session: Session, lines: Iterable[Dict[str, Any]], user_id: Optional[uuid.UUID] = None, as_count: bool = False) -> Dict[str, Any]:
    """Post adjustments (or a count) in one transaction; all or nothing."""
    begin_write(session)
    lines = list(lines)
    if not lines:
        raise ValidationError("Add at least one product.")
    seen = set()
    for line in lines:
        key = str(line.get("product_id"))
        if key in seen:
            raise ValidationError("Each product can appear only once in a count.")
        seen.add(key)
    try:
        count_number = next_document_number(session, COUNT_COUNTER, "CNT") if as_count else None
        posted = [a for a in (_post_one(session, line, count_number, user_id) for line in lines) if a is not None]
        if posted:
            from ..models import User
            from .controls import log

            user = session.get(User, user_id) if user_id else None
            value = sum((a.value_change for a in posted), ZERO_MONEY)
            log(session, user, "stock_count" if as_count else "stock_adjustment", "stock", count_number or posted[0].number,
                "{} {} product(s), value {:+,.2f} at cost".format("Counted; adjusted" if as_count else "Adjusted", len(posted), value),
                {"numbers": [a.number for a in posted]})
        session.commit()
    except Exception:
        session.rollback()
        raise
    rows = [view(a) for a in posted]
    return {
        "count_number": count_number,
        "checked": len(lines),
        "adjusted": len(rows),
        "matched": len(lines) - len(rows),
        "value_change": float(sum((a.value_change for a in posted), ZERO_MONEY)),
        "released_to_short": float(sum((a.released_to_short for a in posted), ZERO)),
        "adjustments": rows,
    }


def view(adjustment: StockAdjustment) -> Dict[str, Any]:
    product = adjustment.product
    return {
        "id": adjustment.id,
        "number": adjustment.number,
        "count_number": adjustment.count_number,
        "product_id": adjustment.product_id,
        "product_name": product.name if product else None,
        "product_sku": product.sku if product else None,
        "unit": product.unit_of_measure if product else None,
        "reason": adjustment.reason,
        "reason_label": REASONS.get(adjustment.reason, adjustment.reason),
        "system_quantity": float(adjustment.system_quantity),
        "counted_quantity": float(adjustment.counted_quantity) if adjustment.counted_quantity is not None else None,
        "quantity_change": float(adjustment.quantity_change),
        "unit_cost": float(adjustment.unit_cost),
        "value_change": float(adjustment.value_change),
        "released_to_short": float(adjustment.released_to_short),
        "note": adjustment.note,
        "created_at": adjustment.created_at,
    }


def _filters(stmt, product_id=None, reason=None, count_number=None):
    if product_id:
        stmt = stmt.where(StockAdjustment.product_id == product_id)
    if reason:
        stmt = stmt.where(StockAdjustment.reason == reason)
    if count_number:
        stmt = stmt.where(StockAdjustment.count_number == count_number)
    return stmt


def list_adjustments(session: Session, limit: int = 100, offset: int = 0, **filters: Any) -> Dict[str, Any]:
    stmt = _filters(select(StockAdjustment), **filters).options(joinedload(StockAdjustment.product)).order_by(StockAdjustment.created_at.desc())
    items = session.execute(windowed(stmt, limit, offset)).scalars().all()
    total = count_matching(session, _filters(select(StockAdjustment.id), **filters))
    summary = session.execute(
        _filters(select(StockAdjustment.reason, func.count(StockAdjustment.id), func.sum(StockAdjustment.value_change)), **filters).group_by(StockAdjustment.reason)
    ).all()
    return {
        "items": [view(a) for a in items],
        "total": total,
        "by_reason": [{"reason": r, "label": REASONS.get(r, r), "count": c, "value_change": float(v or 0)} for r, c, v in summary],
    }


def count_sheet(session: Session, category: Optional[str] = None) -> List[Dict[str, Any]]:
    """Products to count, with the quantity the books expect."""
    stmt = select(Product).where(Product.is_active.is_(True)).order_by(Product.category.nulls_last(), Product.name)
    if category:
        stmt = stmt.where(Product.category == category)
    last = dict(session.execute(
        select(StockAdjustment.product_id, func.max(StockAdjustment.created_at)).where(StockAdjustment.reason == "count").group_by(StockAdjustment.product_id)
    ).all())
    valuation = costing.stock_valuation_map(session)
    reserved = reservations.reserved_map(session)
    return [
        {"product_id": p.id, "name": p.name, "sku": p.sku, "unit": p.unit_of_measure, "category": p.category,
         "system_quantity": float(p.physical_stock), "reserved": float(reserved.get(p.id, ZERO)),
         "average_cost": float(valuation.get(p.id, {}).get("average_cost") or p.last_purchase_price or 0),
         "last_counted": last.get(p.id)}
        for p in session.execute(stmt).scalars()
    ]


def get(session: Session, adjustment_id: uuid.UUID) -> Dict[str, Any]:
    adjustment = session.get(StockAdjustment, adjustment_id)
    if adjustment is None:
        raise NotFoundError("Adjustment not found.")
    return view(adjustment)
