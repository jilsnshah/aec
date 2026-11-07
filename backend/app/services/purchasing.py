"""Purchase orders and goods receipts.

Ordering from a supplier changes no stock. Stock only moves when the goods
physically arrive, and when they do they are put through the same compulsory
allocation engine as any other receipt: waiting customer orders are reserved
against the new stock before any of it becomes freely available.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, object_session

from ..database import begin_write
from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import (
    AllocationSource,
    GoodsReceipt,
    GoodsReceiptItem,
    MovementType,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    Supplier,
)
from ..numeric import ZERO, ZERO_MONEY, money, quantity, require_non_negative, unit_cost
from . import costing, reservations
from .common import (
    count_matching,
    lock_products,
    next_document_number,
    pending_quantity_for_product,
    record_movement,
    stock_for_product,
    windowed,
)
from . import assignments
from .suppliers import get_supplier

logger = logging.getLogger(__name__)

PO_COUNTER = "purchase_order"
GOODS_RECEIPT_COUNTER = "goods_receipt"


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------

def _po_relations(stmt):
    return stmt.options(
        joinedload(PurchaseOrder.supplier),
        joinedload(PurchaseOrder.items).joinedload(PurchaseOrderItem.product),
    )


def get_purchase_order(session: Session, po_id: uuid.UUID) -> PurchaseOrder:
    order = (
        session.execute(
            _po_relations(select(PurchaseOrder).where(PurchaseOrder.id == po_id))
            .execution_options(populate_existing=True)
        )
        .unique()
        .scalar_one_or_none()
    )
    if order is None:
        raise NotFoundError("Purchase order {} does not exist.".format(po_id))
    return order


def count_purchase_orders(
    session: Session,
    search: Optional[str] = None,
    status: Optional[str] = None,
    supplier_id: Optional[uuid.UUID] = None,
    product_id: Optional[uuid.UUID] = None,
) -> int:
    return count_matching(session, _po_filter(search, status, supplier_id, product_id))


def list_purchase_orders(
    session: Session,
    search: Optional[str] = None,
    status: Optional[str] = None,
    supplier_id: Optional[uuid.UUID] = None,
    product_id: Optional[uuid.UUID] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> List[PurchaseOrder]:
    stmt = _po_relations(_po_filter(search, status, supplier_id, product_id)).order_by(
        PurchaseOrder.created_at.desc(), PurchaseOrder.po_number.desc()
    )
    return list(session.execute(windowed(stmt, limit, offset)).unique().scalars().all())


def _po_filter(
    search: Optional[str],
    status: Optional[str],
    supplier_id: Optional[uuid.UUID],
    product_id: Optional[uuid.UUID],
):
    stmt = select(PurchaseOrder)
    if status:
        wanted = []
        for value in (part.strip() for part in status.split(",")):
            if not value:
                continue
            try:
                wanted.append(PurchaseOrderStatus(value))
            except ValueError:
                raise ValidationError("'{}' is not a valid purchase order status.".format(value))
        if wanted:
            stmt = stmt.where(PurchaseOrder.status.in_(wanted))
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    if product_id:
        stmt = stmt.where(
            PurchaseOrder.id.in_(
                select(PurchaseOrderItem.purchase_order_id).where(
                    PurchaseOrderItem.product_id == product_id
                )
            )
        )
    if search:
        pattern = "%{}%".format(search.strip().lower())
        stmt = stmt.where(
            or_(
                func.lower(PurchaseOrder.po_number).like(pattern),
                PurchaseOrder.supplier_id.in_(
                    select(Supplier.id).where(
                        or_(
                            func.lower(Supplier.name).like(pattern),
                            func.lower(Supplier.code).like(pattern),
                        )
                    )
                ),
            )
        )
    return stmt


def _clean_po_lines(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate requested lines and consolidate repeats of the same product."""
    merged: Dict[uuid.UUID, Dict[str, Any]] = {}
    order: List[uuid.UUID] = []

    for index, item in enumerate(items, start=1):
        raw_id = item.get("product_id")
        try:
            product_id = raw_id if isinstance(raw_id, uuid.UUID) else uuid.UUID(str(raw_id))
        except (ValueError, AttributeError, TypeError):
            raise ValidationError("Line {}: '{}' is not a valid product id.".format(index, raw_id))

        qty = quantity(item.get("quantity_ordered", 0), "Line {} quantity".format(index))
        if qty <= ZERO:
            raise ValidationError("Line {} quantity must be greater than zero.".format(index))
        cost = require_non_negative(
            unit_cost(item.get("unit_cost") or 0, "Line {} unit cost".format(index)),
            "Line {} unit cost".format(index),
        )
        notes = item.get("notes") or None

        if product_id in merged:
            merged[product_id]["quantity_ordered"] += qty
            merged[product_id]["unit_cost"] = cost
            merged[product_id]["notes"] = notes or merged[product_id]["notes"]
        else:
            merged[product_id] = {
                "product_id": product_id,
                "quantity_ordered": qty,
                "unit_cost": cost,
                "notes": notes,
            }
            order.append(product_id)

    if not merged:
        raise ValidationError("A purchase order must contain at least one product line.")
    return [merged[product_id] for product_id in order]


