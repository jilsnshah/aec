"""Customer enquiry service.

An enquiry is a deal being negotiated: the products a customer asked for, the
quantity of each, and the discount agreed on each. Prices are always worked out
by :mod:`app.services.pricing` from an MRP read out of the product master --
never from a figure the client sent.

When the deal is won the enquiry is converted by calling the Phase 1 order
builder, so stock allocation, partial fulfilment and pending quantities behave
exactly as they do for an order entered directly. Conversion and order creation
share one transaction: an enquiry can never end up marked CONVERTED without a
sales order behind it.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..database import begin_write
from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import (
    Customer,
    CustomerEnquiry,
    CustomerEnquiryItem,
    EnquiryStatus,
    Product,
    SalesOrder,
)
from ..numeric import ZERO, ZERO_MONEY, money, percent, quantity, unit_cost
from . import pricing
from .common import count_matching, get_customer, next_document_number, windowed
from .orders import build_order, get_order

logger = logging.getLogger(__name__)

ENQUIRY_COUNTER = "customer_enquiry"


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def _with_relations(stmt):
    """Eager-load everything a listing or detail view renders, in one round trip."""
    return stmt.options(
        joinedload(CustomerEnquiry.customer),
        joinedload(CustomerEnquiry.items).joinedload(CustomerEnquiryItem.product),
        joinedload(CustomerEnquiry.sales_order),
    )


def get_enquiry(session: Session, enquiry_id: uuid.UUID) -> CustomerEnquiry:
    enquiry = (
        session.execute(
            _with_relations(select(CustomerEnquiry).where(CustomerEnquiry.id == enquiry_id))
            .execution_options(populate_existing=True)
        )
        .unique()
        .scalar_one_or_none()
    )
    if enquiry is None:
        raise NotFoundError("Enquiry {} does not exist.".format(enquiry_id))
    return enquiry


def count_enquiries(
    session: Session,
    search: Optional[str] = None,
    status: Optional[str] = None,
    customer_id: Optional[uuid.UUID] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
) -> int:
    return count_matching(
        session, _enquiry_filter(search, status, customer_id, created_from, created_to)
    )


def list_enquiries(
    session: Session,
    search: Optional[str] = None,
    status: Optional[str] = None,
    customer_id: Optional[uuid.UUID] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> List[CustomerEnquiry]:
    stmt = _with_relations(
        _enquiry_filter(search, status, customer_id, created_from, created_to)
    ).order_by(CustomerEnquiry.created_at.desc(), CustomerEnquiry.enquiry_number.desc())
    return list(session.execute(windowed(stmt, limit, offset)).unique().scalars().all())


def _enquiry_filter(
    search: Optional[str],
    status: Optional[str],
    customer_id: Optional[uuid.UUID],
    created_from: Optional[datetime],
    created_to: Optional[datetime],
):
    stmt = select(CustomerEnquiry)
    if status:
        try:
            stmt = stmt.where(CustomerEnquiry.status == EnquiryStatus(status))
        except ValueError:
            raise ValidationError("'{}' is not a valid enquiry status.".format(status))
    if customer_id:
        stmt = stmt.where(CustomerEnquiry.customer_id == customer_id)
    if created_from:
        stmt = stmt.where(CustomerEnquiry.created_at >= created_from)
    if created_to:
        stmt = stmt.where(CustomerEnquiry.created_at <= created_to)
    if search:
        pattern = "%{}%".format(search.strip().lower())
        stmt = stmt.where(
            or_(
                func.lower(CustomerEnquiry.enquiry_number).like(pattern),
                CustomerEnquiry.customer_id.in_(
                    select(Customer.id).where(func.lower(Customer.name).like(pattern))
                ),
            )
        )
    return stmt


def enquiry_total(enquiry: CustomerEnquiry) -> Decimal:
    """Value of the enquiry before tax."""
    return money(sum((item.line_total for item in enquiry.items), ZERO_MONEY))


def enquiry_mrp_total(enquiry: CustomerEnquiry) -> Decimal:
    return money(sum((item.mrp_snapshot * item.quantity for item in enquiry.items), ZERO_MONEY))


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _require_open(enquiry: CustomerEnquiry, action: str) -> None:
    if enquiry.status != EnquiryStatus.OPEN:
        raise ConflictError(
            "Enquiry {} is {} and is read-only; it cannot be {}.".format(
                enquiry.enquiry_number, enquiry.status.value.lower(), action
            ),
            details={
                "status": enquiry.status.value,
                "sales_order_id": str(enquiry.sales_order_id) if enquiry.sales_order_id else None,
            },
        )


def _clean_items(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate the requested lines and consolidate repeats of the same product.

    Adding a product twice is a slip, not an error: the quantities are added
    together and the later discount wins, which is what the operator meant.
    """
    merged: Dict[uuid.UUID, Dict[str, Any]] = {}
    order: List[uuid.UUID] = []

    for index, item in enumerate(items, start=1):
        raw_id = item.get("product_id")
        try:
            product_id = raw_id if isinstance(raw_id, uuid.UUID) else uuid.UUID(str(raw_id))
        except (ValueError, AttributeError, TypeError):
            raise ValidationError("Line {}: '{}' is not a valid product id.".format(index, raw_id))

        qty = quantity(item.get("quantity", 0), "Line {} quantity".format(index))
        if qty <= ZERO:
            raise ValidationError("Line {} quantity must be greater than zero.".format(index))
        discount = percent(item.get("discount_percent") or 0, "Line {} discount".format(index))

        if product_id in merged:
            merged[product_id]["quantity"] = merged[product_id]["quantity"] + qty
            merged[product_id]["discount_percent"] = discount
        else:
            merged[product_id] = {
                "product_id": product_id,
                "quantity": qty,
                "discount_percent": discount,
            }
            order.append(product_id)

    if not merged:
        raise ValidationError("An enquiry must contain at least one product line.")
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
                "Product '{}' is archived and cannot be added to an enquiry.".format(product.sku)
            )
    return found


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def create_enquiry(
    session: Session,
    customer_id: uuid.UUID,
    items: Iterable[Dict[str, Any]],
    notes: Optional[str] = None,
    source: str = "manual",
    source_detail: Optional[str] = None,
) -> CustomerEnquiry:
    """Open an enquiry, pricing each line from the product master's MRP.

    ``source`` says where it came from -- ``manual``, ``whatsapp`` or
    ``email`` -- and ``source_detail`` who sent it, for captured enquiries.
    """
    cleaned = _clean_items(items)

    try:
        begin_write(session)
        customer = get_customer(session, customer_id)
        if not customer.is_active:
            raise ValidationError(
                "Customer '{}' is archived; reactivate them before taking an enquiry.".format(
                    customer.name
                )
            )
        products = _load_products(session, [line["product_id"] for line in cleaned])

        enquiry = CustomerEnquiry(
            enquiry_number=next_document_number(session, ENQUIRY_COUNTER, "ENQ"),
            customer_id=customer.id,
            notes=notes,
            status=EnquiryStatus.OPEN,
            source=source,
            source_detail=source_detail,
        )
        session.add(enquiry)
        session.flush()

        for line_number, line in enumerate(cleaned, start=1):
            product = products[line["product_id"]]
            # The MRP is read here, from the product master. A price sent by the
            # client is never used.
            quote = pricing.quote_line(
                product.mrp, line["quantity"], line["discount_percent"], "Line {}".format(line_number)
            )
            session.add(
                CustomerEnquiryItem(
                    enquiry_id=enquiry.id,
                    product_id=product.id,
                    line_number=line_number,
                    quantity=quote["quantity"],
                    mrp_snapshot=quote["mrp_snapshot"],
                    discount_percent=quote["discount_percent"],
                    quoted_unit_price=quote["quoted_unit_price"],
                    line_total=quote["line_total"],
                )
            )

        session.commit()
    except Exception:
        session.rollback()
        raise

    logger.info(
        "Created enquiry %s for customer %s with %d line(s)",
        enquiry.enquiry_number,
        customer_id,
        len(cleaned),
    )
    return get_enquiry(session, enquiry.id)


