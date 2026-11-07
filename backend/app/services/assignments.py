"""Settling waiting customers from purchases that have not arrived yet.

Stock is counted as *bought less sold*: a confirmed purchase order adds to it
straight away and a sales order takes from it straight away. For that figure
to mean anything, a customer left waiting must be covered the moment a
purchase is made -- and a sale made while bought goods are still on the way
must be covered by them.

That cover is a :class:`PurchaseAssignment`: part of a purchase order line set
aside for one sales order line. It moves nothing physical. When the goods
arrive the assignment is released and the same quantity becomes an ordinary
reservation on the shelf (see :mod:`reservations`).

Per sales order line this keeps

    ordered = delivered + cancelled + reserved + incoming + unallocated

where *incoming* is the open assignments and *unallocated* is what nothing
covers yet -- the only quantity that makes a product short.

Callers must hold the row locks of the products involved.
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..models import (
    Product,
    PurchaseAssignment,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    SalesOrder,
    SalesOrderItem,
    Supplier,
)
from ..numeric import ZERO, aggregate
from . import reservations
from .common import OPEN_PURCHASE_STATUSES

logger = logging.getLogger(__name__)


def _open_expression():
    return PurchaseAssignment.quantity - PurchaseAssignment.quantity_released


def _open_assignments(
    session: Session,
    purchase_order_item_id: Optional[uuid.UUID] = None,
    order_item_id: Optional[uuid.UUID] = None,
    newest_first: bool = False,
) -> List[PurchaseAssignment]:
    stmt = select(PurchaseAssignment).where(_open_expression() > 0)
    if purchase_order_item_id is not None:
        stmt = stmt.where(PurchaseAssignment.purchase_order_item_id == purchase_order_item_id)
    if order_item_id is not None:
        stmt = stmt.where(PurchaseAssignment.order_item_id == order_item_id)
    if newest_first:
        stmt = stmt.order_by(PurchaseAssignment.created_at.desc(), PurchaseAssignment.id.desc())
    else:
        stmt = stmt.order_by(PurchaseAssignment.created_at.asc(), PurchaseAssignment.id.asc())
    return list(session.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def assigned_map(
    session: Session, purchase_order_item_ids: Sequence[uuid.UUID]
) -> Dict[uuid.UUID, Decimal]:
    """Open assigned quantity keyed by purchase order line."""
    if not purchase_order_item_ids:
        return {}
    rows = session.execute(
        select(PurchaseAssignment.purchase_order_item_id, func.sum(_open_expression()))
        .where(
            PurchaseAssignment.purchase_order_item_id.in_(list(purchase_order_item_ids)),
            _open_expression() > 0,
        )
        .group_by(PurchaseAssignment.purchase_order_item_id)
    ).all()
    return {row[0]: aggregate(row[1]) for row in rows}


def assigned_on_line(session: Session, po_item: PurchaseOrderItem) -> Decimal:
    return assigned_map(session, [po_item.id]).get(po_item.id, ZERO)


def open_by_order_item(session: Session, po_item_id: uuid.UUID) -> Dict[uuid.UUID, Decimal]:
    """What each sales order line is waiting for on one purchase order line."""
    totals: Dict[uuid.UUID, Decimal] = {}
    for assignment in _open_assignments(session, purchase_order_item_id=po_item_id):
        totals[assignment.order_item_id] = (
            totals.get(assignment.order_item_id, ZERO) + assignment.quantity_open
        )
    return totals


def assignment_rows(session: Session, po_item_id: uuid.UUID) -> List[Dict[str, Any]]:
    """Who a purchase order line is settling, for the purchase order view."""
    rows = session.execute(
        select(PurchaseAssignment, SalesOrderItem, SalesOrder)
        .join(SalesOrderItem, PurchaseAssignment.order_item_id == SalesOrderItem.id)
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .where(PurchaseAssignment.purchase_order_item_id == po_item_id)
        .order_by(PurchaseAssignment.created_at, PurchaseAssignment.id)
        .options(joinedload(SalesOrder.customer))
    ).unique().all()
    return [
        {
            "order_item_id": item.id,
            "order_id": order.id,
            "order_number": order.order_number,
            "customer_id": order.customer_id,
            "customer_name": order.customer.name,
            "quantity": assignment.quantity,
            "quantity_open": assignment.quantity_open,
        }
        for assignment, item, order in rows
    ]


def incoming_sources(
    session: Session, order_item_ids: Sequence[uuid.UUID]
) -> Dict[uuid.UUID, List[Dict[str, Any]]]:
    """For each sales line, the purchase orders covering it and how much each."""
    if not order_item_ids:
        return {}
    rows = session.execute(
        select(
            PurchaseAssignment.order_item_id,
            PurchaseOrder.id,
            PurchaseOrderItem.id,
            PurchaseOrder.po_number,
            Supplier.name,
            func.sum(_open_expression()),
        )
        .join(PurchaseOrderItem, PurchaseAssignment.purchase_order_item_id == PurchaseOrderItem.id)
        .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .join(Supplier, PurchaseOrder.supplier_id == Supplier.id)
        .where(
            PurchaseAssignment.order_item_id.in_(list(order_item_ids)),
            _open_expression() > 0,
        )
        .group_by(
            PurchaseAssignment.order_item_id,
            PurchaseOrder.id,
            PurchaseOrderItem.id,
            PurchaseOrder.po_number,
            Supplier.name,
        )
        .order_by(PurchaseOrder.po_number)
    ).all()
    sources: Dict[uuid.UUID, List[Dict[str, Any]]] = {}
    for item_id, po_id, po_item_id, po_number, supplier_name, qty in rows:
        sources.setdefault(item_id, []).append(
            {
                "purchase_order_id": po_id,
                "purchase_order_item_id": po_item_id,
                "po_number": po_number,
                "supplier_name": supplier_name,
                "quantity": aggregate(qty),
            }
        )
    return sources


def last_suppliers(
    session: Session, product_ids: Sequence[uuid.UUID]
) -> Dict[uuid.UUID, uuid.UUID]:
    """Who each product was last ordered from, to suggest when buying again."""
    if not product_ids:
        return {}
    rows = session.execute(
        select(PurchaseOrderItem.product_id, PurchaseOrder.supplier_id, PurchaseOrder.created_at)
        .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .where(
            PurchaseOrderItem.product_id.in_(list(product_ids)),
            PurchaseOrder.status != PurchaseOrderStatus.CANCELLED,
        )
        .order_by(PurchaseOrder.created_at.desc())
    ).all()
    latest: Dict[uuid.UUID, uuid.UUID] = {}
    for product_id, supplier_id, _ in rows:
        latest.setdefault(product_id, supplier_id)
    return latest


def _open_purchase_lines(session: Session, product_id: uuid.UUID) -> List[PurchaseOrderItem]:
    """Confirmed, not fully received purchase order lines, oldest order first."""
    return list(
        session.execute(
            select(PurchaseOrderItem)
            .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
            .where(
                PurchaseOrderItem.product_id == product_id,
                PurchaseOrder.status.in_(OPEN_PURCHASE_STATUSES),
                PurchaseOrderItem.quantity_ordered > PurchaseOrderItem.quantity_received,
            )
            .order_by(
                PurchaseOrder.ordered_at.asc().nulls_last(),
                PurchaseOrder.po_number.asc(),
                PurchaseOrderItem.line_number.asc(),
            )
        )
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------
# Assigning
# ---------------------------------------------------------------------------

def _assign(
    session: Session,
    po_item: PurchaseOrderItem,
    plan: Sequence[Tuple[SalesOrderItem, Decimal]],
) -> None:
    for item, qty in plan:
        if qty <= ZERO:
            continue
        session.add(
            PurchaseAssignment(
                purchase_order_item_id=po_item.id,
                order_item_id=item.id,
                product_id=po_item.product_id,
                quantity=qty,
                quantity_released=ZERO,
            )
        )
        item.quantity_incoming = item.quantity_incoming + qty
    session.flush()


def preview_settlement(session: Session, product_id: uuid.UUID, quantity: Decimal) -> Dict[str, Any]:
    """Who a purchase of ``quantity`` would settle, oldest order first. Writes nothing."""
    items = reservations.fifo_unallocated_items(session, product_id)
    proposals = reservations.propose_fifo(items, quantity)
    return {
        "items": items,
        "proposals": proposals,
        "required": min(quantity, reservations.unallocated_total(items)),
    }


def settle_purchase_line(
    session: Session,
    po_item: PurchaseOrderItem,
    allocations: Optional[Iterable[Dict[str, Any]]] = None,
) -> List[Tuple[SalesOrderItem, Decimal]]:
    """Compulsorily cover waiting customers from what this line has not yet promised.

    The same rule as a receipt: the plan must total exactly
    ``min(free on this line, uncovered demand)``. Who gets it, and how much
    each, is the user's choice in ``allocations``; only when it is omitted
    altogether are the oldest orders settled first.
    """
    free = po_item.quantity_remaining - assigned_on_line(session, po_item)
    if free <= ZERO:
        return []
    items = reservations.fifo_unallocated_items(session, po_item.product_id)
    if not items:
        return []
    plan = reservations.validate_allocation(items, allocations, free, label="purchase order")
    _assign(session, po_item, plan)
    return plan


def cover_new_lines(
    session: Session, product_id: uuid.UUID, items: Sequence[SalesOrderItem]
) -> None:
    """Cover a new sale from goods bought but not yet arrived.

    Only the given lines are covered -- never anybody else's -- from whatever
    open purchase lines have not been promised, oldest purchase first.
    """
    for po_item in _open_purchase_lines(session, product_id):
        free = po_item.quantity_remaining - assigned_on_line(session, po_item)
        plan = []
        for item in items:
            if free <= ZERO:
                break
            take = min(free, item.quantity_unallocated)
            if take > ZERO:
                plan.append((item, take))
                free = free - take
        if plan:
            _assign(session, po_item, plan)


def free_on_line(session: Session, po_item: PurchaseOrderItem) -> Decimal:
    """Still to arrive on this line and promised to nobody."""
    free = po_item.quantity_remaining - assigned_on_line(session, po_item)
    return free if free > ZERO else ZERO


def settle_required(session: Session, po_item: PurchaseOrderItem) -> Decimal:
    """How much of this line's free quantity must go to customers who are short."""
    free = free_on_line(session, po_item)
    if free <= ZERO:
        return ZERO
    short = reservations.unallocated_total(
        reservations.fifo_unallocated_items(session, po_item.product_id)
    )
    return min(free, short)