def _load_products(session: Session, product_ids: Iterable[uuid.UUID]) -> Dict[uuid.UUID, Product]:
    ids = list(product_ids)
    found = {
        product.id: product
        for product in session.execute(select(Product).where(Product.id.in_(ids))).scalars().all()
    }
    for product_id in ids:
        product = found.get(product_id)
        if product is None:
            raise NotFoundError("Product {} does not exist.".format(product_id))
        if not product.is_active:
            raise ValidationError(
                "Product '{}' is archived and cannot be ordered.".format(product.sku)
            )
    return found


def create_purchase_order(
    session: Session,
    supplier_id: uuid.UUID,
    items: Iterable[Dict[str, Any]],
    expected_delivery_date: Optional[datetime] = None,
    notes: Optional[str] = None,
    confirm: bool = False,
    settlements: Optional[Iterable[Dict[str, Any]]] = None,
) -> PurchaseOrder:
    """Raise a purchase order. Confirmed straight away, it counts as stock at once."""
    cleaned = _clean_po_lines(items)

    try:
        begin_write(session)
        supplier = get_supplier(session, supplier_id)
        if not supplier.is_active:
            raise ValidationError(
                "Supplier '{}' is archived; reactivate it before ordering.".format(supplier.name)
            )
        products = _load_products(session, [line["product_id"] for line in cleaned])

        order = PurchaseOrder(
            po_number=next_document_number(session, PO_COUNTER, "PO"),
            supplier_id=supplier.id,
            status=PurchaseOrderStatus.ORDERED if confirm else PurchaseOrderStatus.DRAFT,
            expected_delivery_date=expected_delivery_date,
            ordered_at=datetime.now(timezone.utc) if confirm else None,
            notes=notes,
        )
        session.add(order)
        session.flush()

        for line_number, line in enumerate(cleaned, start=1):
            product = products[line["product_id"]]
            session.add(
                PurchaseOrderItem(
                    purchase_order_id=order.id,
                    product_id=product.id,
                    line_number=line_number,
                    quantity_ordered=line["quantity_ordered"],
                    quantity_received=ZERO,
                    unit_cost=line["unit_cost"],
                    notes=line["notes"],
                )
            )

        if confirm:
            session.flush()
            session.expire(order)
            _settle_waiting_customers(session, order, settlements)

        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("That purchase order could not be saved.") from exc
    except Exception:
        session.rollback()
        raise

    logger.info(
        "Created purchase order %s for supplier %s with %d line(s)%s",
        order.po_number,
        supplier.code,
        len(cleaned),
        " (confirmed)" if confirm else " (draft)",
    )
    return get_purchase_order(session, order.id)


def update_purchase_order(
    session: Session, po_id: uuid.UUID, changes: Dict[str, Any]
) -> PurchaseOrder:
    """Edit a DRAFT purchase order. Once ordered, only its notes can change."""
    try:
        begin_write(session)
        order = get_purchase_order(session, po_id)
        if order.status in (PurchaseOrderStatus.CANCELLED, PurchaseOrderStatus.RECEIVED):
            raise ConflictError(
                "Purchase order {} is {} and is read-only.".format(
                    order.po_number, order.status.value.lower()
                )
            )

        if "notes" in changes:
            order.notes = changes["notes"] or None
        if "expected_delivery_date" in changes:
            order.expected_delivery_date = changes["expected_delivery_date"]

        if "items" in changes and changes["items"] is not None:
            if not order.is_editable:
                raise ConflictError(
                    "Purchase order {} has already been placed; its lines can no longer be "
                    "changed.".format(order.po_number)
                )
            cleaned = _clean_po_lines(changes["items"])
            products = _load_products(session, [line["product_id"] for line in cleaned])
            existing = {item.product_id: item for item in order.items}

            keep: List[uuid.UUID] = []
            for line_number, line in enumerate(cleaned, start=1):
                product = products[line["product_id"]]
                item = existing.get(product.id)
                if item is None:
                    item = PurchaseOrderItem(
                        purchase_order_id=order.id, product_id=product.id, quantity_received=ZERO
                    )
                    session.add(item)
                item.line_number = line_number
                item.quantity_ordered = line["quantity_ordered"]
                item.unit_cost = line["unit_cost"]
                item.notes = line["notes"]
                keep.append(product.id)

            for item in list(order.items):
                if item.product_id not in keep:
                    session.delete(item)
            session.flush()

        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("That change would put the same product on the order twice.") from exc
    except Exception:
        session.rollback()
        raise
    return get_purchase_order(session, po_id)


