"""Shared service helpers: locking, numbering, movements and status derivation."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import NotFoundError
from ..models import (
    Customer,
    DocumentCounter,
    MovementType,
    OrderStatus,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    SalesOrder,
    SalesOrderItem,
    StockMovement,
)
from ..numeric import ZERO, aggregate

ORDER_COUNTER = "sales_order"
RECEIPT_COUNTER = "stock_receipt"


def count_matching(session: Session, stmt) -> int:
    """How many rows a filtered listing matches, ignoring its order and window."""
    return session.execute(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    ).scalar_one()


def windowed(stmt, limit: Optional[int] = None, offset: int = 0):
    """Apply a page window to a listing; no limit returns every row."""
    if limit is not None:
        stmt = stmt.limit(limit)
    if offset:
        stmt = stmt.offset(offset)
    return stmt


def lock_product(session: Session, product_id: uuid.UUID) -> Product:
    """Load a product, taking the row lock that serialises stock changes.

    Every operation that changes a product's physical stock, its reservations
    or its pending quantity acquires this lock first, so per-product state is
    mutated by one transaction at a time. Concurrent work on *different*
    products is unaffected, which is the point of locking per row rather than
    per table.
    """
    stmt = select(Product).where(Product.id == product_id).with_for_update()
    product = session.execute(stmt).scalar_one_or_none()
    if product is None:
        raise NotFoundError("Product {} does not exist.".format(product_id))
    return product


def lock_products(session: Session, product_ids: Iterable[uuid.UUID]) -> Dict[uuid.UUID, Product]:
    """Lock several products in a deterministic order to avoid deadlocks."""
    ordered = sorted(set(product_ids), key=str)
    return {product_id: lock_product(session, product_id) for product_id in ordered}


def get_customer(session: Session, customer_id: uuid.UUID) -> Customer:
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError("Customer {} does not exist.".format(customer_id))
    return customer


def next_document_number(session: Session, counter_name: str, prefix: str) -> str:
    """Allocate the next gap-free number for a document series."""
    counter = session.get(DocumentCounter, counter_name, with_for_update=True)
    if counter is None:
        counter = DocumentCounter(name=counter_name, last_value=0)
        session.add(counter)
        session.flush()
    counter.last_value += 1
    session.flush()
    return "{}-{}-{:06d}".format(prefix, datetime.now(timezone.utc).year, counter.last_value)


def record_movement(
    session: Session,
    product: Product,
    movement_type: MovementType,
    quantity_change: Decimal,
    reference_type: Optional[str] = None,
    reference_id: Optional[uuid.UUID] = None,
    note: Optional[str] = None,
) -> StockMovement:
    """Append to the stock ledger and keep the cached balance in step.

    The cached ``Product.physical_stock`` and the ledger are written in the same
    transaction, so they can never drift apart.
    """
    movement = StockMovement(
        product_id=product.id,
        movement_type=movement_type,
        quantity_change=quantity_change,
        reference_type=reference_type,
        reference_id=reference_id,
        note=note,
    )
    session.add(movement)
    product.physical_stock = product.physical_stock + quantity_change
    session.flush()
    return movement


def pending_quantity_expression():
    """SQL expression for the quantity still owed on an order line."""
    return (
        SalesOrderItem.quantity_ordered
        - SalesOrderItem.quantity_fulfilled
        - SalesOrderItem.quantity_cancelled
    )


def pending_quantity_for_product(session: Session, product_id: uuid.UUID) -> Decimal:
    """Total quantity still owed to customers for one product."""
    pending = pending_quantity_expression()
    total = session.execute(
        select(func.coalesce(func.sum(pending), 0))
        .select_from(SalesOrderItem)
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .where(
            SalesOrderItem.product_id == product_id,
            SalesOrder.status != OrderStatus.CANCELLED,
            pending > 0,
        )
    ).scalar_one()
    return aggregate(total)


# Purchase orders that count as bought: confirmed and not cancelled or closed.
OPEN_PURCHASE_STATUSES = (PurchaseOrderStatus.ORDERED, PurchaseOrderStatus.PARTIALLY_RECEIVED)


def on_order_quantity_expression():
    """SQL expression for what a purchase order line still has to deliver."""
    return PurchaseOrderItem.quantity_ordered - PurchaseOrderItem.quantity_received


def on_order_quantity_map(
    session: Session, product_ids: Optional[Sequence[uuid.UUID]] = None
) -> Dict[uuid.UUID, Decimal]:
    """Quantity bought from suppliers but not yet received, keyed by product id."""
    due = on_order_quantity_expression()
    stmt = (
        select(PurchaseOrderItem.product_id, func.coalesce(func.sum(due), 0))
        .select_from(PurchaseOrderItem)
        .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .where(PurchaseOrder.status.in_(OPEN_PURCHASE_STATUSES), due > 0)
        .group_by(PurchaseOrderItem.product_id)
    )
    if product_ids is not None:
        if not product_ids:
            return {}
        stmt = stmt.where(PurchaseOrderItem.product_id.in_(list(product_ids)))
    return {row[0]: aggregate(row[1]) for row in session.execute(stmt).all()}


def on_order_quantity_for_product(session: Session, product_id: uuid.UUID) -> Decimal:
    return on_order_quantity_map(session, [product_id]).get(product_id, ZERO)


def stock_for_product(session: Session, product: Product) -> Decimal:
    """Stock as the business counts it: bought less sold.

    A confirmed purchase adds the moment it is placed and a sale takes the
    moment it is placed; whether goods have physically arrived or left the
    warehouse does not matter.
    """
    return (
        Decimal(str(product.physical_stock))
        + on_order_quantity_for_product(session, product.id)
        - pending_quantity_for_product(session, product.id)
    )


def pending_quantity_map(
    session: Session, product_ids: Optional[Sequence[uuid.UUID]] = None
) -> Dict[uuid.UUID, Decimal]:
    """Pending customer quantity keyed by product id."""
    pending = pending_quantity_expression()
    stmt = (
        select(SalesOrderItem.product_id, func.coalesce(func.sum(pending), 0))
        .select_from(SalesOrderItem)
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .where(SalesOrder.status != OrderStatus.CANCELLED, pending > 0)
        .group_by(SalesOrderItem.product_id)
    )
    if product_ids is not None:
        if not product_ids:
            return {}
        stmt = stmt.where(SalesOrderItem.product_id.in_(list(product_ids)))
    return {row[0]: aggregate(row[1]) for row in session.execute(stmt).all()}


def fifo_pending_items(session: Session, product_id: uuid.UUID) -> List[SalesOrderItem]:
    """Outstanding order lines for a product, oldest order first.

    The sort key is the order's creation timestamp with the order number and the
    line number as stable tie-breakers, so two orders created in the same
    microsecond still have a deterministic, reproducible priority.
    """
    pending = pending_quantity_expression()
    stmt = (
        select(SalesOrderItem)
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .where(
            SalesOrderItem.product_id == product_id,
            SalesOrder.status != OrderStatus.CANCELLED,
            pending > 0,
        )
        .order_by(
            SalesOrder.created_at.asc(),
            SalesOrder.order_number.asc(),
            SalesOrderItem.line_number.asc(),
            SalesOrderItem.id.asc(),
        )
    )
    return list(session.execute(stmt).scalars().all())


def recompute_order_status(order: SalesOrder) -> OrderStatus:
    """Derive an order's status from its line items and apply it."""
    total_fulfilled = sum((item.quantity_fulfilled for item in order.items), ZERO)
    total_cancelled = sum((item.quantity_cancelled for item in order.items), ZERO)
    total_pending = sum((item.quantity_pending for item in order.items), ZERO)

    if total_pending > ZERO:
        status = OrderStatus.PARTIALLY_FULFILLED if total_fulfilled > ZERO else OrderStatus.PENDING
    elif total_fulfilled <= ZERO and total_cancelled > ZERO:
        status = OrderStatus.CANCELLED
    elif total_cancelled > ZERO:
        # Fulfilled in part, remainder cancelled: the order is closed but it was
        # never fully delivered, so it must not read as FULFILLED.
        status = OrderStatus.PARTIALLY_FULFILLED
    else:
        status = OrderStatus.FULFILLED

    order.status = status
    if status == OrderStatus.CANCELLED and order.cancelled_at is None:
        order.cancelled_at = datetime.now(timezone.utc)
    return status
