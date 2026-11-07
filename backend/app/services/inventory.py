"""Inventory service: stock receipts and the compulsory settlement of pending orders.

The rule this module exists to enforce
--------------------------------------
When stock arrives for a product, outstanding customer commitments are settled
*before* any of the new stock becomes freely available. For a receipt of ``R``
units against a total outstanding quantity of ``P`` units:

    required allocation = min(R, P)

and the allocations submitted (or proposed by FIFO) must sum to exactly that.
The backend recomputes this from its own data on every request; allocation
figures sent by the client are treated as a proposal and never as truth.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..errors import AllocationError, ConflictError, NotFoundError, ValidationError
from ..models import (
    AllocationSource,
    Customer,
    CustomerDelivery,
    CustomerDeliveryItem,
    MovementType,
    OrderStatus,
    Product,
    SalesOrder,
    SalesOrderItem,
    StockAllocation,
    StockCostLayer,
    StockMovement,
    StockReceipt,
)
from ..numeric import ZERO, ZERO_MONEY, aggregate, money, quantity, require_positive, unit_cost
from ..config import get_settings
from ..database import begin_write
from . import costing
from . import reservations
from . import orders as order_service
from .common import (
    RECEIPT_COUNTER,
    lock_product,
    next_document_number,
    on_order_quantity_for_product,
    on_order_quantity_map,
    pending_quantity_for_product,
    pending_quantity_expression,
    pending_quantity_map,
    record_movement,
    recompute_order_status,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------

def _pending_item_row(item: SalesOrderItem, proposed: Decimal = ZERO) -> Dict[str, Any]:
    order = item.order
    return {
        "order_item_id": item.id,
        "order_id": order.id,
        "order_number": order.order_number,
        "order_created_at": order.created_at,
        "order_status": order.status,
        "customer_id": order.customer_id,
        "customer_name": order.customer.name,
        "product_id": item.product_id,
        "quantity_ordered": item.quantity_ordered,
        "quantity_fulfilled": item.quantity_fulfilled,
        "quantity_cancelled": item.quantity_cancelled,
        "quantity_reserved": item.quantity_reserved,
        "quantity_pending": item.quantity_pending,
        "quantity_unallocated": item.quantity_unallocated,
        "quantity_incoming": item.quantity_incoming,
        "proposed_allocation": proposed,
    }


def pending_orders_for_product(
    session: Session,
    product_id: uuid.UUID,
    receipt_quantity: Optional[Any] = None,
) -> Dict[str, Any]:
    """Settlement preview: outstanding orders for a product, oldest first.

    When ``receipt_quantity`` is supplied the FIFO proposal and the required
    allocation total are included, which is exactly what the stock-in screen
    needs before the operator confirms.
    """
    product = session.get(Product, product_id)
    if product is None:
        raise NotFoundError("Product {} does not exist.".format(product_id))

    items = reservations.fifo_unallocated_items(session, product_id)
    unallocated = reservations.unallocated_total(items)
    reserved = reservations.reserved_for_product(session, product_id)
    total_pending = pending_quantity_for_product(session, product_id)

    received = None
    proposals: List[Decimal] = [ZERO] * len(items)
    required = ZERO
    if receipt_quantity is not None:
        received = quantity(receipt_quantity, "Receipt quantity")
        required = min(received, unallocated)
        proposals = reservations.propose_fifo(items, received)

    physical = Decimal(str(product.physical_stock))
    stock = physical + on_order_quantity_for_product(session, product_id) - total_pending
    return {
        "product_id": product.id,
        "product_sku": product.sku,
        "product_name": product.name,
        "unit_of_measure": product.unit_of_measure,
        "physical_stock": physical,
        "reserved_stock": reserved,
        "available_stock": physical - reserved,
        "pending_quantity": total_pending,
        "unallocated_quantity": unallocated,
        "net_stock_position": physical - total_pending,
        # Bought less sold. A receipt without a purchase order is a purchase in
        # itself, so it raises this by the full quantity.
        "stock": stock,
        "stock_after": (stock + received) if received is not None else None,
        "receipt_quantity": received,
        "required_allocation": required,
        "surplus_quantity": (received - required) if received is not None else None,
        "free_stock_after": (physical + received - reserved - required)
        if received is not None
        else None,
        "pending_after": (total_pending - required) if received is not None else None,
        "items": [_pending_item_row(item, proposal) for item, proposal in zip(items, proposals)],
    }


# ---------------------------------------------------------------------------
# Allocation validation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Stock receipt
# ---------------------------------------------------------------------------

def _receipt_result(
    session: Session,
    receipt: StockReceipt,
    product: Product,
    plan: Sequence[Tuple[SalesOrderItem, Decimal]],
    required: Decimal,
    unallocated_before: Decimal,
    pending_before: Decimal,
) -> Dict[str, Any]:
    physical = Decimal(str(product.physical_stock))
    reserved = reservations.reserved_for_product(session, product.id)
    valuation = costing.stock_valuation(session, product.id)
    allocated = sum((qty for _, qty in plan), ZERO)
    return {
        "receipt_id": receipt.id,
        "receipt_number": receipt.receipt_number,
        "created_at": receipt.created_at,
        "product_id": product.id,
        "product_sku": product.sku,
        "product_name": product.name,
        "unit_of_measure": product.unit_of_measure,
        "receipt_quantity": receipt.quantity,
        "unit_cost": receipt.unit_cost,
        "total_cost": receipt.total_cost,
        "supplier_reference": receipt.supplier_reference,
        "total_pending_before": pending_before,
        "unallocated_before": unallocated_before,
        "required_allocation": required,
        "allocated_total": allocated,
        "surplus_quantity": receipt.quantity - allocated,
        "allocations": [
            {
                "order_item_id": item.id,
                "order_id": item.order_id,
                "order_number": item.order.order_number,
                "customer_id": item.order.customer_id,
                "customer_name": item.order.customer.name,
                "order_created_at": item.order.created_at,
                "order_status": item.order.status,
                "quantity_allocated": qty,
                "quantity_ordered": item.quantity_ordered,
                "quantity_fulfilled": item.quantity_fulfilled,
                "quantity_reserved": item.quantity_reserved,
                "quantity_pending": item.quantity_pending,
                "quantity_unallocated": item.quantity_unallocated,
                "quantity_incoming": item.quantity_incoming,
                "unit_price_net": item.unit_price_net,
                "revenue": money(qty * item.unit_price_net),
            }
            for item, qty in plan
        ],
        "physical_stock_after": physical,
        "reserved_stock_after": reserved,
        "available_stock_after": physical - reserved,
        "pending_quantity_after": pending_before,
        "unallocated_after": unallocated_before - allocated,
        "net_stock_position_after": physical - pending_before,
        "stock_after": physical + on_order_quantity_for_product(session, product.id) - pending_before,
        "stock_value_after": valuation["stock_value"],
        "average_cost_after": valuation["average_cost"],
    }


def _serialise_result(result: Dict[str, Any]) -> str:
    return json.dumps(result, default=str)


def receive_stock(
    session: Session,
    product_id: uuid.UUID,
    received_quantity: Any,
    allocations: Optional[Iterable[Dict[str, Any]]] = None,
    note: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    purchase_unit_cost: Any = 0,
    supplier_reference: Optional[str] = None,
) -> Dict[str, Any]:
    """Record an ad-hoc stock receipt and compulsorily reserve waiting orders.

    The stock arrives and is **reserved** against the orders waiting for it; it
    is not delivered. Physical stock goes up by the full quantity received, and
    the reserved part of it simply stops being available to anybody else. The
    units leave inventory later, when somebody actually delivers them.

    The receipt, the ledger movement, the cost layer and every reservation are
    written in one transaction. If any rule fails nothing is persisted.
    """
    # Declared before the very first statement so the whole operation -- the
    # duplicate check included -- runs inside one write transaction.
    begin_write(session)

    if idempotency_key:
        existing = session.execute(
            select(StockReceipt).where(StockReceipt.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing is not None:
            # A retry or a double-click: replay the original outcome rather than
            # recording a second receipt.
            logger.info("Replaying stock receipt for idempotency key %s", idempotency_key)
            if existing.result_json:
                return json.loads(existing.result_json)
            raise ConflictError("This stock receipt has already been recorded.")

    try:
        # Taking the product lock first serialises every change to this
        # product's stock, reservations and pending quantity.
        product = lock_product(session, product_id)
        if not product.is_active:
            raise ValidationError(
                "Product '{}' is archived; reactivate it before receiving stock.".format(product.sku)
            )

        received = require_positive(
            quantity(received_quantity, "Received quantity"), "Received quantity"
        )
        cost_per_unit = unit_cost(purchase_unit_cost, "Purchase price")
        if cost_per_unit < ZERO_MONEY:
            raise ValidationError("Purchase price cannot be negative.")

        pending_before = pending_quantity_for_product(session, product.id)
        items = reservations.fifo_unallocated_items(session, product.id)
        unallocated_before = reservations.unallocated_total(items)
        required = min(received, unallocated_before)

        plan = reservations.validate_allocation(items, allocations, received)

        receipt = StockReceipt(
            receipt_number=next_document_number(session, RECEIPT_COUNTER, "GRN"),
            product_id=product.id,
            quantity=received,
            unit_cost=cost_per_unit,
            total_cost=money(received * cost_per_unit),
            supplier_reference=supplier_reference,
            note=note,
            idempotency_key=idempotency_key,
        )
        session.add(receipt)
        session.flush()

        # The goods are here, so physical stock rises by the whole quantity.
        # Reserving part of it below moves nothing further.
        record_movement(
            session,
            product,
            MovementType.STOCK_RECEIPT,
            received,
            reference_type="stock_receipt",
            reference_id=receipt.id,
            note=note,
        )
        costing.open_cost_layer(
            session,
            product,
            received,
            cost_per_unit,
            MovementType.STOCK_RECEIPT,
            receipt.id,
            note,
        )

        reservations.reserve(
            session,
            product,
            plan,
            AllocationSource.STOCK_RECEIPT,
            stock_receipt_id=receipt.id,
        )

        session.flush()
        result = _receipt_result(
            session, receipt, product, plan, required, unallocated_before, pending_before
        )
        receipt.result_json = _serialise_result(result)

        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            "The stock receipt could not be saved because it conflicts with an existing "
            "record. Nothing was changed."
        ) from exc
    except Exception:
        session.rollback()
        raise

    logger.info(
        "Receipt %s: %s units of %s at %s each (spend %s), %s reserved across %d order lines",
        result["receipt_number"],
        received,
        product.sku,
        cost_per_unit,
        receipt.total_cost,
        result["allocated_total"],
        len(plan),
    )
    return result


# ---------------------------------------------------------------------------
# Dashboard / summary
# ---------------------------------------------------------------------------

def daily_sales(session: Session, days: int = 30, tz: Optional[str] = None) -> List[Dict[str, Any]]:
    """Value booked (orders placed) and delivered per local calendar day, for
    the last `days` days including today. Days with no trade are present with
    zeros, so the series has no gaps."""
    zone = tz or get_settings().business_timezone
    today = datetime.now(ZoneInfo(zone)).date()
    start = today - timedelta(days=days - 1)

    def local_day(column):
        return func.date(func.timezone(zone, column))

    booked_day = local_day(SalesOrder.created_at)
    booked = session.execute(
        select(booked_day, func.count(SalesOrder.id), func.sum(SalesOrder.total_amount))
        .where(SalesOrder.status != OrderStatus.CANCELLED, booked_day >= start)
        .group_by(booked_day)
    ).all()
    delivered_day = local_day(CustomerDelivery.created_at)
    delivered = session.execute(
        select(
            delivered_day,
            func.sum(CustomerDeliveryItem.quantity * SalesOrderItem.unit_price_net),
        )
        .select_from(CustomerDeliveryItem)
        .join(CustomerDelivery, CustomerDeliveryItem.customer_delivery_id == CustomerDelivery.id)
        .join(SalesOrderItem, CustomerDeliveryItem.order_item_id == SalesOrderItem.id)
        .where(delivered_day >= start)
        .group_by(delivered_day)
    ).all()

    series = {
        start + timedelta(days=offset): {
            "date": start + timedelta(days=offset),
            "orders": 0,
            "booked_value": ZERO_MONEY,
            "delivered_value": ZERO_MONEY,
        }
        for offset in range(days)
    }
    for day, count, value in booked:
        if day in series:
            series[day].update(orders=count, booked_value=money(value or 0))
    for day, value in delivered:
        if day in series:
            series[day]["delivered_value"] = money(value or 0)
    return [series[day] for day in sorted(series)]


def inventory_summary(session: Session, recent_limit: int = 8) -> Dict[str, Any]:
    """Everything the dashboard shows, computed from live data."""
    active_products = session.execute(
        select(func.count()).select_from(Product).where(Product.is_active.is_(True))
    ).scalar_one()
    active_customers = session.execute(
        select(func.count()).select_from(Customer).where(Customer.is_active.is_(True))
    ).scalar_one()
    total_physical = session.execute(
        select(func.coalesce(func.sum(Product.physical_stock), 0)).where(Product.is_active.is_(True))
    ).scalar_one()

    pending = pending_quantity_map(session)
    total_pending = sum(pending.values(), ZERO)
    reserved = reservations.reserved_map(session)
    total_reserved = sum(reserved.values(), ZERO)
    total_incoming = aggregate(
        session.execute(
            select(func.coalesce(func.sum(SalesOrderItem.quantity_incoming), 0))
            .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
            .where(SalesOrder.status != OrderStatus.CANCELLED)
        ).scalar_one()
    )
    valuations = costing.stock_valuation_map(session)
    purchase_spend = money(
        session.execute(
            select(func.coalesce(func.sum(StockReceipt.total_cost), 0))
        ).scalar_one()
        or 0
    )
    trading = order_service.sales_report(session)

    products = list(session.execute(select(Product).where(Product.is_active.is_(True))).scalars().all())
    on_order = on_order_quantity_map(session)
    negative = []
    short = []
    for product in products:
        pending_qty = pending.get(product.id, ZERO)
        physical = Decimal(str(product.physical_stock))
        net = physical - pending_qty
        stock = physical + on_order.get(product.id, ZERO) - pending_qty
        if net >= ZERO and stock >= ZERO:
            continue
        row = {
            "product_id": product.id,
            "sku": product.sku,
            "name": product.name,
            "unit_of_measure": product.unit_of_measure,
            "physical_stock": physical,
            "reserved_stock": reserved.get(product.id, ZERO),
            "pending_quantity": pending_qty,
            "net_stock_position": net,
            "on_order_quantity": on_order.get(product.id, ZERO),
            "stock": stock,
            "stock_value": (valuations.get(product.id) or {}).get("stock_value", ZERO_MONEY),
        }
        if net < ZERO:
            negative.append(row)
        if stock < ZERO:
            short.append(row)
    negative.sort(key=lambda row: row["net_stock_position"])
    short.sort(key=lambda row: row["stock"])

    open_orders = session.execute(
        select(func.count())
        .select_from(SalesOrder)
        .where(SalesOrder.status.in_([OrderStatus.PENDING, OrderStatus.PARTIALLY_FULFILLED]))
    ).scalar_one()

    recent_orders = list(
        session.execute(
            select(SalesOrder)
            .order_by(SalesOrder.created_at.desc())
            .limit(recent_limit)
            .options(joinedload(SalesOrder.customer), joinedload(SalesOrder.items))
        )
        .unique()
        .scalars()
        .all()
    )
    recent_receipts = list(
        session.execute(
            select(StockReceipt)
            .order_by(StockReceipt.created_at.desc())
            .limit(recent_limit)
            .options(joinedload(StockReceipt.product))
        )
        .unique()
        .scalars()
        .all()
    )

    return {
        "active_products": active_products,
        "active_customers": active_customers,
        "total_physical_stock": aggregate(total_physical),
        "total_reserved_stock": total_reserved,
        "total_available_stock": aggregate(total_physical) - total_reserved,
        "total_pending_quantity": total_pending,
        # Sold with nothing behind it: not in the warehouse, not on order.
        "total_unallocated_quantity": max(ZERO, total_pending - total_reserved - total_incoming),
        "open_orders": open_orders,
        # Money. Stock is valued from the open FIFO cost layers, so it is what
        # the business actually paid for what it is holding.
        "total_stock_value": costing.total_stock_value(session),
        "purchase_spend": purchase_spend,
        "revenue_delivered": trading["revenue_delivered"],
        "cost_of_goods_sold": trading["cost_of_goods_sold"],
        "gross_profit": trading["gross_profit"],
        "margin_percent": trading["margin_percent"],
        "discounts_given": trading["discounts_given"],
        "outstanding_order_value": trading["outstanding_order_value"],
        "products_with_negative_position": negative,
        "products_short": short,
        "daily_sales": daily_sales(session),
        "recent_orders": [
            {
                "id": order.id,
                "order_number": order.order_number,
                "customer_id": order.customer_id,
                "customer_name": order.customer.name,
                "status": order.status,
                "created_at": order.created_at,
                "total_amount": order.total_amount,
                "line_count": len(order.items),
                "total_ordered": sum((item.quantity_ordered for item in order.items), ZERO),
                "total_pending": sum((item.quantity_pending for item in order.items), ZERO),
            }
            for order in recent_orders
        ],
        "recent_receipts": [
            {
                "id": receipt.id,
                "receipt_number": receipt.receipt_number,
                "product_id": receipt.product_id,
                "product_sku": receipt.product.sku,
                "product_name": receipt.product.name,
                "unit_of_measure": receipt.product.unit_of_measure,
                "quantity": receipt.quantity,
                "unit_cost": receipt.unit_cost,
                "total_cost": receipt.total_cost,
                "created_at": receipt.created_at,
                "allocated_quantity": aggregate(
                    session.execute(
                        select(func.coalesce(func.sum(StockAllocation.quantity), 0)).where(
                            StockAllocation.stock_receipt_id == receipt.id
                        )
                    ).scalar_one()
                ),
            }
            for receipt in recent_receipts
        ],
    }


def receipt_allocations(session: Session, receipt_id: uuid.UUID) -> List[Dict[str, Any]]:
    """Which customer orders received each incoming quantity."""
    rows = session.execute(
        select(StockAllocation, SalesOrderItem, SalesOrder, Customer)
        .join(SalesOrderItem, StockAllocation.order_item_id == SalesOrderItem.id)
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .join(Customer, SalesOrder.customer_id == Customer.id)
        .where(StockAllocation.stock_receipt_id == receipt_id)
        .order_by(StockAllocation.created_at)
    ).all()
    return [
        {
            "allocation_id": allocation.id,
            "quantity": allocation.quantity,
            "order_item_id": item.id,
            "order_id": order.id,
            "order_number": order.order_number,
            "customer_id": customer.id,
            "customer_name": customer.name,
            "created_at": allocation.created_at,
        }
        for allocation, item, order, customer in rows
    ]