def _settlements_by_product(
    settlements: Optional[Iterable[Dict[str, Any]]],
) -> Optional[Dict[uuid.UUID, List[Dict[str, Any]]]]:
    if settlements is None:
        return None
    chosen: Dict[uuid.UUID, List[Dict[str, Any]]] = {}
    for entry in settlements:
        raw_id = entry.get("product_id")
        try:
            product_id = raw_id if isinstance(raw_id, uuid.UUID) else uuid.UUID(str(raw_id))
        except (ValueError, AttributeError, TypeError):
            raise ValidationError("'{}' is not a valid product id.".format(raw_id))
        if product_id in chosen:
            raise ValidationError("Product {} is settled twice.".format(product_id))
        chosen[product_id] = [dict(row) for row in (entry.get("allocations") or [])]
    return chosen


def _settle_waiting_customers(
    session: Session,
    order: PurchaseOrder,
    settlements: Optional[Iterable[Dict[str, Any]]] = None,
    only_listed: bool = False,
) -> None:
    """A purchase counts as stock the moment it is placed, so customers who are
    short must be settled from it. ``settlements`` is the user's choice of who
    and how much; each product must settle ``min(free, short)`` exactly."""
    chosen = _settlements_by_product(settlements)
    lock_products(session, [item.product_id for item in order.items])
    for item in order.items:
        if only_listed and (chosen is None or item.product_id not in chosen):
            continue
        allocations = None if chosen is None else chosen.get(item.product_id, [])
        plan = assignments.settle_purchase_line(session, item, allocations)
        if plan:
            logger.info(
                "Purchase order %s settles %s of %s across %d waiting order line(s)",
                order.po_number,
                sum((qty for _, qty in plan), ZERO),
                item.product.sku,
                len(plan),
            )


def confirm_purchase_order(
    session: Session,
    po_id: uuid.UUID,
    settlements: Optional[Iterable[Dict[str, Any]]] = None,
) -> PurchaseOrder:
    """Place a draft order with the supplier.

    No goods move, but the purchase now counts as stock: customers waiting for
    these products are covered from it at once.
    """
    try:
        begin_write(session)
        order = get_purchase_order(session, po_id)
        if order.status != PurchaseOrderStatus.DRAFT:
            raise ConflictError(
                "Purchase order {} is already {}.".format(
                    order.po_number, order.status.value.lower()
                )
            )
        if not order.items:
            raise ValidationError(
                "Purchase order {} has no lines to place.".format(order.po_number)
            )
        order.status = PurchaseOrderStatus.ORDERED
        order.ordered_at = datetime.now(timezone.utc)
        session.flush()
        _settle_waiting_customers(session, order, settlements)
        session.commit()
    except Exception:
        session.rollback()
        raise
    logger.info("Confirmed purchase order %s", order.po_number)
    return get_purchase_order(session, po_id)


def settle_purchase_order(
    session: Session, po_id: uuid.UUID, settlements: Iterable[Dict[str, Any]]
) -> PurchaseOrder:
    """Give a placed order's unpromised quantity to customers who are short.

    Needed when cover was freed after the order was placed -- a sale or
    another purchase was cancelled. The user chooses who and how much.
    """
    try:
        begin_write(session)
        order = get_purchase_order(session, po_id)
        if not order.can_receive:
            raise ConflictError(
                "Purchase order {} is {}; only a placed order can settle customers.".format(
                    order.po_number, order.status.value.lower()
                )
            )
        _settle_waiting_customers(session, order, settlements, only_listed=True)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_purchase_order(session, po_id)


