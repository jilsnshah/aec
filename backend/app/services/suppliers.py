"""Supplier master."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..database import begin_write
from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import (
    GoodsReceipt,
    GoodsReceiptItem,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    Supplier,
)
from ..numeric import ZERO, ZERO_MONEY, money, quantity
from .common import count_matching, next_document_number, windowed

logger = logging.getLogger(__name__)

SUPPLIER_COUNTER = "supplier"

SORTABLE_FIELDS = {
    "code": Supplier.code,
    "name": Supplier.name,
    "created_at": Supplier.created_at,
    "updated_at": Supplier.updated_at,
}


def get_supplier(session: Session, supplier_id: uuid.UUID) -> Supplier:
    supplier = session.get(Supplier, supplier_id)
    if supplier is None:
        raise NotFoundError("Supplier {} does not exist.".format(supplier_id))
    return supplier


def _normalise_code(code: str) -> str:
    cleaned = (code or "").strip().upper()
    if not cleaned:
        raise ValidationError("Supplier code is required.")
    return cleaned


def count_suppliers(
    session: Session, search: Optional[str] = None, include_inactive: bool = False
) -> int:
    return count_matching(session, _supplier_filter(search, include_inactive))


def list_suppliers(
    session: Session,
    search: Optional[str] = None,
    include_inactive: bool = False,
    sort_by: str = "name",
    sort_dir: str = "asc",
    limit: Optional[int] = None,
    offset: int = 0,
) -> List[Supplier]:
    stmt = _supplier_filter(search, include_inactive)
    column = SORTABLE_FIELDS.get(sort_by, Supplier.name)
    stmt = stmt.order_by(column.desc() if sort_dir == "desc" else column.asc(), Supplier.id)
    return list(session.execute(windowed(stmt, limit, offset)).scalars().all())


def supplier_stats(session: Session, supplier_ids: List[uuid.UUID]) -> Dict[uuid.UUID, Dict[str, Any]]:
    """Purchasing summary per supplier, for listings."""
    if not supplier_ids:
        return {}
    live = PurchaseOrder.status != PurchaseOrderStatus.CANCELLED
    open_statuses = [PurchaseOrderStatus.ORDERED, PurchaseOrderStatus.PARTIALLY_RECEIVED]
    stats: Dict[uuid.UUID, Dict[str, Any]] = {
        supplier_id: {
            "po_count": 0,
            "open_po_count": 0,
            "on_order_quantity": ZERO,
            "on_order_value": ZERO_MONEY,
            "last_po_at": None,
        }
        for supplier_id in supplier_ids
    }
    for supplier_id, count, open_count, last_at in session.execute(
        select(
            PurchaseOrder.supplier_id,
            func.count(PurchaseOrder.id).filter(live),
            func.count(PurchaseOrder.id).filter(PurchaseOrder.status.in_(open_statuses)),
            func.max(PurchaseOrder.created_at),
        )
        .where(PurchaseOrder.supplier_id.in_(supplier_ids))
        .group_by(PurchaseOrder.supplier_id)
    ).all():
        stats[supplier_id].update(po_count=count, open_po_count=open_count, last_po_at=last_at)
    still_due = PurchaseOrderItem.quantity_ordered - PurchaseOrderItem.quantity_received
    for supplier_id, due, due_value in session.execute(
        select(
            PurchaseOrder.supplier_id,
            func.sum(still_due),
            func.sum(still_due * PurchaseOrderItem.unit_cost),
        )
        .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .where(
            PurchaseOrder.supplier_id.in_(supplier_ids),
            PurchaseOrder.status.in_(open_statuses),
            still_due > 0,
        )
        .group_by(PurchaseOrder.supplier_id)
    ).all():
        stats[supplier_id].update(
            on_order_quantity=quantity(due or 0), on_order_value=money(due_value or 0)
        )
    return stats


def _supplier_filter(search: Optional[str], include_inactive: bool):
    stmt = select(Supplier)
    if not include_inactive:
        stmt = stmt.where(Supplier.is_active.is_(True))
    if search:
        pattern = "%{}%".format(search.strip().lower())
        stmt = stmt.where(
            or_(
                func.lower(Supplier.code).like(pattern),
                func.lower(Supplier.name).like(pattern),
                func.lower(func.coalesce(Supplier.contact_person, "")).like(pattern),
                func.lower(func.coalesce(Supplier.phone, "")).like(pattern),
                func.lower(func.coalesce(Supplier.email, "")).like(pattern),
            )
        )
    return stmt


def create_supplier(session: Session, **fields: Any) -> Supplier:
    name = (fields.get("name") or "").strip()
    if not name:
        raise ValidationError("Supplier name is required.")

    try:
        begin_write(session)
        raw_code = fields.get("code")
        if raw_code:
            code = _normalise_code(raw_code)
            clash = session.execute(select(Supplier.id).where(Supplier.code == code)).first()
            if clash is not None:
                raise ConflictError("A supplier with code '{}' already exists.".format(code))
        else:
            # The backend generates one when the user does not supply it.
            code = next_document_number(session, SUPPLIER_COUNTER, "SUP")

        supplier = Supplier(
            code=code,
            name=name,
            contact_person=(fields.get("contact_person") or None),
            phone=(fields.get("phone") or None),
            email=(fields.get("email") or None),
            address=(fields.get("address") or None),
            notes=(fields.get("notes") or None),
        )
        session.add(supplier)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("That supplier code is already in use.") from exc
    except Exception:
        session.rollback()
        raise

    logger.info("Created supplier %s (%s)", supplier.code, supplier.id)
    return supplier


def update_supplier(session: Session, supplier_id: uuid.UUID, changes: Dict[str, Any]) -> Supplier:
    try:
        begin_write(session)
        supplier = get_supplier(session, supplier_id)

        if "code" in changes and changes["code"] is not None:
            code = _normalise_code(changes["code"])
            if code != supplier.code:
                clash = session.execute(
                    select(Supplier.id).where(Supplier.code == code, Supplier.id != supplier.id)
                ).first()
                if clash is not None:
                    raise ConflictError("A supplier with code '{}' already exists.".format(code))
                supplier.code = code

        if "name" in changes and changes["name"] is not None:
            name = changes["name"].strip()
            if not name:
                raise ValidationError("Supplier name is required.")
            supplier.name = name

        for field in ("contact_person", "phone", "email", "address", "notes"):
            if field in changes:
                setattr(supplier, field, changes[field] or None)

        if "is_active" in changes and changes["is_active"] is not None:
            supplier.is_active = bool(changes["is_active"])

        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("That supplier code is already in use.") from exc
    except Exception:
        session.rollback()
        raise
    return supplier


def archive_supplier(session: Session, supplier_id: uuid.UUID) -> Supplier:
    """Soft-delete a supplier. Purchase orders and receipts keep pointing at it."""
    try:
        begin_write(session)
        supplier = get_supplier(session, supplier_id)
        supplier.is_active = False
        session.commit()
    except Exception:
        session.rollback()
        raise
    logger.info("Archived supplier %s (%s)", supplier.code, supplier.id)
    return supplier


def supplier_detail(session: Session, supplier_id: uuid.UUID) -> Dict[str, Any]:
    """A supplier with its purchasing and receipt history."""
    supplier = get_supplier(session, supplier_id)

    orders = list(
        session.execute(
            select(PurchaseOrder)
            .where(PurchaseOrder.supplier_id == supplier.id)
            .order_by(PurchaseOrder.created_at.desc())
            .options(joinedload(PurchaseOrder.items).joinedload(PurchaseOrderItem.product))
        )
        .unique()
        .scalars()
        .all()
    )
    receipts = list(
        session.execute(
            select(GoodsReceipt)
            .where(GoodsReceipt.supplier_id == supplier.id)
            .order_by(GoodsReceipt.created_at.desc())
            .options(
                joinedload(GoodsReceipt.items).joinedload(GoodsReceiptItem.product),
                joinedload(GoodsReceipt.purchase_order),
            )
        )
        .unique()
        .scalars()
        .all()
    )

    return {
        "id": supplier.id,
        "code": supplier.code,
        "name": supplier.name,
        "contact_person": supplier.contact_person,
        "phone": supplier.phone,
        "email": supplier.email,
        "address": supplier.address,
        "notes": supplier.notes,
        "is_active": supplier.is_active,
        "created_at": supplier.created_at,
        "updated_at": supplier.updated_at,
        "purchase_orders": [
            {
                "id": order.id,
                "po_number": order.po_number,
                "status": order.status,
                "created_at": order.created_at,
                "expected_delivery_date": order.expected_delivery_date,
                "line_count": len(order.items),
                "total_ordered": sum((item.quantity_ordered for item in order.items), ZERO),
                "total_received": sum((item.quantity_received for item in order.items), ZERO),
                "total_cost": money(
                    sum(
                        (item.unit_cost * item.quantity_ordered for item in order.items),
                        ZERO_MONEY,
                    )
                ),
            }
            for order in orders
        ],
        "goods_receipts": [
            {
                "id": receipt.id,
                "receipt_number": receipt.receipt_number,
                "created_at": receipt.created_at,
                "purchase_order_id": receipt.purchase_order_id,
                "po_number": receipt.purchase_order.po_number,
                "delivery_note_reference": receipt.delivery_note_reference,
                "line_count": len(receipt.items),
                "total_quantity": sum((line.quantity for line in receipt.items), ZERO),
                "total_cost": money(
                    sum((line.total_cost for line in receipt.items), ZERO_MONEY)
                ),
            }
            for receipt in receipts
        ],
    }


def has_history(session: Session, supplier_id: uuid.UUID) -> bool:
    row = session.execute(
        select(PurchaseOrder.id).where(PurchaseOrder.supplier_id == supplier_id).limit(1)
    ).first()
    return row is not None
