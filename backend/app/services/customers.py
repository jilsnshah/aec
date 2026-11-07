"""Customer master service."""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..errors import NotFoundError, ValidationError
from ..models import Customer, OrderStatus, Product, SalesOrder, SalesOrderItem
from ..numeric import ZERO_MONEY, aggregate, money
from ..database import begin_write
from .common import count_matching, pending_quantity_expression, windowed

logger = logging.getLogger(__name__)

SORTABLE_FIELDS = {
    "name": Customer.name,
    "created_at": Customer.created_at,
    "updated_at": Customer.updated_at,
}


def get_customer(session: Session, customer_id: uuid.UUID) -> Customer:
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError("Customer {} does not exist.".format(customer_id))
    return customer


def count_customers(
    session: Session, search: Optional[str] = None, include_inactive: bool = False
) -> int:
    return count_matching(session, _customer_filter(search, include_inactive))


def list_customers(
    session: Session,
    search: Optional[str] = None,
    include_inactive: bool = False,
    sort_by: str = "name",
    sort_dir: str = "asc",
    limit: Optional[int] = None,
    offset: int = 0,
) -> List[Customer]:
    stmt = _customer_filter(search, include_inactive)
    column = SORTABLE_FIELDS.get(sort_by, Customer.name)
    stmt = stmt.order_by(column.desc() if sort_dir == "desc" else column.asc(), Customer.id)
    return list(session.execute(windowed(stmt, limit, offset)).scalars().all())


def customer_stats(session: Session, customer_ids: List[uuid.UUID]) -> Dict[uuid.UUID, Dict[str, Any]]:
    """Trading summary per customer, for listings: two grouped queries in all."""
    if not customer_ids:
        return {}
    live = SalesOrder.status != OrderStatus.CANCELLED
    open_statuses = [OrderStatus.PENDING, OrderStatus.PARTIALLY_FULFILLED]
    stats: Dict[uuid.UUID, Dict[str, Any]] = {
        customer_id: {
            "order_count": 0,
            "open_order_count": 0,
            "ordered_value": ZERO_MONEY,
            "outstanding_quantity": aggregate(None),
            "outstanding_value": ZERO_MONEY,
            "last_order_at": None,
        }
        for customer_id in customer_ids
    }
    order_rows = session.execute(
        select(
            SalesOrder.customer_id,
            func.count(SalesOrder.id).filter(live),
            func.count(SalesOrder.id).filter(SalesOrder.status.in_(open_statuses)),
            func.sum(SalesOrder.total_amount).filter(live),
            func.max(SalesOrder.created_at),
        )
        .where(SalesOrder.customer_id.in_(customer_ids))
        .group_by(SalesOrder.customer_id)
    ).all()
    for customer_id, count, open_count, value, last_at in order_rows:
        stats[customer_id].update(
            order_count=count,
            open_order_count=open_count,
            ordered_value=money(value or 0),
            last_order_at=last_at,
        )
    pending = pending_quantity_expression()
    owed_rows = session.execute(
        select(
            SalesOrder.customer_id,
            func.sum(pending),
            func.sum(pending * SalesOrderItem.unit_price_net),
        )
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .where(SalesOrder.customer_id.in_(customer_ids), live, pending > 0)
        .group_by(SalesOrder.customer_id)
    ).all()
    for customer_id, owed, owed_value in owed_rows:
        stats[customer_id].update(
            outstanding_quantity=aggregate(owed), outstanding_value=money(owed_value or 0)
        )
    return stats


def _customer_filter(search: Optional[str], include_inactive: bool):
    stmt = select(Customer)
    if not include_inactive:
        stmt = stmt.where(Customer.is_active.is_(True))
    if search:
        pattern = "%{}%".format(search.strip().lower())
        stmt = stmt.where(
            or_(
                func.lower(Customer.name).like(pattern),
                func.lower(func.coalesce(Customer.phone, "")).like(pattern),
                func.lower(func.coalesce(Customer.email, "")).like(pattern),
            )
        )
    return stmt


def create_customer(session: Session, **fields: Any) -> Customer:
    name = (fields.get("name") or "").strip()
    if not name:
        raise ValidationError("Customer name is required.")
    begin_write(session)
    customer = Customer(
        name=name,
        phone=(fields.get("phone") or None),
        email=(fields.get("email") or None),
        address=(fields.get("address") or None),
        notes=(fields.get("notes") or None),
    )
    session.add(customer)
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    logger.info("Created customer %s (%s)", customer.name, customer.id)
    return customer


def update_customer(session: Session, customer_id: uuid.UUID, changes: Dict[str, Any]) -> Customer:
    begin_write(session)
    customer = get_customer(session, customer_id)
    if "name" in changes and changes["name"] is not None:
        name = changes["name"].strip()
        if not name:
            raise ValidationError("Customer name is required.")
        customer.name = name
    for field in ("phone", "email", "address", "notes"):
        if field in changes:
            setattr(customer, field, changes[field] or None)
    if "is_active" in changes and changes["is_active"] is not None:
        customer.is_active = bool(changes["is_active"])
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    return customer


def archive_customer(session: Session, customer_id: uuid.UUID) -> Customer:
    """Soft-delete a customer. Their historical orders keep pointing at them."""
    begin_write(session)
    customer = get_customer(session, customer_id)
    customer.is_active = False
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    logger.info("Archived customer %s (%s)", customer.name, customer.id)
    return customer


def customer_outstanding(session: Session, customer_id: uuid.UUID) -> List[Dict[str, Any]]:
    """Quantities this customer is still owed, broken down by product."""
    pending = pending_quantity_expression()
    rows = session.execute(
        select(
            Product.id,
            Product.sku,
            Product.name,
            Product.unit_of_measure,
            func.sum(pending),
        )
        .select_from(SalesOrderItem)
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .join(Product, SalesOrderItem.product_id == Product.id)
        .where(
            SalesOrder.customer_id == customer_id,
            SalesOrder.status != OrderStatus.CANCELLED,
            pending > 0,
        )
        .group_by(Product.id, Product.sku, Product.name, Product.unit_of_measure)
        .order_by(Product.name)
    ).all()
    return [
        {
            "product_id": row[0],
            "product_sku": row[1],
            "product_name": row[2],
            "unit_of_measure": row[3],
            "pending_quantity": aggregate(row[4]),
        }
        for row in rows
    ]


def customer_orders(session: Session, customer_id: uuid.UUID) -> List[SalesOrder]:
    return list(
        session.execute(
            select(SalesOrder)
            .where(SalesOrder.customer_id == customer_id)
            .order_by(SalesOrder.created_at.desc())
            .options(joinedload(SalesOrder.items).joinedload(SalesOrderItem.product))
        )
        .unique()
        .scalars()
        .all()
    )


def has_history(session: Session, customer_id: uuid.UUID) -> bool:
    row = session.execute(
        select(SalesOrder.id).where(SalesOrder.customer_id == customer_id).limit(1)
    ).first()
    return row is not None