def cancel_purchase_order(
    session: Session, po_id: uuid.UUID, reason: Optional[str] = None
) -> PurchaseOrder:
    """Cancel an order. Anything already received stays received."""
    try:
        begin_write(session)
        order = get_purchase_order(session, po_id)
        if order.status == PurchaseOrderStatus.CANCELLED:
            raise ConflictError("Purchase order {} is already cancelled.".format(order.po_number))
        if order.status == PurchaseOrderStatus.RECEIVED:
            raise ConflictError(
                "Purchase order {} has been received in full and cannot be cancelled.".format(
                    order.po_number
                )
            )
        lock_products(session, [item.product_id for item in order.items])
        order.status = PurchaseOrderStatus.CANCELLED
        order.cancelled_at = datetime.now(timezone.utc)
        order.cancellation_reason = reason or None
        session.flush()
        # What this order was covering is short again. Other purchases on the
        # way can settle it, but who gets what is the user's call.
        for item in order.items:
            assignments.release_for_purchase_line(session, item)
        session.commit()
    except Exception:
        session.rollback()
        raise
    logger.info("Cancelled purchase order %s", order.po_number)
    return get_purchase_order(session, po_id)


def _recompute_po_status(order: PurchaseOrder) -> None:
    """Derive the order's status from how much of it has arrived."""
    if order.status == PurchaseOrderStatus.CANCELLED:
        return
    received = sum((item.quantity_received for item in order.items), ZERO)
    outstanding = sum((item.quantity_remaining for item in order.items), ZERO)
    if received <= ZERO:
        order.status = PurchaseOrderStatus.ORDERED
    elif outstanding > ZERO:
        order.status = PurchaseOrderStatus.PARTIALLY_RECEIVED
    else:
        order.status = PurchaseOrderStatus.RECEIVED


def to_po_view(order: PurchaseOrder) -> Dict[str, Any]:
    session = object_session(order)
    assigned = (
        assignments.assigned_map(session, [item.id for item in order.items]) if session else {}
    )
    placed = order.can_receive and session is not None
    required = {
        item.id: assignments.settle_required(session, item) if placed else ZERO
        for item in order.items
    }
    return {
        "id": order.id,
        "po_number": order.po_number,
        "supplier_id": order.supplier_id,
        "supplier": order.supplier,
        "status": order.status,
        "expected_delivery_date": order.expected_delivery_date,
        "ordered_at": order.ordered_at,
        "cancelled_at": order.cancelled_at,
        "cancellation_reason": order.cancellation_reason,
        "notes": order.notes,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "is_editable": order.is_editable,
        "can_receive": order.can_receive,
        "item_count": len(order.items),
        "items": [
            {
                "id": item.id,
                "product_id": item.product_id,
                "product": item.product,
                "line_number": item.line_number,
                "quantity_ordered": item.quantity_ordered,
                "quantity_received": item.quantity_received,
                "quantity_remaining": item.quantity_remaining,
                "unit_cost": item.unit_cost,
                "line_cost": money(item.unit_cost * item.quantity_ordered),
                "notes": item.notes,
                "quantity_assigned": assigned.get(item.id, ZERO),
                "quantity_free": max(
                    ZERO, item.quantity_remaining - assigned.get(item.id, ZERO)
                ) if placed else ZERO,
                "settle_required": required[item.id],
            }
            for item in order.items
        ],
        "total_ordered": sum((item.quantity_ordered for item in order.items), ZERO),
        "total_received": sum((item.quantity_received for item in order.items), ZERO),
        "total_remaining": sum((item.quantity_remaining for item in order.items), ZERO),
        "total_cost": money(
            sum((item.unit_cost * item.quantity_ordered for item in order.items), ZERO_MONEY)
        ),
        "receipts": [
            {
                "id": receipt.id,
                "receipt_number": receipt.receipt_number,
                "created_at": receipt.created_at,
                "delivery_note_reference": receipt.delivery_note_reference,
                "total_quantity": sum((line.quantity for line in receipt.items), ZERO),
            }
            for receipt in sorted(order.receipts, key=lambda row: row.created_at, reverse=True)
        ],
    }


# ---------------------------------------------------------------------------
# Goods receipts
# ---------------------------------------------------------------------------