# ---------------------------------------------------------------------------
# Releasing
# ---------------------------------------------------------------------------

def _release(session: Session, assignment: PurchaseAssignment, quantity: Decimal) -> Decimal:
    take = assignment.quantity_open if assignment.quantity_open < quantity else quantity
    if take <= ZERO:
        return ZERO
    assignment.quantity_released = assignment.quantity_released + take
    item = assignment.order_item
    item.quantity_incoming = item.quantity_incoming - take
    if item.quantity_incoming < ZERO:
        item.quantity_incoming = ZERO
    return take


def draw_on_receipt(
    session: Session, po_item_id: uuid.UUID, item: SalesOrderItem, quantity: Decimal
) -> Decimal:
    """Goods for this line arrived on this PO line: turn its cover into a reservation.

    Releases up to ``quantity`` of the line's assignment on the PO line and
    returns how much was released; the caller then reserves the full quantity.
    """
    remaining = quantity
    released = ZERO
    for assignment in _open_assignments(session, purchase_order_item_id=po_item_id, order_item_id=item.id):
        if remaining <= ZERO:
            break
        took = _release(session, assignment, remaining)
        released = released + took
        remaining = remaining - took
    session.flush()
    return released


def release_for_order_item(session: Session, item: SalesOrderItem) -> Decimal:
    """Drop a sales line's cover, e.g. when it is cancelled."""
    released = ZERO
    for assignment in _open_assignments(session, order_item_id=item.id):
        released = released + _release(session, assignment, assignment.quantity_open)
    session.flush()
    return released


