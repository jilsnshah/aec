"""Sales returns (credit notes).

A customer sends back delivered goods. The return's value is credited to their
account -- it settles their oldest open invoices first, exactly like a payment
-- and revenue for the period falls by it. Lines in sellable condition go back
on the shelf: physical stock rises and a cost layer reopens at the average cost
those units were delivered at, so profit is reversed exactly. Damaged lines are
credited but not restocked; their cost stays as a loss. Stock coming back is
reserved for any customer already waiting, oldest order first.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..database import begin_write
from ..errors import NotFoundError, ValidationError
from ..models import (
    AllocationSource,
    MovementType,
    SalesOrder,
    SalesOrderItem,
    SalesReturn,
    SalesReturnItem,
    StockAllocation,
    StockCostLayer,
)
from ..numeric import ZERO, ZERO_MONEY, money, quantity as to_quantity, unit_cost
from . import reservations
from .common import lock_product, next_document_number, record_movement

REASONS = {
    "damaged": "Damaged in transit",
    "wrong_item": "Wrong item sent",
    "quality": "Quality complaint",
    "excess": "Ordered too much",
    "other": "Other",
}
RETURN_COUNTER = "sales_return"


def returned_map(session: Session, order_item_ids: Iterable[uuid.UUID]) -> Dict[uuid.UUID, Decimal]:
    ids = list(order_item_ids)
    if not ids:
        return {}
    return {
        item_id: total
        for item_id, total in session.execute(
            select(SalesReturnItem.order_item_id, func.sum(SalesReturnItem.quantity)).where(SalesReturnItem.order_item_id.in_(ids)).group_by(SalesReturnItem.order_item_id)
        ).all()
    }


def _delivered_unit_cost(session: Session, line: SalesOrderItem) -> Decimal:
    qty, cost = session.execute(
        select(func.coalesce(func.sum(StockAllocation.quantity), 0), func.coalesce(func.sum(StockAllocation.cost_amount), 0))
        .where(StockAllocation.order_item_id == line.id, StockAllocation.customer_delivery_item_id.is_not(None))
    ).one()
    if qty and Decimal(qty) > ZERO:
        return unit_cost(Decimal(cost) / Decimal(qty))
    return line.product.last_purchase_price or Decimal("0.0000")


def create_return(
    session: Session,
    order_id: uuid.UUID,
    lines: Iterable[Dict[str, Any]],
    reason: str,
    note: Optional[str] = None,
    user_id: Optional[uuid.UUID] = None,
    warehouse_id: Optional[uuid.UUID] = None,
) -> SalesReturn:
    begin_write(session)
    try:
        if reason not in REASONS:
            raise ValidationError("Choose a reason for the return.")
        order = session.execute(
            select(SalesOrder).where(SalesOrder.id == order_id).options(joinedload(SalesOrder.items).joinedload(SalesOrderItem.product))
        ).unique().scalar_one_or_none()
        if order is None:
            raise NotFoundError("Order not found.")
        by_id = {item.id: item for item in order.items}
        wanted: List[Dict[str, Any]] = []
        for line in lines:
            try:
                item_id = uuid.UUID(str(line.get("order_item_id")))
            except (TypeError, ValueError):
                raise ValidationError("Each returned line must name an order line.")
            if item_id not in by_id:
                raise ValidationError("That line is not on order {}.".format(order.order_number))
            qty = to_quantity(line.get("quantity"), "Returned quantity")
            if qty <= ZERO:
                continue
            wanted.append({"item": by_id[item_id], "quantity": qty, "restock": bool(line.get("restock", True))})
        if not wanted:
            raise ValidationError("Enter a quantity to return on at least one line.")
        already = returned_map(session, [w["item"].id for w in wanted])
        for w in wanted:
            item = w["item"]
            can = item.quantity_fulfilled - already.get(item.id, ZERO)
            if w["quantity"] > can:
                raise ValidationError("Only {} of {} was delivered and not yet returned.".format(format(can.normalize(), "f"), item.product.name))

        record = SalesReturn(
            number=next_document_number(session, RETURN_COUNTER, "CRN"),
            sales_order_id=order.id,
            customer_id=order.customer_id,
            reason=reason,
            note=(note or "").strip() or None,
            amount=ZERO_MONEY,
            created_by_id=user_id,
        )
        from . import warehouses as warehouse_service

        into = warehouse_service.resolve(session, warehouse_id)
        record.warehouse_id = into
        session.add(record)
        session.flush()
        total = ZERO_MONEY
        restocked = ZERO_MONEY
        for w in sorted(wanted, key=lambda w: str(w["item"].product_id)):
            item: SalesOrderItem = w["item"]
            qty = w["quantity"]
            cost = _delivered_unit_cost(session, item)
            amount = money(qty * item.unit_price_net)
            session.add(SalesReturnItem(sales_return_id=record.id, order_item_id=item.id, product_id=item.product_id, quantity=qty,
                                        unit_price_net=item.unit_price_net, amount=amount, restock=w["restock"], unit_cost=cost))
            total = total + amount
            if w["restock"]:
                product = lock_product(session, item.product_id)
                label = "Returned by customer ({}, {})".format(record.number, order.order_number)
                session.add(StockCostLayer(product_id=product.id, source=MovementType.SALES_RETURN, source_id=record.id,
                                           unit_cost=cost, quantity=qty, quantity_remaining=qty, note=label, warehouse_id=into))
                record_movement(session, product, MovementType.SALES_RETURN, qty, "sales_return", record.id, label, warehouse_id=into)
                restocked = restocked + money(qty * cost)
                waiting = reservations.unallocated_total(reservations.fifo_unallocated_items(session, product.id))
                if waiting > ZERO:
                    reservations.allocate_available_stock(session, product, min(qty, waiting), AllocationSource.ADJUSTMENT, label="return")
        record.amount = total
        record.restocked_cost = restocked
        from ..models import User
        from .controls import log

        log(session, session.get(User, user_id) if user_id else None, "sales_return", "order", str(order.id),
            "{} on {}: credited {:,.2f} ({})".format(record.number, order.order_number, total, REASONS[reason]), {"return_id": str(record.id)})
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_return(session, record.id)


def get_return(session: Session, return_id: uuid.UUID) -> SalesReturn:
    record = session.execute(
        select(SalesReturn).where(SalesReturn.id == return_id).options(joinedload(SalesReturn.items).joinedload(SalesReturnItem.product), joinedload(SalesReturn.sales_order), joinedload(SalesReturn.customer))
    ).unique().scalar_one_or_none()
    if record is None:
        raise NotFoundError("Return not found.")
    return record


def view(record: SalesReturn) -> Dict[str, Any]:
    return {
        "id": record.id,
        "number": record.number,
        "sales_order_id": record.sales_order_id,
        "order_number": record.sales_order.order_number if record.sales_order else None,
        "customer_id": record.customer_id,
        "customer_name": record.customer.name if record.customer else None,
        "reason": record.reason,
        "reason_label": REASONS.get(record.reason, record.reason),
        "note": record.note,
        "amount": float(record.amount),
        "restocked_cost": float(record.restocked_cost),
        "created_at": record.created_at,
        "lines": [
            {"order_item_id": line.order_item_id, "product_id": line.product_id, "product_name": line.product.name if line.product else None,
             "unit": line.product.unit_of_measure if line.product else None, "quantity": float(line.quantity),
             "unit_price_net": float(line.unit_price_net), "amount": float(line.amount), "restock": line.restock, "unit_cost": float(line.unit_cost)}
            for line in record.items
        ],
    }


def list_returns(session: Session, customer_id=None, order_id=None, limit: int = 100) -> Dict[str, Any]:
    stmt = select(SalesReturn).options(joinedload(SalesReturn.items).joinedload(SalesReturnItem.product), joinedload(SalesReturn.sales_order), joinedload(SalesReturn.customer)).order_by(SalesReturn.created_at.desc())
    if customer_id:
        stmt = stmt.where(SalesReturn.customer_id == customer_id)
    if order_id:
        stmt = stmt.where(SalesReturn.sales_order_id == order_id)
    rows = session.execute(stmt.limit(limit)).unique().scalars().all()
    by_reason = session.execute(select(SalesReturn.reason, func.count(SalesReturn.id), func.sum(SalesReturn.amount)).group_by(SalesReturn.reason)).all()
    return {
        "items": [view(r) for r in rows],
        "by_reason": [{"reason": r, "label": REASONS.get(r, r), "count": c, "amount": float(a or 0)} for r, c, a in by_reason],
    }


def returnable(session: Session, order_id: uuid.UUID) -> List[Dict[str, Any]]:
    """Each order line with what was delivered and can still be returned."""
    order = session.execute(
        select(SalesOrder).where(SalesOrder.id == order_id).options(joinedload(SalesOrder.items).joinedload(SalesOrderItem.product))
    ).unique().scalar_one_or_none()
    if order is None:
        raise NotFoundError("Order not found.")
    already = returned_map(session, [item.id for item in order.items])
    return [
        {"order_item_id": item.id, "product_id": item.product_id, "product_name": item.product.name, "unit": item.product.unit_of_measure,
         "delivered": float(item.quantity_fulfilled), "returned": float(already.get(item.id, ZERO)),
         "returnable": float(item.quantity_fulfilled - already.get(item.id, ZERO)), "unit_price_net": float(item.unit_price_net)}
        for item in sorted(order.items, key=lambda i: i.line_number)
    ]


def credits_by_customer(session: Session) -> Dict[uuid.UUID, Decimal]:
    return {cid: money(total or 0) for cid, total in session.execute(select(SalesReturn.customer_id, func.sum(SalesReturn.amount)).group_by(SalesReturn.customer_id)).all()}


def totals_between(session: Session, start, end) -> Dict[str, float]:
    """Credited value and restocked cost of returns made in a period."""
    amount, restocked, count = session.execute(
        select(func.coalesce(func.sum(SalesReturn.amount), 0), func.coalesce(func.sum(SalesReturn.restocked_cost), 0), func.count(SalesReturn.id))
        .where(SalesReturn.created_at >= start, SalesReturn.created_at < end)
    ).one()
    return {"amount": float(amount), "restocked_cost": float(restocked), "count": count}