def _clean_receipt_lines(
    order: PurchaseOrder, lines: Iterable[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Validate what is being received against what is still outstanding."""
    items_by_id = {item.id: item for item in order.items}
    cleaned: List[Dict[str, Any]] = []
    seen: set = set()

    for index, line in enumerate(lines, start=1):
        raw_id = line.get("purchase_order_item_id")
        try:
            item_id = raw_id if isinstance(raw_id, uuid.UUID) else uuid.UUID(str(raw_id))
        except (ValueError, AttributeError, TypeError):
            raise ValidationError(
                "Line {}: '{}' is not a valid purchase order line id.".format(index, raw_id)
            )
        if item_id in seen:
            raise ValidationError(
                "Purchase order line {} appears more than once in this receipt.".format(item_id)
            )
        seen.add(item_id)

        po_item = items_by_id.get(item_id)
        if po_item is None:
            raise NotFoundError(
                "Line {} is not part of purchase order {}.".format(item_id, order.po_number)
            )

        qty = quantity(line.get("quantity", 0), "Line {} quantity".format(index))
        if qty <= ZERO:
            continue

        cost = line.get("unit_cost")
        # Default to what was agreed when ordering; the actual price may differ.
        actual_cost = (
            po_item.unit_cost
            if cost is None or cost == ""
            else require_non_negative(
                unit_cost(cost, "Line {} unit cost".format(index)),
                "Line {} unit cost".format(index),
            )
        )

        cleaned.append(
            {
                "purchase_order_item": po_item,
                "quantity": qty,
                "unit_cost": actual_cost,
                "over_receipt_reason": (line.get("over_receipt_reason") or None),
                "allocations": line.get("allocations"),
            }
        )

    if not cleaned:
        raise ValidationError("A goods receipt must contain at least one quantity received.")
    return cleaned


def _check_over_receipt(
    line: Dict[str, Any], allow_over_receipt: bool
) -> bool:
    """Reject more than the PO is still owed, unless explicitly overridden."""
    po_item = line["purchase_order_item"]
    remaining = po_item.quantity_remaining
    if line["quantity"] <= remaining:
        return False
    if not allow_over_receipt:
        raise ValidationError(
            "{} has only {} outstanding on this purchase order, but {} was entered. Tick the "
            "over-receipt override and give a reason to accept more than was ordered.".format(
                po_item.product.sku, remaining, line["quantity"]
            ),
            details={
                "purchase_order_item_id": str(po_item.id),
                "quantity_remaining": str(remaining),
            },
        )
    if not line["over_receipt_reason"]:
        raise ValidationError(
            "An over-receipt of {} needs a recorded reason.".format(po_item.product.sku)
        )
    return True


def preview_receipt(
    session: Session, po_id: uuid.UUID, lines: Iterable[Dict[str, Any]]
) -> Dict[str, Any]:
    """What would happen if this receipt were confirmed. Writes nothing."""
    order = get_purchase_order(session, po_id)
    if order.status == PurchaseOrderStatus.CANCELLED:
        raise ConflictError(
            "Purchase order {} is cancelled; goods cannot be received against it.".format(
                order.po_number
            )
        )

    cleaned = _clean_receipt_lines(order, lines)
    previews = []
    for line in cleaned:
        po_item = line["purchase_order_item"]
        product = po_item.product
        received = line["quantity"]

        is_over = received > po_item.quantity_remaining
        # Who this PO line was covering, plus anyone nothing covers.
        items, capacity = assignments.receipt_candidates(session, product, po_item.id)
        demand = reservations.unallocated_total(items, capacity)
        required = min(received, demand)
        proposals = reservations.propose_fifo(items, received, capacity)

        physical = Decimal(str(product.physical_stock))
        reserved_now = reservations.reserved_for_product(session, product.id)
        # Stock counted these units when the purchase order was confirmed; only
        # an over-receipt adds to it.
        stock_now = stock_for_product(session, product)
        extra = max(ZERO, received - po_item.quantity_remaining)

        previews.append(
            {
                "purchase_order_item_id": po_item.id,
                "product_id": product.id,
                "product_sku": product.sku,
                "product_name": product.name,
                "unit_of_measure": product.unit_of_measure,
                "quantity_ordered": po_item.quantity_ordered,
                "quantity_already_received": po_item.quantity_received,
                "quantity_remaining": po_item.quantity_remaining,
                "quantity_receiving": received,
                "is_over_receipt": is_over,
                "unit_cost": line["unit_cost"],
                "line_cost": money(line["unit_cost"] * received),
                "eligible_demand": demand,
                "required_allocation": required,
                "surplus_quantity": received - required,
                "physical_stock": physical,
                "reserved_stock": reserved_now,
                "available_stock": physical - reserved_now,
                "physical_stock_after": physical + received,
                "reserved_stock_after": reserved_now + required,
                "available_stock_after": physical + received - reserved_now - required,
                "pending_quantity": pending_quantity_for_product(session, product.id),
                "stock": stock_now,
                "stock_after": stock_now + extra,
                "allocations": [
                    {
                        "order_item_id": item.id,
                        "order_id": item.order_id,
                        "order_number": item.order.order_number,
                        "order_created_at": item.order.created_at,
                        "customer_id": item.order.customer_id,
                        "customer_name": item.order.customer.name,
                        "quantity_ordered": item.quantity_ordered,
                        "quantity_delivered": item.quantity_fulfilled,
                        "quantity_reserved": item.quantity_reserved,
                        "quantity_outstanding": item.quantity_pending,
                        "quantity_unallocated": item.quantity_unallocated,
                        "quantity_incoming": item.quantity_incoming,
                        "quantity_eligible": capacity[item.id],
                        "proposed_allocation": proposal,
                    }
                    for item, proposal in zip(items, proposals)
                ],
            }
        )

    return {
        "purchase_order_id": order.id,
        "po_number": order.po_number,
        "supplier_id": order.supplier_id,
        "supplier_name": order.supplier.name,
        "status": order.status,
        "lines": previews,
        "total_receiving": sum((row["quantity_receiving"] for row in previews), ZERO),
        "total_required_allocation": sum((row["required_allocation"] for row in previews), ZERO),
        "total_surplus": sum((row["surplus_quantity"] for row in previews), ZERO),
        "total_cost": money(sum((row["line_cost"] for row in previews), ZERO_MONEY)),
    }


def _receipt_result(session: Session, receipt: GoodsReceipt) -> Dict[str, Any]:
    order = get_purchase_order(session, receipt.purchase_order_id)
    lines = []
    for line in receipt.items:
        product = line.product
        physical = Decimal(str(product.physical_stock))
        reserved_now = reservations.reserved_for_product(session, product.id)
        pending_now = pending_quantity_for_product(session, product.id)
        allocations = [
            {
                "order_item_id": row["order_item_id"],
                "order_id": row["order_id"],
                "order_number": row["order_number"],
                "customer_id": row["customer_id"],
                "customer_name": row["customer_name"],
                "quantity_allocated": row["quantity"],
                "quantity_outstanding": row["quantity_outstanding"],
                "quantity_reserved": row["quantity_reserved"],
            }
            for row in _receipt_line_allocations(session, line.id)
        ]
        allocated = sum((row["quantity_allocated"] for row in allocations), ZERO)
        lines.append(
            {
                "goods_receipt_item_id": line.id,
                "purchase_order_item_id": line.purchase_order_item_id,
                "product_id": product.id,
                "product_sku": product.sku,
                "product_name": product.name,
                "unit_of_measure": product.unit_of_measure,
                "quantity_received": line.quantity,
                "unit_cost": line.unit_cost,
                "total_cost": line.total_cost,
                "is_over_receipt": line.is_over_receipt,
                "over_receipt_reason": line.over_receipt_reason,
                "quantity_allocated": allocated,
                "surplus_quantity": line.quantity - allocated,
                "quantity_ordered_on_po": line.purchase_order_item.quantity_ordered,
                "quantity_received_on_po": line.purchase_order_item.quantity_received,
                "quantity_remaining_on_po": line.purchase_order_item.quantity_remaining,
                "physical_stock_after": physical,
                "reserved_stock_after": reserved_now,
                "available_stock_after": physical - reserved_now,
                "net_stock_position_after": physical - pending_now,
                "stock_after": stock_for_product(session, product),
                "allocations": allocations,
            }
        )

    return {
        "receipt_id": receipt.id,
        "receipt_number": receipt.receipt_number,
        "created_at": receipt.created_at,
        "purchase_order_id": order.id,
        "po_number": order.po_number,
        "po_status": order.status,
        "supplier_id": receipt.supplier_id,
        "supplier_name": order.supplier.name,
        "delivery_note_reference": receipt.delivery_note_reference,
        "notes": receipt.notes,
        "lines": lines,
        "total_received": sum((row["quantity_received"] for row in lines), ZERO),
        "total_allocated": sum((row["quantity_allocated"] for row in lines), ZERO),
        "total_surplus": sum((row["surplus_quantity"] for row in lines), ZERO),
        "total_cost": money(sum((row["total_cost"] for row in lines), ZERO_MONEY)),
    }


def _receipt_line_allocations(
    session: Session, goods_receipt_item_id: uuid.UUID
) -> List[Dict[str, Any]]:
    from ..models import SalesOrder, SalesOrderItem, StockReservation

    rows = session.execute(
        select(StockReservation, SalesOrderItem, SalesOrder)
        .join(SalesOrderItem, StockReservation.order_item_id == SalesOrderItem.id)
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .where(StockReservation.goods_receipt_item_id == goods_receipt_item_id)
        .order_by(StockReservation.created_at)
        .options(joinedload(SalesOrder.customer))
    ).unique().all()
    return [
        {
            "order_item_id": item.id,
            "order_id": order.id,
            "order_number": order.order_number,
            "customer_id": order.customer_id,
            "customer_name": order.customer.name,
            "quantity": reservation.quantity,
            "quantity_outstanding": item.quantity_pending,
            "quantity_reserved": item.quantity_reserved,
        }
        for reservation, item, order in rows
    ]


def create_goods_receipt(
    session: Session,
    po_id: uuid.UUID,
    lines: Iterable[Dict[str, Any]],
    delivery_note_reference: Optional[str] = None,
    notes: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    allow_over_receipt: bool = False,
) -> Dict[str, Any]:
    """Book goods in against a purchase order and settle waiting customers.

    Physical stock rises by what actually arrived; the part of it that waiting
    customer orders are owed is reserved to them before any of it becomes
    available to anyone else. The receipt, the ledger movements, the cost layers
    and the reservations are one transaction.
    """
    begin_write(session)

    if idempotency_key:
        existing = session.execute(
            select(GoodsReceipt).where(GoodsReceipt.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing is not None:
            logger.info("Replaying goods receipt for idempotency key %s", idempotency_key)
            if existing.result_json:
                return json.loads(existing.result_json)
            raise ConflictError("This goods receipt has already been recorded.")

    try:
        stmt = select(PurchaseOrder).where(PurchaseOrder.id == po_id).with_for_update()
        if session.execute(stmt).scalar_one_or_none() is None:
            raise NotFoundError("Purchase order {} does not exist.".format(po_id))

        order = get_purchase_order(session, po_id)
        if order.status == PurchaseOrderStatus.CANCELLED:
            raise ConflictError(
                "Purchase order {} is cancelled; goods cannot be received against it.".format(
                    order.po_number
                )
            )
        if not order.can_receive:
            raise ConflictError(
                "Purchase order {} is {}; only a placed order can receive goods.".format(
                    order.po_number, order.status.value.lower()
                )
            )

        cleaned = _clean_receipt_lines(order, lines)
        products = lock_products(
            session, [line["purchase_order_item"].product_id for line in cleaned]
        )

        receipt = GoodsReceipt(
            receipt_number=next_document_number(session, GOODS_RECEIPT_COUNTER, "GR"),
            purchase_order_id=order.id,
            supplier_id=order.supplier_id,
            delivery_note_reference=delivery_note_reference,
            notes=notes,
            idempotency_key=idempotency_key,
        )
        session.add(receipt)
        session.flush()

        for line in cleaned:
            po_item = line["purchase_order_item"]
            product = products[po_item.product_id]
            received = line["quantity"]
            is_over = _check_over_receipt(line, allow_over_receipt)

            receipt_item = GoodsReceiptItem(
                goods_receipt_id=receipt.id,
                purchase_order_item_id=po_item.id,
                product_id=product.id,
                quantity=received,
                unit_cost=line["unit_cost"],
                total_cost=money(line["unit_cost"] * received),
                is_over_receipt=is_over,
                over_receipt_reason=line["over_receipt_reason"] if is_over else None,
            )
            session.add(receipt_item)
            session.flush()

            movement = record_movement(
                session,
                product,
                MovementType.GOODS_RECEIPT,
                received,
                reference_type="goods_receipt_item",
                reference_id=receipt_item.id,
                note="Received on {} against {}".format(receipt.receipt_number, order.po_number),
            )
            receipt_item.stock_movement_id = movement.id

            costing.open_cost_layer(
                session,
                product,
                received,
                line["unit_cost"],
                MovementType.GOODS_RECEIPT,
                receipt_item.id,
                "Goods receipt {}".format(receipt.receipt_number),
            )

            # The compulsory bit: the customers this purchase was covering, and
            # anyone nothing covers, get the goods before any of it is free.
            items, capacity = assignments.receipt_candidates(session, product, po_item.id)
            plan = reservations.validate_allocation(
                items, line["allocations"], received, "goods receipt", capacity
            )
            for item, qty in plan:
                assignments.draw_on_receipt(session, po_item.id, item, qty)
            reservations.reserve(
                session,
                product,
                plan,
                AllocationSource.GOODS_RECEIPT,
                goods_receipt_item_id=receipt_item.id,
            )

            po_item.quantity_received = po_item.quantity_received + received
            session.flush()
            # Cover can never exceed what the line still has to deliver.
            assignments.trim_to_remaining(session, po_item)

        session.flush()
        session.expire(order)
        _recompute_po_status(get_purchase_order(session, order.id))
        session.flush()

        result = _receipt_result(session, receipt)
        receipt.result_json = json.dumps(result, default=str)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            "The goods receipt could not be saved because it conflicts with an existing "
            "record. Nothing was changed."
        ) from exc
    except Exception:
        session.rollback()
        raise

    logger.info(
        "Goods receipt %s against %s: %s units in, %s reserved to customers",
        result["receipt_number"],
        result["po_number"],
        result["total_received"],
        result["total_allocated"],
    )
    return result


def get_goods_receipt(session: Session, receipt_id: uuid.UUID) -> Dict[str, Any]:
    receipt = session.get(GoodsReceipt, receipt_id)
    if receipt is None:
        raise NotFoundError("Goods receipt {} does not exist.".format(receipt_id))
    return _receipt_result(session, receipt)


def count_goods_receipts(
    session: Session,
    search: Optional[str] = None,
    supplier_id: Optional[uuid.UUID] = None,
    purchase_order_id: Optional[uuid.UUID] = None,
) -> int:
    return count_matching(session, _receipt_filter(search, supplier_id, purchase_order_id))


def _receipt_filter(
    search: Optional[str],
    supplier_id: Optional[uuid.UUID],
    purchase_order_id: Optional[uuid.UUID],
):
    stmt = select(GoodsReceipt)
    if supplier_id:
        stmt = stmt.where(GoodsReceipt.supplier_id == supplier_id)
    if purchase_order_id:
        stmt = stmt.where(GoodsReceipt.purchase_order_id == purchase_order_id)
    if search:
        pattern = "%{}%".format(search.strip().lower())
        stmt = stmt.where(
            or_(
                func.lower(GoodsReceipt.receipt_number).like(pattern),
                func.lower(func.coalesce(GoodsReceipt.delivery_note_reference, "")).like(pattern),
                GoodsReceipt.supplier_id.in_(
                    select(Supplier.id).where(func.lower(Supplier.name).like(pattern))
                ),
            )
        )
    return stmt


def list_goods_receipts(
    session: Session,
    search: Optional[str] = None,
    supplier_id: Optional[uuid.UUID] = None,
    purchase_order_id: Optional[uuid.UUID] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    stmt = (
        _receipt_filter(search, supplier_id, purchase_order_id)
        .options(
            joinedload(GoodsReceipt.supplier),
            joinedload(GoodsReceipt.purchase_order),
            joinedload(GoodsReceipt.items).joinedload(GoodsReceiptItem.product),
        )
        .order_by(GoodsReceipt.created_at.desc(), GoodsReceipt.receipt_number.desc())
    )
    return [
        {
            "id": receipt.id,
            "receipt_number": receipt.receipt_number,
            "created_at": receipt.created_at,
            "purchase_order_id": receipt.purchase_order_id,
            "po_number": receipt.purchase_order.po_number,
            "supplier_id": receipt.supplier_id,
            "supplier_name": receipt.supplier.name,
            "delivery_note_reference": receipt.delivery_note_reference,
            "notes": receipt.notes,
            "line_count": len(receipt.items),
            "total_quantity": sum((line.quantity for line in receipt.items), ZERO),
            "total_cost": money(sum((line.total_cost for line in receipt.items), ZERO_MONEY)),
            "lines": [
                {
                    "product_id": line.product_id,
                    "product_sku": line.product.sku,
                    "product_name": line.product.name,
                    "unit_of_measure": line.product.unit_of_measure,
                    "quantity": line.quantity,
                    "unit_cost": line.unit_cost,
                    "is_over_receipt": line.is_over_receipt,
                }
                for line in receipt.items
            ],
        }
        for receipt in session.execute(windowed(stmt, limit, offset)).unique().scalars().all()
    ]
