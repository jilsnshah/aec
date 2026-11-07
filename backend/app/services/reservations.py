"""Reserving stock for customer orders, and releasing it when goods go out.

Four quantities are tracked per sales order line and must not be confused:

* **ordered** -- what the customer asked for;
* **delivered** (``quantity_fulfilled``) -- what has physically been handed over;
* **reserved** -- set aside for this line and sitting on the shelf, not yet gone;
* **incoming** -- covered by a confirmed purchase order not yet arrived
  (see :mod:`assignments`);
* **unallocated** -- ``ordered - delivered - cancelled - reserved - incoming``:
  still owed with nothing behind it.

A reservation moves no stock. The units stay in inventory and in the cost
layers until a delivery takes them out. What a reservation does is remove them
from the pool anyone else can be sold from:

    available stock = physical stock - reserved stock

This module owns the one allocation routine the whole system uses, so stock
arriving on a purchase order, stock arriving ad hoc and stock already on the
shelf when an order is taken are all distributed by the same rules.
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..errors import AllocationError
from ..models import (
    AllocationSource,
    OrderStatus,
    Product,
    SalesOrder,
    SalesOrderItem,
    StockReservation,
)
from ..numeric import ZERO, aggregate, quantity as to_quantity

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reading the reserved position
# ---------------------------------------------------------------------------

def _open_quantity_expression():
    return StockReservation.quantity - StockReservation.quantity_released


def reserved_for_product(session: Session, product_id: uuid.UUID) -> Decimal:
    """Stock currently set aside for customers, for one product."""
    total = session.execute(
        select(func.coalesce(func.sum(_open_quantity_expression()), 0)).where(
            StockReservation.product_id == product_id,
            _open_quantity_expression() > 0,
        )
    ).scalar_one()
    return aggregate(total)


def reserved_map(
    session: Session, product_ids: Optional[Sequence[uuid.UUID]] = None
) -> Dict[uuid.UUID, Decimal]:
    """Reserved quantity keyed by product id."""
    stmt = (
        select(StockReservation.product_id, func.coalesce(func.sum(_open_quantity_expression()), 0))
        .where(_open_quantity_expression() > 0)
        .group_by(StockReservation.product_id)
    )
    if product_ids is not None:
        if not product_ids:
            return {}
        stmt = stmt.where(StockReservation.product_id.in_(list(product_ids)))
    return {row[0]: aggregate(row[1]) for row in session.execute(stmt).all()}


def available_stock(session: Session, product: Product) -> Decimal:
    """Physical stock that is not already promised to a customer."""
    free = Decimal(str(product.physical_stock)) - reserved_for_product(session, product.id)
    return free if free > ZERO else ZERO


# ---------------------------------------------------------------------------
# Finding demand
# ---------------------------------------------------------------------------

def fifo_unallocated_items(session: Session, product_id: uuid.UUID) -> List[SalesOrderItem]:
    """Order lines still owed stock that has not been reserved, oldest first.

    The sort key is the order's creation time with the order number and line
    number as stable tie-breakers, so two orders created in the same microsecond
    still have a deterministic, reproducible priority.
    """
    unallocated = (
        SalesOrderItem.quantity_ordered
        - SalesOrderItem.quantity_fulfilled
        - SalesOrderItem.quantity_cancelled
        - SalesOrderItem.quantity_reserved
        - SalesOrderItem.quantity_incoming
    )
    stmt = (
        select(SalesOrderItem)
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .where(
            SalesOrderItem.product_id == product_id,
            SalesOrder.status != OrderStatus.CANCELLED,
            unallocated > 0,
        )
        .order_by(
            SalesOrder.created_at.asc(),
            SalesOrder.order_number.asc(),
            SalesOrderItem.line_number.asc(),
            SalesOrderItem.id.asc(),
        )
        .options(joinedload(SalesOrderItem.order).joinedload(SalesOrder.customer))
    )
    return list(session.execute(stmt).unique().scalars().all())


#: How much each line can take, when that is not simply its unallocated
#: quantity (a goods receipt may also fill what was assigned to its PO line).
Capacity = Optional[Dict[uuid.UUID, Decimal]]


def _capacity(item: SalesOrderItem, capacity: Capacity) -> Decimal:
    if capacity is not None and item.id in capacity:
        return capacity[item.id]
    return item.quantity_unallocated


def unallocated_total(items: Sequence[SalesOrderItem], capacity: Capacity = None) -> Decimal:
    return sum((_capacity(item, capacity) for item in items), ZERO)


def propose_fifo(
    items: Sequence[SalesOrderItem], quantity: Decimal, capacity: Capacity = None
) -> List[Decimal]:
    """Spread ``quantity`` over ``items`` oldest-first."""
    remaining = quantity
    proposals: List[Decimal] = []
    for item in items:
        want = _capacity(item, capacity)
        take = want if want < remaining else remaining
        if take < ZERO:
            take = ZERO
        proposals.append(take)
        remaining = remaining - take
    return proposals


# ---------------------------------------------------------------------------
# Allocating
# ---------------------------------------------------------------------------

def validate_allocation(
    items: Sequence[SalesOrderItem],
    requested: Optional[Iterable[Dict[str, Any]]],
    quantity_available: Decimal,
    label: str = "receipt",
    capacity: Capacity = None,
) -> List[Tuple[SalesOrderItem, Decimal]]:
    """Turn a proposed distribution into a validated allocation plan.

    Every rule is checked here, on the server, against order lines loaded in
    this transaction. ``None`` means no proposal was supplied, which falls back
    to FIFO. The plan must total exactly
    ``min(quantity_available, unallocated demand)`` -- no part of incoming stock
    may be left free while a customer is still waiting for it.
    """
    demand = unallocated_total(items, capacity)
    required = min(quantity_available, demand)
    items_by_id = {item.id: item for item in items}

    if requested is None:
        plan = [
            (item, qty)
            for item, qty in zip(items, propose_fifo(items, quantity_available, capacity))
            if qty > ZERO
        ]
    else:
        seen: Dict[uuid.UUID, Decimal] = {}
        plan = []
        for entry in requested:
            raw_id = entry.get("order_item_id")
            try:
                item_id = raw_id if isinstance(raw_id, uuid.UUID) else uuid.UUID(str(raw_id))
            except (ValueError, AttributeError, TypeError):
                raise AllocationError("'{}' is not a valid order item id.".format(raw_id))

            if item_id in seen:
                raise AllocationError(
                    "Order line {} appears more than once in the allocation.".format(item_id)
                )
            item = items_by_id.get(item_id)
            if item is None:
                raise AllocationError(
                    "Order line {} is not awaiting stock for this product; it may have been "
                    "reserved or cancelled since the preview was loaded.".format(item_id),
                    details={"order_item_id": str(item_id)},
                )

            qty = to_quantity(entry.get("quantity", 0), "Allocation quantity")
            if qty < ZERO:
                raise AllocationError("Allocation quantity cannot be negative.")
            limit = _capacity(item, capacity)
            if qty > limit:
                raise AllocationError(
                    "Order {} can take at most {} (what it is still waiting for), not {}.".format(
                        item.order.order_number, limit, qty
                    ),
                    details={"order_item_id": str(item_id), "max_allowed": str(limit)},
                )
            seen[item_id] = qty
            if qty > ZERO:
                plan.append((item, qty))

    allocated = sum((qty for _, qty in plan), ZERO)

    if allocated > quantity_available:
        raise AllocationError(
            "Allocated {} exceeds the {} available from this {}.".format(
                allocated, quantity_available, label
            ),
            details={"allocated": str(allocated), "available": str(quantity_available)},
        )
    if allocated != required:
        raise AllocationError(
            "Allocations must total exactly {} (the lesser of the {} available and the {} "
            "customers are waiting for). Got {}. Incoming stock cannot be left free while "
            "orders are unallocated.".format(required, quantity_available, demand, allocated),
            details={
                "required_allocation": str(required),
                "allocated": str(allocated),
                "available": str(quantity_available),
                "unallocated_demand": str(demand),
            },
        )
    return plan


def reserve(
    session: Session,
    product: Product,
    plan: Sequence[Tuple[SalesOrderItem, Decimal]],
    source: AllocationSource,
    stock_receipt_id: Optional[uuid.UUID] = None,
    goods_receipt_item_id: Optional[uuid.UUID] = None,
) -> List[StockReservation]:
    """Set the planned quantities aside. No stock moves; none leaves inventory."""
    created: List[StockReservation] = []
    for item, qty in plan:
        if qty <= ZERO:
            continue
        reservation = StockReservation(
            order_item_id=item.id,
            product_id=product.id,
            quantity=qty,
            quantity_released=ZERO,
            source=source,
            stock_receipt_id=stock_receipt_id,
            goods_receipt_item_id=goods_receipt_item_id,
        )
        session.add(reservation)
        item.quantity_reserved = item.quantity_reserved + qty
        created.append(reservation)
    session.flush()
    return created


def allocate_available_stock(
    session: Session,
    product: Product,
    quantity_available: Decimal,
    source: AllocationSource,
    allocations: Optional[Iterable[Dict[str, Any]]] = None,
    stock_receipt_id: Optional[uuid.UUID] = None,
    goods_receipt_item_id: Optional[uuid.UUID] = None,
    label: str = "receipt",
) -> List[Tuple[SalesOrderItem, Decimal]]:
    """Compulsorily settle waiting orders from ``quantity_available``.

    The caller must already hold the product row lock.
    """
    items = fifo_unallocated_items(session, product.id)
    plan = validate_allocation(items, allocations, quantity_available, label)
    reserve(session, product, plan, source, stock_receipt_id, goods_receipt_item_id)
    return plan


# ---------------------------------------------------------------------------
# Releasing
# ---------------------------------------------------------------------------

def _open_reservations(session: Session, order_item_id: uuid.UUID) -> List[StockReservation]:
    """Open reservations for one order line, oldest first."""
    return list(
        session.execute(
            select(StockReservation)
            .where(
                StockReservation.order_item_id == order_item_id,
                StockReservation.quantity > StockReservation.quantity_released,
            )
            .order_by(StockReservation.created_at.asc(), StockReservation.id.asc())
        )
        .scalars()
        .all()
    )


def consume(
    session: Session, item: SalesOrderItem, quantity: Decimal
) -> List[Tuple[StockReservation, Decimal]]:
    """Draw ``quantity`` out of a line's reservations, oldest first.

    Used when goods are delivered and when outstanding quantity is cancelled.
    The same reserved quantity can never be drawn twice: each draw raises
    ``quantity_released`` on the reservation it came from, which is what takes
    it out of the open pool.

    Returns the individual draws, so a delivery can record exactly which
    reservation -- and therefore which receipt -- each delivered unit came from.
    """
    remaining = quantity
    draws: List[Tuple[StockReservation, Decimal]] = []
    for reservation in _open_reservations(session, item.id):
        if remaining <= ZERO:
            break
        take = reservation.quantity_open if reservation.quantity_open < remaining else remaining
        if take <= ZERO:
            continue
        reservation.quantity_released = reservation.quantity_released + take
        draws.append((reservation, take))
        remaining = remaining - take

    consumed = sum((qty for _, qty in draws), ZERO)
    item.quantity_reserved = item.quantity_reserved - consumed
    if item.quantity_reserved < ZERO:
        item.quantity_reserved = ZERO
    session.flush()

    if remaining > ZERO:
        logger.warning(
            "Asked to release %s from order line %s but only %s was reserved.",
            quantity,
            item.id,
            consumed,
        )
    return draws


def release_outstanding(session: Session, item: SalesOrderItem) -> Decimal:
    """Give back everything reserved for a line, e.g. when it is cancelled."""
    return sum((qty for _, qty in consume(session, item, item.quantity_reserved)), ZERO)


def reservation_rows(session: Session, order_item_id: uuid.UUID) -> List[Dict[str, Any]]:
    """Where a line's reserved stock came from, for the audit trail."""
    rows = session.execute(
        select(StockReservation)
        .where(StockReservation.order_item_id == order_item_id)
        .order_by(StockReservation.created_at)
    ).scalars().all()
    return [
        {
            "reservation_id": row.id,
            "quantity": row.quantity,
            "quantity_released": row.quantity_released,
            "quantity_open": row.quantity_open,
            "source": row.source,
            "stock_receipt_id": row.stock_receipt_id,
            "goods_receipt_item_id": row.goods_receipt_item_id,
            "created_at": row.created_at,
        }
        for row in rows
    ]