def update_enquiry(
    session: Session, enquiry_id: uuid.UUID, changes: Dict[str, Any]
) -> CustomerEnquiry:
    """Edit an open enquiry: its notes, its lines, its quantities, its discounts.

    A line that is still for the same product keeps the MRP it was opened
    against -- that is the figure the deal is being negotiated on, and a later
    MRP change must not move it. A newly added product is snapshotted at today's
    MRP.
    """
    try:
        begin_write(session)
        enquiry = get_enquiry(session, enquiry_id)
        _require_open(enquiry, "edited")

        if "notes" in changes:
            enquiry.notes = changes["notes"] or None

        if "items" in changes and changes["items"] is not None:
            cleaned = _clean_items(changes["items"])
            products = _load_products(session, [line["product_id"] for line in cleaned])
            existing = {item.product_id: item for item in enquiry.items}

            kept: List[CustomerEnquiryItem] = []
            for line_number, line in enumerate(cleaned, start=1):
                product = products[line["product_id"]]
                item = existing.get(product.id)
                # Keep the agreed MRP for a line that is already on the enquiry.
                mrp = item.mrp_snapshot if item is not None else product.mrp
                quote = pricing.quote_line(
                    mrp, line["quantity"], line["discount_percent"], "Line {}".format(line_number)
                )
                if item is None:
                    item = CustomerEnquiryItem(enquiry_id=enquiry.id, product_id=product.id)
                    session.add(item)
                item.line_number = line_number
                item.quantity = quote["quantity"]
                item.mrp_snapshot = quote["mrp_snapshot"]
                item.discount_percent = quote["discount_percent"]
                item.quoted_unit_price = quote["quoted_unit_price"]
                item.line_total = quote["line_total"]
                kept.append(item)

            keep_ids = {id(item) for item in kept}
            for item in list(enquiry.items):
                if id(item) not in keep_ids and item.product_id not in {
                    line["product_id"] for line in cleaned
                }:
                    session.delete(item)

            session.flush()

        enquiry.updated_at = datetime.now(timezone.utc)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            "That change would put the same product on the enquiry twice."
        ) from exc
    except Exception:
        session.rollback()
        raise

    return get_enquiry(session, enquiry_id)


