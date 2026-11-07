"""Sales order service: creation with priority-aware fulfilment, and cancellation."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import (
    AllocationSource,
    CancellationKind,
    Customer,
    MovementType,
    OrderCancellation,
    OrderStatus,
    Product,
    SalesOrder,
    SalesOrderItem,
    StockAllocation,
)
from ..numeric import (
    ZERO,
    ZERO_MONEY,
    aggregate,
    money,
    net_of_discount,
    percent,
    quantity,
    require_non_negative,
    require_positive,
    unit_cost,
)
from ..database import begin_write
from . import assignments
from . import costing
from . import pricing
from . import reservations
from .common import (
    ORDER_COUNTER,
    count_matching,
    get_customer,
    lock_products,
    next_document_number,
    pending_quantity_expression,
    record_movement,
    recompute_order_status,
    windowed,
)

logger = logging.getLogger(__name__)


def get_order(session: Session, order_id: uuid.UUID) -> SalesOrder:
    order = session.execute(
        select(SalesOrder)
        .where(SalesOrder.id == order_id)
        .options(
            joinedload(SalesOrder.customer),
            joinedload(SalesOrder.items).joinedload(SalesOrderItem.product),
            joinedload(SalesOrder.cancellations),
            joinedload(SalesOrder.enquiry),
        )
        # Refresh collections already held by this session, so a caller that
        # re-reads an order after changing it never sees a stale snapshot.
        .execution_options(populate_existing=True)
    ).unique().scalar_one_or_none()
    if order is None:
        raise NotFoundError("Order {} does not exist.".format(order_id))
    return order


ORDER_SORTS = {
    "created_at": SalesOrder.created_at,
    "order_number": SalesOrder.order_number,
    "total_amount": SalesOrder.total_amount,
}


def count_orders(
    session: Session,
    search: Optional[str] = None,
    status: Optional[str] = None,
    customer_id: Optional[uuid.UUID] = None,
    product_id: Optional[uuid.UUID] = None,
) -> int:
    return count_matching(session, _order_filter(search, status, customer_id, product_id))


def list_orders(
    session: Session,
    search: Optional[str] = None,
    status: Optional[str] = None,
    customer_id: Optional[uuid.UUID] = None,
    product_id: Optional[uuid.UUID] = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    limit: Optional[int] = None,
    offset: int = 0,
) -> List[SalesOrder]:
    column = ORDER_SORTS.get(sort_by, SalesOrder.created_at)
    stmt = (
        _order_filter(search, status, customer_id, product_id)
        .options(
            joinedload(SalesOrder.customer),
            joinedload(SalesOrder.items).joinedload(SalesOrderItem.product),
        )
        .order_by(
            column.desc() if sort_dir == "desc" else column.asc(),
            SalesOrder.order_number.desc(),
        )
    )
    return list(session.execute(windowed(stmt, limit, offset)).unique().scalars().all())


def _order_filter(
    search: Optional[str],
    status: Optional[str],
    customer_id: Optional[uuid.UUID],
    product_id: Optional[uuid.UUID],
):
    stmt = select(SalesOrder)
    if status:
        try:
            stmt = stmt.where(SalesOrder.status == OrderStatus(status))
        except ValueError:
            raise ValidationError("'{}' is not a valid order status.".format(status))
    if customer_id:
        stmt = stmt.where(SalesOrder.customer_id == customer_id)
    if product_id:
        stmt = stmt.where(
            SalesOrder.id.in_(
                select(SalesOrderItem.order_id).where(SalesOrderItem.product_id == product_id)
            )
        )
    if search:
        pattern = "%{}%".format(search.strip().lower())
        stmt = stmt.where(
            or_(
                func.lower(SalesOrder.order_number).like(pattern),
                SalesOrder.customer_id.in_(
                    select(Customer.id).where(func.lower(Customer.name).like(pattern))
                ),
            )
        )
    return stmt


def _validate_lines(lines: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not lines:
        raise ValidationError("An order must contain at least one product line.")
    cleaned = []
    for index, line in enumerate(lines, start=1):
        raw_id = line.get("product_id")
        try:
            product_id = raw_id if isinstance(raw_id, uuid.UUID) else uuid.UUID(str(raw_id))
        except (ValueError, AttributeError, TypeError):
            raise ValidationError("Line {}: '{}' is not a valid product id.".format(index, raw_id))
        qty = require_positive(
            quantity(line.get("quantity_ordered", 0), "Line {} quantity".format(index)),
            "Line {} quantity".format(index),
        )
        raw_price = line.get("unit_price")
        price = (
            None
            if raw_price is None or raw_price == ""
            else require_non_negative(
                unit_cost(raw_price, "Line {} price".format(index)),
                "Line {} price".format(index),
            )
        )
        discount = percent(
            line.get("discount_percent") or 0, "Line {} discount".format(index)
        )
        raw_snapshot = line.get("mrp_snapshot")
        snapshot = (
            None
            if raw_snapshot is None or raw_snapshot == ""
            else require_non_negative(
                unit_cost(raw_snapshot, "Line {} MRP".format(index)),
                "Line {} MRP".format(index),
            )
        )
        cleaned.append(
            {
                "product_id": product_id,
                "quantity_ordered": qty,
                "line_number": index,
                # None means "use the product's MRP", resolved once the product is loaded.
                "unit_price": price,
                "discount_percent": discount,
                # Supplied when converting an enquiry, so the order records the
                # MRP the deal was struck against rather than today's.
                "mrp_snapshot": snapshot,
            }
        )
    return cleaned


def create_order(
    session: Session,
    customer_id: uuid.UUID,
    lines: Iterable[Dict[str, Any]],
    notes: Optional[str] = None,
) -> SalesOrder:
    """Create a confirmed sales order in its own transaction.

    Callers that are already inside a transaction -- converting a customer
    enquiry, for instance -- call :func:`build_order` directly so the order and
    whatever else they are doing commit or roll back together.
    """
    try:
        begin_write(session)
        order = build_order(session, customer_id, lines, notes)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_order(session, order.id)


def build_order(
    session: Session,
    customer_id: uuid.UUID,
    lines: Iterable[Dict[str, Any]],
    notes: Optional[str] = None,
    enquiry_id: Optional[uuid.UUID] = None,
) -> SalesOrder:
    """Create a confirmed sales order, fulfilling what stock honestly allows.

    Stock already promised to *older* pending orders is reserved for them: the
    new order may only draw on what is left after those commitments. Anything it
    cannot get becomes pending quantity on its own line, and the shortfall shows
    up as a negative net stock position rather than as imaginary stock.

    Stock on hand is **reserved** against the order, not delivered: the units
    stay in inventory until someone actually hands them over. Reservation runs
    through the same FIFO engine as a goods receipt, over every line still
    waiting for this product, so an older order keeps its priority and the new
    order gets only what is left.

    This does **not** open or close a transaction: the caller owns it.
    """
    cleaned = _validate_lines(list(lines))

    customer = get_customer(session, customer_id)
    if not customer.is_active:
        raise ValidationError(
            "Customer '{}' is archived; reactivate them before taking new orders.".format(
                customer.name
            )
        )

    products = lock_products(session, [line["product_id"] for line in cleaned])
    new_items: List[SalesOrderItem] = []
    for line in cleaned:
        product = products[line["product_id"]]
        if not product.is_active:
            raise ValidationError(
                "Product '{}' is archived and cannot be ordered.".format(product.sku)
            )

    order = SalesOrder(
        order_number=next_document_number(session, ORDER_COUNTER, "SO"),
        customer_id=customer.id,
        status=OrderStatus.PENDING,
        notes=notes,
        enquiry_id=enquiry_id,
    )
    session.add(order)
    session.flush()

    subtotal = ZERO_MONEY
    order_total = ZERO_MONEY

    for line in cleaned:
        product = products[line["product_id"]]
        requested = line["quantity_ordered"]

        # An unspecified price falls back to the product's MRP, so a quick
        # order still gets priced; the discount is then applied to it.
        mrp_at_order = unit_cost(product.mrp)
        list_price = line["unit_price"] if line["unit_price"] is not None else mrp_at_order
        discount = line["discount_percent"]
        net_price = pricing.selling_price(list_price, discount)

        subtotal = subtotal + money(list_price * requested)
        order_total = order_total + money(net_price * requested)

        item = SalesOrderItem(
            order_id=order.id,
            product_id=product.id,
            line_number=line["line_number"],
            quantity_ordered=requested,
            # Nothing is delivered or reserved yet; the allocation pass below
            # reserves whatever stock is actually free.
            quantity_fulfilled=ZERO,
            quantity_reserved=ZERO,
            quantity_cancelled=ZERO,
            mrp_snapshot=line.get("mrp_snapshot") or mrp_at_order,
            unit_price=list_price,
            discount_percent=discount,
            unit_price_net=net_price,
        )
        session.add(item)
        session.flush()
        new_items.append(item)

    session.flush()

    # Reserve what is genuinely free, oldest order first across every line
    # waiting for each product. No stock moves: reserving only takes units out
    # of the pool other customers can be sold from.
    for product_id in sorted(products, key=str):
        product = products[product_id]
        free = reservations.available_stock(session, product)
        if free > ZERO:
            reservations.allocate_available_stock(
                session,
                product,
                free,
                AllocationSource.ORDER_CREATION,
                label="stock on hand",
            )
        # Goods already bought but not yet arrived count as stock too; whatever
        # the shelf could not cover on this order is covered from them.
        assignments.cover_new_lines(
            session, product.id, [item for item in new_items if item.product_id == product.id]
        )

    order.subtotal_amount = subtotal
    order.discount_amount = subtotal - order_total
    order.total_amount = order_total

    session.flush()
    # The items were added by foreign key, not through the relationship,
    # so expire the order to pick them up before deriving its status.
    session.expire(order)
    recompute_order_status(order)
    session.flush()

    logger.info(
        "Created order %s for customer %s with %d line(s)%s",
        order.order_number,
        customer_id,
        len(cleaned),
        " from enquiry {}".format(enquiry_id) if enquiry_id else "",
    )
    return order


def cancel_order(
    session: Session, order_id: uuid.UUID, reason: Optional[str] = None
) -> SalesOrder:
    """Cancel an order outright. Only allowed while nothing has been fulfilled."""
    try:
        begin_write(session)
        order = get_order(session, order_id)
        if order.status == OrderStatus.CANCELLED:
            raise ConflictError("Order {} is already cancelled.".format(order.order_number))

        fulfilled = sum((item.quantity_fulfilled for item in order.items), ZERO)
        if fulfilled > ZERO:
            raise ConflictError(
                "Order {} has {} units already fulfilled and cannot be cancelled outright. "
                "Cancel the unfulfilled remainder instead.".format(order.order_number, fulfilled),
                details={"fulfilled_quantity": str(fulfilled)},
            )

        cancelled_total = ZERO
        for item in order.items:
            pending = item.quantity_pending
            if pending <= ZERO:
                continue
            # Stock set aside for this line goes back into available stock,
            # and purchases on the way stop covering it.
            reservations.consume(session, item, item.quantity_reserved)
            assignments.release_for_order_item(session, item)
            item.quantity_cancelled = item.quantity_cancelled + pending
            cancelled_total = cancelled_total + pending
            session.add(
                OrderCancellation(
                    order_id=order.id,
                    order_item_id=item.id,
                    kind=CancellationKind.FULL,
                    quantity_cancelled=pending,
                    reason=reason,
                )
            )

        order.cancelled_at = datetime.now(timezone.utc)
        session.flush()
        recompute_order_status(order)
        order.status = OrderStatus.CANCELLED
        session.commit()
    except Exception:
        session.rollback()
        raise

    logger.info("Cancelled order %s (%s units)", order.order_number, cancelled_total)
    return get_order(session, order_id)


def cancel_remaining(
    session: Session, order_id: uuid.UUID, reason: Optional[str] = None
) -> SalesOrder:
    """Cancel only the unfulfilled remainder, leaving fulfilments intact.

    No stock moves: units already handed to the customer stay handed over, and
    the product's physical stock is not touched.
    """
    try:
        begin_write(session)
        order = get_order(session, order_id)
        if order.status == OrderStatus.CANCELLED:
            raise ConflictError("Order {} is already cancelled.".format(order.order_number))

        cancelled_total = ZERO
        for item in order.items:
            pending = item.quantity_pending
            if pending <= ZERO:
                continue
            # Stock set aside for this line goes back into available stock,
            # and purchases on the way stop covering it.
            reservations.consume(session, item, item.quantity_reserved)
            assignments.release_for_order_item(session, item)
            item.quantity_cancelled = item.quantity_cancelled + pending
            cancelled_total = cancelled_total + pending
            session.add(
                OrderCancellation(
                    order_id=order.id,
                    order_item_id=item.id,
                    kind=CancellationKind.REMAINING,
                    quantity_cancelled=pending,
                    reason=reason,
                )
            )

        if cancelled_total <= ZERO:
            raise ConflictError(
                "Order {} has no outstanding quantity left to cancel.".format(order.order_number)
            )

        session.flush()
        recompute_order_status(order)
        session.commit()
    except Exception:
        session.rollback()
        raise

    logger.info("Cancelled remaining %s units on order %s", cancelled_total, order.order_number)
    return get_order(session, order_id)


def order_allocations(session: Session, order_id: uuid.UUID) -> List[Dict[str, Any]]:
    """Where every *delivered* unit on an order came from.

    Reserved-but-undelivered stock is not here; it has not left inventory and
    has no cost of goods yet.
    """
    rows = session.execute(
        select(StockAllocation, SalesOrderItem, Product)
        .join(SalesOrderItem, StockAllocation.order_item_id == SalesOrderItem.id)
        .join(Product, SalesOrderItem.product_id == Product.id)
        .where(SalesOrderItem.order_id == order_id)
        .order_by(StockAllocation.created_at)
    ).all()
    return [
        {
            "allocation_id": allocation.id,
            "order_item_id": item.id,
            "product_id": product.id,
            "product_sku": product.sku,
            "product_name": product.name,
            "source": allocation.source,
            "stock_receipt_id": allocation.stock_receipt_id,
            "quantity": allocation.quantity,
            "cost_amount": allocation.cost_amount,
            "created_at": allocation.created_at,
        }
        for allocation, item, product in rows
    ]


# ---------------------------------------------------------------------------
# Money: what the order is worth, what it cost, what it earned
# ---------------------------------------------------------------------------

def _margin(profit: Decimal, revenue: Decimal) -> Decimal:
    """Gross margin as a percentage of revenue; zero when nothing was delivered."""
    if revenue <= ZERO_MONEY:
        return Decimal("0.00")
    return (profit / revenue * Decimal("100")).quantize(Decimal("0.01"))


def order_financials(session: Session, order: SalesOrder) -> Dict[str, Any]:
    """Per-line and whole-order money for one order.

    Revenue and profit are recognised on the quantity actually *delivered*, not
    the quantity ordered: a pending line has value but has earned nothing yet,
    and it has no cost of goods either. Cost comes from the FIFO cost layers the
    delivered units were drawn from, so the margin is the real one.
    """
    cost_rows = session.execute(
        select(
            StockAllocation.order_item_id,
            func.coalesce(func.sum(StockAllocation.cost_amount), 0),
        )
        .join(SalesOrderItem, StockAllocation.order_item_id == SalesOrderItem.id)
        .where(SalesOrderItem.order_id == order.id)
        .group_by(StockAllocation.order_item_id)
    ).all()
    cost_by_item = {row[0]: money(row[1] or 0) for row in cost_rows}

    lines: List[Dict[str, Any]] = []
    totals = {
        "subtotal_amount": ZERO_MONEY,
        "discount_amount": ZERO_MONEY,
        "total_amount": ZERO_MONEY,
        "delivered_amount": ZERO_MONEY,
        "pending_amount": ZERO_MONEY,
        "cancelled_amount": ZERO_MONEY,
        "cost_of_goods_sold": ZERO_MONEY,
        "gross_profit": ZERO_MONEY,
    }

    for item in order.items:
        gross = money(item.unit_price * item.quantity_ordered)
        net = money(item.unit_price_net * item.quantity_ordered)
        delivered = money(item.unit_price_net * item.quantity_fulfilled)
        pending_value = money(item.unit_price_net * item.quantity_pending)
        cancelled_value = money(item.unit_price_net * item.quantity_cancelled)
        cogs = cost_by_item.get(item.id, ZERO_MONEY)
        profit = delivered - cogs

        lines.append(
            {
                "order_item_id": item.id,
                "product_id": item.product_id,
                "unit_price": item.unit_price,
                "discount_percent": item.discount_percent,
                "unit_price_net": item.unit_price_net,
                "line_subtotal": gross,
                "line_discount": gross - net,
                "line_total": net,
                "delivered_amount": delivered,
                "pending_amount": pending_value,
                "cancelled_amount": cancelled_value,
                "cost_of_goods_sold": cogs,
                "gross_profit": profit,
                "margin_percent": _margin(profit, delivered),
            }
        )

        totals["subtotal_amount"] += gross
        totals["discount_amount"] += gross - net
        totals["total_amount"] += net
        totals["delivered_amount"] += delivered
        totals["pending_amount"] += pending_value
        totals["cancelled_amount"] += cancelled_value
        totals["cost_of_goods_sold"] += cogs
        totals["gross_profit"] += profit

    totals["margin_percent"] = _margin(totals["gross_profit"], totals["delivered_amount"])
    return {"lines": lines, "totals": totals}


def sales_report(session: Session) -> Dict[str, Any]:
    """Whole-business trading figures, delivered quantities only."""
    revenue_row = session.execute(
        select(
            func.coalesce(func.sum(SalesOrderItem.unit_price_net * SalesOrderItem.quantity_fulfilled), 0),
            func.coalesce(
                func.sum(SalesOrderItem.unit_price_net * SalesOrderItem.quantity_ordered)
                - func.sum(SalesOrderItem.unit_price_net * SalesOrderItem.quantity_fulfilled)
                - func.sum(SalesOrderItem.unit_price_net * SalesOrderItem.quantity_cancelled),
                0,
            ),
            func.coalesce(
                func.sum(
                    (SalesOrderItem.unit_price - SalesOrderItem.unit_price_net)
                    * SalesOrderItem.quantity_ordered
                ),
                0,
            ),
        )
        .select_from(SalesOrderItem)
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .where(SalesOrder.status != OrderStatus.CANCELLED)
    ).one()

    cogs = session.execute(
        select(func.coalesce(func.sum(StockAllocation.cost_amount), 0))
    ).scalar_one()

    revenue = money(revenue_row[0] or 0)
    outstanding = money(revenue_row[1] or 0)
    discounts = money(revenue_row[2] or 0)
    cost = money(cogs or 0)
    profit = revenue - cost
    return {
        "revenue_delivered": revenue,
        "cost_of_goods_sold": cost,
        "gross_profit": profit,
        "margin_percent": _margin(profit, revenue),
        "discounts_given": discounts,
        "outstanding_order_value": outstanding,
    }