def release_for_purchase_line(session: Session, po_item: PurchaseOrderItem) -> Decimal:
    """Drop everything a purchase line was covering, e.g. when it is cancelled."""
    released = ZERO
    for assignment in _open_assignments(session, purchase_order_item_id=po_item.id):
        released = released + _release(session, assignment, assignment.quantity_open)
    session.flush()
    return released


def trim_to_remaining(session: Session, po_item: PurchaseOrderItem) -> Decimal:
    """A line can only cover what it has still to deliver; release the newest excess."""
    excess = assigned_on_line(session, po_item) - po_item.quantity_remaining
    released = ZERO
    if excess <= ZERO:
        return released
    for assignment in _open_assignments(session, purchase_order_item_id=po_item.id, newest_first=True):
        if excess <= ZERO:
            break
        took = _release(session, assignment, excess)
        released = released + took
        excess = excess - took
    session.flush()
    return released


def receipt_candidates(
    session: Session, product: Product, po_item_id: uuid.UUID
) -> Tuple[List[SalesOrderItem], Dict[uuid.UUID, Decimal]]:
    """Lines goods arriving on ``po_item_id`` may go to.

    Those this PO line was covering come first, then anyone nothing covers. The capacity
    of each is its cover on this line plus its uncovered quantity.
    """
    assigned_here = open_by_order_item(session, po_item_id)
    uncovered = reservations.fifo_unallocated_items(session, product.id)
    by_id = {item.id: item for item in uncovered}
    missing = [item_id for item_id in assigned_here if item_id not in by_id]
    if missing:
        for item in session.execute(
            select(SalesOrderItem)
            .where(SalesOrderItem.id.in_(missing))
            .options(joinedload(SalesOrderItem.order).joinedload(SalesOrder.customer))
        ).unique().scalars().all():
            by_id[item.id] = item
    # The customers this purchase was bought for come first, so that a receipt
    # with no explicit choice honours the settlement made when it was placed.
    items = sorted(
        by_id.values(),
        key=lambda item: (
            0 if item.id in assigned_here else 1,
            item.order.created_at,
            item.order.order_number,
            item.line_number,
            str(item.id),
        ),
    )
    capacity = {
        item.id: item.quantity_unallocated + assigned_here.get(item.id, ZERO) for item in items
    }
    return items, capacity