def mark_lost(
    session: Session, enquiry_id: uuid.UUID, reason: Optional[str] = None
) -> CustomerEnquiry:
    """Close an enquiry that did not become a deal. No order, no stock movement."""
    try:
        begin_write(session)
        enquiry = get_enquiry(session, enquiry_id)
        _require_open(enquiry, "marked lost")
        enquiry.status = EnquiryStatus.LOST
        enquiry.lost_at = datetime.now(timezone.utc)
        enquiry.lost_reason = reason or None
        session.commit()
    except Exception:
        session.rollback()
        raise

    logger.info("Enquiry %s marked lost", enquiry.enquiry_number)
    return get_enquiry(session, enquiry_id)


def convert_enquiry(session: Session, enquiry_id: uuid.UUID) -> Dict[str, Any]:
    """Win the deal: create the sales order and close the enquiry.

    The order is built by the Phase 1 service, inside this transaction, so stock
    allocation, partial fulfilment and pending quantities are identical to an
    order entered directly. If anything fails, the whole thing rolls back and
    the enquiry stays OPEN.

    Converting twice is impossible three times over: the enquiry row is locked
    for the duration, its status is re-read under that lock, and
    ``sales_orders.enquiry_id`` is UNIQUE.
    """
    try:
        begin_write(session)

        stmt = select(CustomerEnquiry).where(CustomerEnquiry.id == enquiry_id).with_for_update()
        locked = session.execute(stmt).scalar_one_or_none()
        if locked is None:
            raise NotFoundError("Enquiry {} does not exist.".format(enquiry_id))

        enquiry = get_enquiry(session, enquiry_id)
        if enquiry.status == EnquiryStatus.CONVERTED:
            order = enquiry.sales_order
            raise ConflictError(
                "Enquiry {} has already been converted into order {}.".format(
                    enquiry.enquiry_number, order.order_number if order else "?"
                ),
                details={
                    "sales_order_id": str(enquiry.sales_order_id),
                    "order_number": order.order_number if order else None,
                },
            )
        _require_open(enquiry, "converted")

        if not enquiry.items:
            raise ValidationError(
                "Enquiry {} has no product lines to convert.".format(enquiry.enquiry_number)
            )

        # Re-price every line from the stored MRP snapshot and the agreed
        # discount. Nothing here comes from the client.
        lines = []
        for item in enquiry.items:
            quote = pricing.quote_line(
                item.mrp_snapshot,
                item.quantity,
                item.discount_percent,
                "Line {}".format(item.line_number),
            )
            item.quoted_unit_price = quote["quoted_unit_price"]
            item.line_total = quote["line_total"]
            lines.append(
                {
                    "product_id": item.product_id,
                    "quantity_ordered": quote["quantity"],
                    # The deal was struck against the snapshot, so the order is
                    # priced from it too, not from today's MRP.
                    "unit_price": quote["mrp_snapshot"],
                    "discount_percent": quote["discount_percent"],
                    "mrp_snapshot": quote["mrp_snapshot"],
                }
            )

        order_notes = "Converted from enquiry {}".format(enquiry.enquiry_number)
        if enquiry.notes:
            order_notes = "{}\n{}".format(order_notes, enquiry.notes)

        order = build_order(
            session,
            customer_id=enquiry.customer_id,
            lines=lines,
            notes=order_notes,
            enquiry_id=enquiry.id,
        )

        enquiry.sales_order_id = order.id
        enquiry.status = EnquiryStatus.CONVERTED
        enquiry.converted_at = datetime.now(timezone.utc)
        session.flush()
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        # The UNIQUE on sales_orders.enquiry_id caught a racing second attempt.
        raise ConflictError(
            "This enquiry has already been converted into a sales order."
        ) from exc
    except Exception:
        session.rollback()
        raise

    logger.info(
        "Converted enquiry %s into order %s", enquiry.enquiry_number, order.order_number
    )
    return {
        "enquiry": get_enquiry(session, enquiry_id),
        "order": get_order(session, order.id),
    }


