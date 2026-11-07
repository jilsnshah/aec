"""Delivering goods to customers, and seeing what is still owed.

Delivery is the only thing that takes stock out of inventory for a sale.
Reserving set the units aside; delivering hands them over:

* physical stock falls by the delivered quantity, with a ``CUSTOMER_DELIVERY``
  ledger movement behind it;
* the reservations backing the line are released, so reserved stock falls too;
* the delivered quantity on the order line rises, which is what finally reduces
  what the customer is owed;
* the cost of goods is taken from the FIFO cost layers, because only now have
  the goods actually been sold.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..database import begin_write
from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import (
    Customer,
    CustomerDelivery,
    CustomerDeliveryItem,
    MovementType,
    OrderStatus,
    Product,
    SalesOrder,
    SalesOrderItem,
    StockAllocation,
)
from ..numeric import ZERO, ZERO_MONEY, money, quantity, require_positive
from . import assignments, costing, reservations
from .common import (
    count_matching,
    lock_products,
    next_document_number,
    record_movement,
    recompute_order_status,
    windowed,
)
from .orders import get_order

logger = logging.getLogger(__name__)

DELIVERY_COUNTER = "customer_delivery"


# ---------------------------------------------------------------------------
# Reading what can be delivered
# ---------------------------------------------------------------------------

def _line_view(item: SalesOrderItem, product: Product, reserved_total: Decimal) -> Dict[str, Any]:
    physical = Decimal(str(product.physical_stock))
    available = physical - reserved_total
    # Only reserved stock can be handed over: units that are not reserved are
    # either someone else's or not spoken for yet.
    deliverable = item.quantity_reserved
    if deliverable > item.quantity_pending:
        deliverable = item.quantity_pending
    return {
        "order_item_id": item.id,
        "product_id": product.id,
        "product_sku": product.sku,
        "product_name": product.name,
        "unit_of_measure": product.unit_of_measure,
        "line_number": item.line_number,
        "quantity_ordered": item.quantity_ordered,
        "quantity_delivered": item.quantity_fulfilled,
        "quantity_reserved": item.quantity_reserved,
        "quantity_cancelled": item.quantity_cancelled,
        "quantity_outstanding": item.quantity_pending,
        "quantity_unallocated": item.quantity_unallocated,
        "quantity_incoming": item.quantity_incoming,
        "quantity_deliverable": deliverable,
        "physical_stock": physical,
        "reserved_stock": reserved_total,
        "available_stock": available if available > ZERO else ZERO,
        "unit_price_net": item.unit_price_net,
        # Filled in by the caller that has a session to hand.
        "reservations": [],
    }


def order_fulfilment(session: Session, order_id: uuid.UUID) -> Dict[str, Any]:
    """Everything the fulfilment screen needs for one order."""
    order = get_order(session, order_id)
    product_ids = [item.product_id for item in order.items]
    products = {
        product.id: product
        for product in session.execute(select(Product).where(Product.id.in_(product_ids)))
        .scalars()
        .all()
    }
    reserved = reservations.reserved_map(session, product_ids)

    lines = []
    for item in order.items:
        view = _line_view(item, products[item.product_id], reserved.get(item.product_id, ZERO))
        view["reservations"] = reservations.reservation_rows(session, item.id)
        lines.append(view)

    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "customer_id": order.customer_id,
        "customer_name": order.customer.name,
        "status": order.status,
        "created_at": order.created_at,
        "can_deliver": order.status != OrderStatus.CANCELLED
        and any(line["quantity_deliverable"] > ZERO for line in lines),
        "lines": lines,
        "total_outstanding": sum((line["quantity_outstanding"] for line in lines), ZERO),
        "total_deliverable": sum((line["quantity_deliverable"] for line in lines), ZERO),
        "deliveries": [
            {
                "id": delivery.id,
                "delivery_number": delivery.delivery_number,
                "reference": delivery.reference,
                "created_at": delivery.created_at,
                "lines": [
                    {
                        "product_sku": line.product.sku,
                        "product_name": line.product.name,
                        "quantity": line.quantity,
                    }
                    for line in delivery.items
                ],
            }
            for delivery in session.execute(
                select(CustomerDelivery)
                .where(CustomerDelivery.sales_order_id == order.id)
                .order_by(CustomerDelivery.created_at.desc())
                .options(joinedload(CustomerDelivery.items).joinedload(CustomerDeliveryItem.product))
            )
            .unique()
            .scalars()
            .all()
        ],
    }


# ---------------------------------------------------------------------------
# Delivering
# ---------------------------------------------------------------------------

def _delivery_result(session: Session, delivery: CustomerDelivery) -> Dict[str, Any]:
    order = get_order(session, delivery.sales_order_id)
    product_ids = [line.product_id for line in delivery.items]
    products = {
        product.id: product
        for product in session.execute(select(Product).where(Product.id.in_(product_ids)))
        .scalars()
        .all()
    }
    reserved = reservations.reserved_map(session, product_ids)
    items_by_id = {item.id: item for item in order.items}

    return {
        "delivery_id": delivery.id,
        "delivery_number": delivery.delivery_number,
        "created_at": delivery.created_at,
        "reference": delivery.reference,
        "notes": delivery.notes,
        "order_id": order.id,
        "order_number": order.order_number,
        "order_status": order.status,
        "customer_id": order.customer_id,
        "customer_name": order.customer.name,
        "lines": [
            {
                "order_item_id": line.order_item_id,
                "product_id": line.product_id,
                "product_sku": products[line.product_id].sku,
                "product_name": products[line.product_id].name,
                "unit_of_measure": products[line.product_id].unit_of_measure,
                "quantity_delivered_now": line.quantity,
                "quantity_delivered_total": items_by_id[line.order_item_id].quantity_fulfilled,
                "quantity_outstanding": items_by_id[line.order_item_id].quantity_pending,
                "quantity_reserved": items_by_id[line.order_item_id].quantity_reserved,
                "physical_stock_after": Decimal(str(products[line.product_id].physical_stock)),
                "available_stock_after": Decimal(str(products[line.product_id].physical_stock))
                - reserved.get(line.product_id, ZERO),
            }
            for line in delivery.items
        ],
        "total_delivered": sum((line.quantity for line in delivery.items), ZERO),
        "order_outstanding_after": sum((item.quantity_pending for item in order.items), ZERO),
    }


def create_delivery(
    session: Session,
    order_id: uuid.UUID,
    lines: Iterable[Dict[str, Any]],
    reference: Optional[str] = None,
    notes: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Hand reserved goods to the customer.

    Everything -- the ledger movements, the released reservations, the cost of
    goods and the updated order -- is written in one transaction.
    """
    begin_write(session)

    if idempotency_key:
        existing = session.execute(
            select(CustomerDelivery).where(CustomerDelivery.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing is not None:
            logger.info("Replaying delivery for idempotency key %s", idempotency_key)
            if existing.result_json:
                return json.loads(existing.result_json)
            raise ConflictError("This delivery has already been recorded.")

    try:
        # Lock the order row before reading any quantity off it. Without this,
        # two concurrent deliveries would both validate against the same
        # pre-delivery snapshot on PostgreSQL, where reads do not block.
        lock_stmt = select(SalesOrder).where(SalesOrder.id == order_id).with_for_update()
        if session.execute(lock_stmt).scalar_one_or_none() is None:
            raise NotFoundError("Order {} does not exist.".format(order_id))

        order = get_order(session, order_id)
        if order.status == OrderStatus.CANCELLED:
            raise ConflictError(
                "Order {} is cancelled; nothing can be delivered against it.".format(
                    order.order_number
                )
            )

        items_by_id = {item.id: item for item in order.items}
        requested: List[Dict[str, Any]] = []
        seen: set = set()

        for index, line in enumerate(lines, start=1):
            raw_id = line.get("order_item_id")
            try:
                item_id = raw_id if isinstance(raw_id, uuid.UUID) else uuid.UUID(str(raw_id))
            except (ValueError, AttributeError, TypeError):
                raise ValidationError(
                    "Line {}: '{}' is not a valid order line id.".format(index, raw_id)
                )
            if item_id in seen:
                raise ValidationError(
                    "Order line {} appears more than once in this delivery.".format(item_id)
                )
            seen.add(item_id)

            item = items_by_id.get(item_id)
            if item is None:
                raise NotFoundError(
                    "Order line {} is not part of order {}.".format(item_id, order.order_number)
                )

            qty = quantity(line.get("quantity", 0), "Line {} quantity".format(index))
            if qty <= ZERO:
                continue
            if qty > item.quantity_pending:
                raise ValidationError(
                    "Cannot deliver {} of {}: only {} is still outstanding on this line.".format(
                        qty, item.product.sku, item.quantity_pending
                    ),
                    details={"order_item_id": str(item_id), "max_allowed": str(item.quantity_pending)},
                )
            if qty > item.quantity_reserved:
                raise ValidationError(
                    "Cannot deliver {} of {}: only {} is reserved for this line. Receive stock "
                    "first so it can be allocated.".format(
                        qty, item.product.sku, item.quantity_reserved
                    ),
                    details={
                        "order_item_id": str(item_id),
                        "max_allowed": str(item.quantity_reserved),
                    },
                )
            requested.append({"item": item, "quantity": qty})

        if not requested:
            raise ValidationError("A delivery must contain at least one quantity to deliver.")

        products = lock_products(session, [entry["item"].product_id for entry in requested])

        delivery = CustomerDelivery(
            delivery_number=next_document_number(session, DELIVERY_COUNTER, "DN"),
            sales_order_id=order.id,
            customer_id=order.customer_id,
            reference=reference,
            notes=notes,
            idempotency_key=idempotency_key,
        )
        session.add(delivery)
        session.flush()

        for entry in requested:
            item = entry["item"]
            qty = entry["quantity"]
            product = products[item.product_id]

            if Decimal(str(product.physical_stock)) < qty:
                # Should be unreachable: reserved stock is backed by real stock.
                raise ConflictError(
                    "Only {} of {} is physically in stock; {} cannot be delivered.".format(
                        product.physical_stock, product.sku, qty
                    )
                )

            delivery_item = CustomerDeliveryItem(
                customer_delivery_id=delivery.id,
                order_item_id=item.id,
                product_id=product.id,
                quantity=qty,
            )
            session.add(delivery_item)
            session.flush()

            # The goods leave the building: this is the only stock-out for a sale.
            movement = record_movement(
                session,
                product,
                MovementType.CUSTOMER_DELIVERY,
                -qty,
                reference_type="customer_delivery_item",
                reference_id=delivery_item.id,
                note="Delivered on {} against order {}".format(
                    delivery.delivery_number, order.order_number
                ),
            )
            delivery_item.stock_movement_id = movement.id

            # Release the reservations this delivery draws on, recording which
            # receipt each delivered unit came from and what it cost.
            draws = reservations.consume(session, item, qty)
            drawn_total = sum((drawn for _, drawn in draws), ZERO)
            if drawn_total != qty:
                # Belt and braces behind the row lock above: if the reservations
                # cannot cover the quantity, nothing is delivered rather than
                # the same reserved units going out twice.
                raise ConflictError(
                    "Only {} of {} is still reserved for this line; {} cannot be "
                    "delivered.".format(drawn_total, product.sku, qty),
                    details={"order_item_id": str(item.id), "max_allowed": str(drawn_total)},
                )
            for reservation, drawn in draws:
                allocation = StockAllocation(
                    order_item_id=item.id,
                    stock_receipt_id=reservation.stock_receipt_id,
                    stock_movement_id=movement.id,
                    customer_delivery_item_id=delivery_item.id,
                    source=reservation.source,
                    quantity=drawn,
                )
                session.add(allocation)
                session.flush()
                costing.consume_cost_layers(session, product, allocation, drawn)

            item.quantity_fulfilled = item.quantity_fulfilled + qty

        session.flush()
        session.expire(order)
        recompute_order_status(order)
        session.flush()

        result = _delivery_result(session, delivery)
        delivery.result_json = json.dumps(result, default=str)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            "The delivery could not be saved because it conflicts with an existing record. "
            "Nothing was changed."
        ) from exc
    except Exception:
        session.rollback()
        raise

    logger.info(
        "Delivery %s: %s units against order %s",
        result["delivery_number"],
        result["total_delivered"],
        result["order_number"],
    )
    return result


def count_deliveries(
    session: Session,
    search: Optional[str] = None,
    customer_id: Optional[uuid.UUID] = None,
    order_id: Optional[uuid.UUID] = None,
) -> int:
    return count_matching(session, _delivery_filter(search, customer_id, order_id))


def _delivery_filter(
    search: Optional[str],
    customer_id: Optional[uuid.UUID],
    order_id: Optional[uuid.UUID],
):
    stmt = select(CustomerDelivery)
    if customer_id:
        stmt = stmt.where(CustomerDelivery.customer_id == customer_id)
    if order_id:
        stmt = stmt.where(CustomerDelivery.sales_order_id == order_id)
    if search:
        pattern = "%{}%".format(search.strip().lower())
        stmt = stmt.where(
            or_(
                func.lower(CustomerDelivery.delivery_number).like(pattern),
                func.lower(func.coalesce(CustomerDelivery.reference, "")).like(pattern),
                CustomerDelivery.customer_id.in_(
                    select(Customer.id).where(func.lower(Customer.name).like(pattern))
                ),
            )
        )
    return stmt


def list_deliveries(
    session: Session,
    search: Optional[str] = None,
    customer_id: Optional[uuid.UUID] = None,
    order_id: Optional[uuid.UUID] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    stmt = (
        _delivery_filter(search, customer_id, order_id)
        .options(
            joinedload(CustomerDelivery.customer),
            joinedload(CustomerDelivery.sales_order),
            joinedload(CustomerDelivery.items).joinedload(CustomerDeliveryItem.product),
        )
        .order_by(CustomerDelivery.created_at.desc(), CustomerDelivery.delivery_number.desc())
    )
    return [
        {
            "id": delivery.id,
            "delivery_number": delivery.delivery_number,
            "created_at": delivery.created_at,
            "reference": delivery.reference,
            "notes": delivery.notes,
            "order_id": delivery.sales_order_id,
            "order_number": delivery.sales_order.order_number,
            "customer_id": delivery.customer_id,
            "customer_name": delivery.customer.name,
            "line_count": len(delivery.items),
            "total_quantity": sum((line.quantity for line in delivery.items), ZERO),
            "lines": [
                {
                    "product_id": line.product_id,
                    "product_sku": line.product.sku,
                    "product_name": line.product.name,
                    "unit_of_measure": line.product.unit_of_measure,
                    "quantity": line.quantity,
                }
                for line in delivery.items
            ],
        }
        for delivery in session.execute(windowed(stmt, limit, offset)).unique().scalars().all()
    ]


# ---------------------------------------------------------------------------
# Pending customer commitments
# ---------------------------------------------------------------------------

def pending_commitments(
    session: Session,
    customer_id: Optional[uuid.UUID] = None,
    product_id: Optional[uuid.UUID] = None,
    order_id: Optional[uuid.UUID] = None,
    search: Optional[str] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    only_unallocated: bool = False,
    only_reserved: bool = False,
    limit: int = 500,
) -> Dict[str, Any]:
    """What the business still owes customers, and what stock is behind it.

    One row per outstanding sales order line, oldest order first, with the
    product's stock position alongside so it is obvious whether the obligation
    can be met today. Also returns a per-customer roll-up.
    """
    outstanding = (
        SalesOrderItem.quantity_ordered
        - SalesOrderItem.quantity_fulfilled
        - SalesOrderItem.quantity_cancelled
    )
    stmt = (
        select(SalesOrderItem)
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .where(SalesOrder.status != OrderStatus.CANCELLED, outstanding > 0)
        .order_by(
            SalesOrder.created_at.asc(),
            SalesOrder.order_number.asc(),
            SalesOrderItem.line_number.asc(),
        )
        .options(
            joinedload(SalesOrderItem.order).joinedload(SalesOrder.customer),
            joinedload(SalesOrderItem.product),
        )
        .limit(max(1, min(limit, 2000)))
    )
    if customer_id:
        stmt = stmt.where(SalesOrder.customer_id == customer_id)
    if product_id:
        stmt = stmt.where(SalesOrderItem.product_id == product_id)
    if order_id:
        stmt = stmt.where(SalesOrderItem.order_id == order_id)
    if created_from:
        stmt = stmt.where(SalesOrder.created_at >= created_from)
    if created_to:
        stmt = stmt.where(SalesOrder.created_at <= created_to)
    if only_unallocated:
        stmt = stmt.where(outstanding - SalesOrderItem.quantity_reserved > 0)
    if only_reserved:
        stmt = stmt.where(SalesOrderItem.quantity_reserved > 0)
    if search:
        pattern = "%{}%".format(search.strip().lower())
        stmt = stmt.where(
            or_(
                func.lower(SalesOrder.order_number).like(pattern),
                SalesOrder.customer_id.in_(
                    select(Customer.id).where(func.lower(Customer.name).like(pattern))
                ),
                SalesOrderItem.product_id.in_(
                    select(Product.id).where(
                        or_(
                            func.lower(Product.sku).like(pattern),
                            func.lower(Product.name).like(pattern),
                        )
                    )
                ),
            )
        )

    items = list(session.execute(stmt).unique().scalars().all())
    reserved_by_product = reservations.reserved_map(
        session, [item.product_id for item in items]
    )

    sources = assignments.incoming_sources(session, [item.id for item in items])
    suppliers = assignments.last_suppliers(session, list({item.product_id for item in items}))

    rows: List[Dict[str, Any]] = []
    for item in items:
        product = item.product
        physical = Decimal(str(product.physical_stock))
        reserved_total = reserved_by_product.get(product.id, ZERO)
        available = physical - reserved_total
        deliverable = min(item.quantity_reserved, item.quantity_pending)

        if item.quantity_fulfilled > ZERO:
            status = "PARTIALLY_DELIVERED"
        elif deliverable > ZERO:
            status = "READY_TO_DELIVER"
        elif item.quantity_reserved > ZERO:
            status = "RESERVED"
        elif item.quantity_incoming > ZERO:
            status = "ON_ORDER"
        else:
            status = "AWAITING_STOCK"

        rows.append(
            {
                "order_item_id": item.id,
                "order_id": item.order_id,
                "order_number": item.order.order_number,
                "order_created_at": item.order.created_at,
                "order_status": item.order.status,
                "customer_id": item.order.customer_id,
                "customer_name": item.order.customer.name,
                "product_id": product.id,
                "product_sku": product.sku,
                "product_name": product.name,
                "unit_of_measure": product.unit_of_measure,
                "quantity_ordered": item.quantity_ordered,
                "quantity_delivered": item.quantity_fulfilled,
                "quantity_reserved": item.quantity_reserved,
                "quantity_cancelled": item.quantity_cancelled,
                "quantity_unallocated": item.quantity_unallocated,
                "quantity_incoming": item.quantity_incoming,
                "quantity_outstanding": item.quantity_pending,
                "quantity_deliverable": deliverable,
                "physical_stock": physical,
                "reserved_stock": reserved_total,
                "available_stock": available if available > ZERO else ZERO,
                "fulfilment_status": status,
                "outstanding_value": money(item.unit_price_net * item.quantity_pending),
                "incoming_sources": sources.get(item.id, []),
                "last_supplier_id": suppliers.get(product.id),
            }
        )

    by_customer: Dict[uuid.UUID, Dict[str, Any]] = {}
    for row in rows:
        summary = by_customer.setdefault(
            row["customer_id"],
            {
                "customer_id": row["customer_id"],
                "customer_name": row["customer_name"],
                "order_count": set(),
                "line_count": 0,
                "quantity_outstanding": ZERO,
                "quantity_reserved": ZERO,
                "quantity_unallocated": ZERO,
                "quantity_incoming": ZERO,
                "outstanding_value": ZERO_MONEY,
                "oldest_order_at": row["order_created_at"],
            },
        )
        summary["order_count"].add(row["order_id"])
        summary["line_count"] += 1
        summary["quantity_outstanding"] += row["quantity_outstanding"]
        summary["quantity_reserved"] += row["quantity_reserved"]
        summary["quantity_unallocated"] += row["quantity_unallocated"]
        summary["quantity_incoming"] += row["quantity_incoming"]
        summary["outstanding_value"] += row["outstanding_value"]
        if row["order_created_at"] < summary["oldest_order_at"]:
            summary["oldest_order_at"] = row["order_created_at"]

    customers = []
    for summary in by_customer.values():
        summary["order_count"] = len(summary["order_count"])
        customers.append(summary)
    customers.sort(key=lambda entry: entry["oldest_order_at"])

    return {
        "rows": rows,
        "customers": customers,
        "totals": {
            "line_count": len(rows),
            "customer_count": len(customers),
            "quantity_outstanding": sum((row["quantity_outstanding"] for row in rows), ZERO),
            "quantity_reserved": sum((row["quantity_reserved"] for row in rows), ZERO),
            "quantity_unallocated": sum((row["quantity_unallocated"] for row in rows), ZERO),
            "quantity_incoming": sum((row["quantity_incoming"] for row in rows), ZERO),
            "quantity_deliverable": sum((row["quantity_deliverable"] for row in rows), ZERO),
            "outstanding_value": money(
                sum((row["outstanding_value"] for row in rows), ZERO_MONEY)
            ),
        },
    }