# ---------------------------------------------------------------------------
# Read model
# ---------------------------------------------------------------------------

def to_view(enquiry: CustomerEnquiry) -> Dict[str, Any]:
    """Shape an enquiry for the API, with its totals worked out."""
    mrp_total = enquiry_mrp_total(enquiry)
    total = enquiry_total(enquiry)
    return {
        "id": enquiry.id,
        "enquiry_number": enquiry.enquiry_number,
        "customer_id": enquiry.customer_id,
        "customer": enquiry.customer,
        "notes": enquiry.notes,
        "status": enquiry.status,
        "created_at": enquiry.created_at,
        "updated_at": enquiry.updated_at,
        "converted_at": enquiry.converted_at,
        "lost_at": enquiry.lost_at,
        "lost_reason": enquiry.lost_reason,
        "source": enquiry.source,
        "source_detail": enquiry.source_detail,
        "sales_order_id": enquiry.sales_order_id,
        "sales_order_number": (
            enquiry.sales_order.order_number if enquiry.sales_order is not None else None
        ),
        "is_editable": enquiry.is_editable,
        "item_count": len(enquiry.items),
        "items": [
            {
                "id": item.id,
                "product_id": item.product_id,
                "product": item.product,
                "line_number": item.line_number,
                "quantity": item.quantity,
                "mrp_snapshot": item.mrp_snapshot,
                "discount_percent": item.discount_percent,
                "quoted_unit_price": item.quoted_unit_price,
                "line_total": item.line_total,
                "discount_amount": pricing.discount_amount(
                    item.mrp_snapshot, item.quoted_unit_price, item.quantity
                ),
            }
            for item in enquiry.items
        ],
        # Before tax: this phase does not calculate tax at all.
        "mrp_total": mrp_total,
        "discount_total": money(mrp_total - total),
        "total_amount": total,
    }
