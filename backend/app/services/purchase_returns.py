"""Purchase returns: goods sent back to the supplier.

Damaged bags, short-dated stock, the wrong grade, excess supplied. A return
is made against a goods receipt (or a purchase order), line by line:

* the goods leave stock -- from the receipt's own cost layers first, so the
  units going back are valued at what they came in at;
* a **debit note** is raised for what the supplier billed for them, which
  reduces what we owe that supplier (and goes to Tally as a Debit Note);
* with **replace**, the supplier is to send the goods again: the purchase
  order is owed that quantity once more.

If stock set aside for customers goes back, the newest orders lose their
reservation first (they become short again), like any loss of stock.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..database import begin_write
from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import (
    GoodsReceipt,
    GoodsReceiptItem,
    MovementType,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReturn,
    PurchaseReturnItem,
    StockCostLayer,
    Supplier,
    User,
)
from ..numeric import ZERO, ZERO_MONEY, money, quantity as to_quantity
from .common import lock_product, next_document_number, record_movement

REASONS = {"damaged": "Damaged", "quality": "Quality not as agreed", "wrong_item": "Wrong item or grade", "excess": "Excess supplied",
           "expired": "Expired or short-dated", "other": "Other"}
COUNTER = "purchase_return"


def returned_by_receipt_item(session: Session, item_ids: Iterable[uuid.UUID]) -> Dict[uuid.UUID, Decimal]:
    ids = list(item_ids)
    if not ids:
        return {}
    rows = session.execute(select(PurchaseReturnItem.goods_receipt_item_id, func.sum(PurchaseReturnItem.quantity))
                           .where(PurchaseReturnItem.goods_receipt_item_id.in_(ids)).group_by(PurchaseReturnItem.goods_receipt_item_id)).all()
    return {i: Decimal(q or 0) for i, q in rows}


def returnable(session: Session, receipt_id: uuid.UUID) -> Dict[str, Any]:
    """A receipt's lines: received, already returned and still returnable."""
    receipt = session.execute(select(GoodsReceipt).where(GoodsReceipt.id == receipt_id).options(
        joinedload(GoodsReceipt.items).joinedload(GoodsReceiptItem.product))).unique().scalar_one_or_none()
    if receipt is None:
        raise NotFoundError("Goods receipt not found.")
    done = returned_by_receipt_item(session, [i.id for i in receipt.items])
    return {"goods_receipt_id": receipt.id, "receipt_number": receipt.receipt_number, "supplier_id": receipt.supplier_id,
            "purchase_order_id": receipt.purchase_order_id, "warehouse_id": receipt.warehouse_id,
            "lines": [{"goods_receipt_item_id": i.id, "product_id": i.product_id, "product": i.product.name, "unit": i.product.unit_of_measure,
                       "received": float(i.quantity), "returned": float(done.get(i.id, ZERO)),
                       "returnable": float(max(ZERO, i.quantity - done.get(i.id, ZERO))), "unit_cost": float(i.unit_cost)}
                      for i in receipt.items if i.quantity > 0]}


def _draw(session: Session, product, amount: Decimal, warehouse_id: Optional[uuid.UUID], prefer_source: Optional[uuid.UUID]) -> Decimal:
    """Take ``amount`` out of stock, from the receipt's own layers first; return its value."""
    from .warehouses import transit_id

    transit = transit_id(session)
    value = ZERO_MONEY
    remaining = amount
    stmts = []
    base = select(StockCostLayer).where(StockCostLayer.product_id == product.id, StockCostLayer.quantity_remaining > 0,
                                        (StockCostLayer.warehouse_id.is_(None)) | (StockCostLayer.warehouse_id != transit))
    if warehouse_id:
        base = base.where(StockCostLayer.warehouse_id == warehouse_id)
    if prefer_source:
        stmts.append(base.where(StockCostLayer.source_id == prefer_source))
    stmts.append(base)
    for stmt in stmts:
        for layer in session.execute(stmt.order_by(StockCostLayer.created_at, StockCostLayer.id).with_for_update()).scalars():
            if remaining <= ZERO:
                break
            take = min(layer.quantity_remaining, remaining)
            if take <= ZERO:
                continue
            layer.quantity_remaining -= take
            value += money(take * layer.unit_cost)
            remaining -= take
    if remaining > ZERO:
        raise ValidationError("Only {} {} of {} is in stock there to send back.".format(amount - remaining, product.unit_of_measure, product.name))
    return value


def create(session: Session, lines: Iterable[Dict[str, Any]], reason: str, goods_receipt_id: Optional[uuid.UUID] = None,
           purchase_order_id: Optional[uuid.UUID] = None, supplier_id: Optional[uuid.UUID] = None, note: Optional[str] = None,
           replace: bool = False, warehouse_id: Optional[uuid.UUID] = None, transport: Optional[Dict[str, Any]] = None,
           user: Optional[User] = None) -> Dict[str, Any]:
    from . import reservations, warehouses
    from .adjustments import _release_newest
    from .purchasing import _recompute_po_status

    if reason not in REASONS:
        raise ValidationError("Reason must be one of: {}.".format(", ".join(REASONS)))
    begin_write(session)
    try:
        receipt = None
        if goods_receipt_id:
            receipt = session.execute(select(GoodsReceipt).where(GoodsReceipt.id == goods_receipt_id).options(
                joinedload(GoodsReceipt.items))).unique().scalar_one_or_none()
            if receipt is None:
                raise NotFoundError("Goods receipt not found.")
            supplier_id, purchase_order_id = receipt.supplier_id, receipt.purchase_order_id
        if purchase_order_id and not supplier_id:
            po = session.get(PurchaseOrder, purchase_order_id)
            if po is None:
                raise NotFoundError("Purchase order not found.")
            supplier_id = po.supplier_id
        if not supplier_id or session.get(Supplier, supplier_id) is None:
            raise ValidationError("Choose the goods receipt, purchase order or supplier the goods go back to.")
        source = warehouses.resolve(session, warehouse_id or (receipt.warehouse_id if receipt else None))
        transport = transport or {}
        record = PurchaseReturn(number=next_document_number(session, COUNTER, "PRN"), supplier_id=supplier_id, purchase_order_id=purchase_order_id,
                                goods_receipt_id=receipt.id if receipt else None, warehouse_id=source, reason=reason,
                                note=(note or "").strip() or None, replace=bool(replace), created_by_id=user.id if user else None,
                                transporter_id=transport.get("transporter_id"), vehicle_number=(transport.get("vehicle_number") or "").strip().upper() or None)
        session.add(record)
        session.flush()
        done = returned_by_receipt_item(session, [i.id for i in receipt.items]) if receipt else {}
        by_item = {i.id: i for i in receipt.items} if receipt else {}
        total = ZERO_MONEY
        stock_value = ZERO_MONEY
        any_line = False
        label = "Returned to supplier ({}): {}".format(record.number, REASONS[reason])
        for index, line in enumerate(lines, start=1):
            qty = to_quantity(line.get("quantity"), "Line {} quantity".format(index))
            if qty <= ZERO:
                continue
            item = None
            if line.get("goods_receipt_item_id"):
                item = by_item.get(uuid.UUID(str(line["goods_receipt_item_id"])))
                if item is None:
                    raise NotFoundError("Line {} is not on that receipt.".format(index))
                left = item.quantity - done.get(item.id, ZERO)
                if qty > left:
                    raise ValidationError("Only {} of line {} can still go back.".format(left, index), {"max_allowed": str(left)})
                product_id, unit_cost = item.product_id, item.unit_cost
                po_item = session.get(PurchaseOrderItem, item.purchase_order_item_id)
            else:
                product_id = uuid.UUID(str(line.get("product_id")))
                po_item = None
                if purchase_order_id:
                    po_item = session.execute(select(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id == purchase_order_id,
                                                                              PurchaseOrderItem.product_id == product_id)).scalar_one_or_none()
                cost = line.get("unit_cost")
                unit_cost = Decimal(str(cost)) if cost not in (None, "") else (po_item.unit_cost if po_item else ZERO)
            product = lock_product(session, product_id)
            on_hand_here = warehouses.on_hand(session, product.id, source)
            if qty > on_hand_here:
                raise ValidationError("Only {} {} of {} is in {} to send back.".format(on_hand_here, product.unit_of_measure, product.name,
                                                                                      "that warehouse"))
            reserved = reservations.reserved_for_product(session, product.id)
            free = product.physical_stock - reserved
            if qty > free:
                _release_newest(session, product, qty - max(free, ZERO))
            value = _draw(session, product, qty, source, item.id if item else None)
            record_movement(session, product, MovementType.PURCHASE_RETURN, -qty, "purchase_return", record.id, label, warehouse_id=source)
            amount = money(qty * unit_cost)
            record.items.append(PurchaseReturnItem(product_id=product.id, goods_receipt_item_id=item.id if item else None,
                                                   purchase_order_item_id=po_item.id if po_item else None, quantity=qty,
                                                   unit_cost=unit_cost, amount=amount, stock_value=value))
            total += amount
            stock_value += value
            any_line = True
            if replace and po_item is not None:
                # The supplier owes these again.
                po_item.quantity_received = max(ZERO, po_item.quantity_received - qty)
        if not any_line:
            raise ValidationError("Enter a quantity to send back.")
        record.amount, record.stock_value = total, stock_value
        if replace and purchase_order_id:
            order = session.get(PurchaseOrder, purchase_order_id)
            session.flush()
            session.expire(order)
            _recompute_po_status(order)
        from .controls import log

        log(session, user, "purchase_return", "supplier", str(supplier_id),
            "{}: Rs {:,.2f} back to {} ({}){}".format(record.number, float(total), session.get(Supplier, supplier_id).name, REASONS[reason],
                                                     "; to be replaced" if replace else ""))
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get(session, record.id)


def view(record: PurchaseReturn) -> Dict[str, Any]:
    return {"id": record.id, "number": record.number, "supplier_id": record.supplier_id, "supplier": record.supplier.name,
            "purchase_order_id": record.purchase_order_id, "goods_receipt_id": record.goods_receipt_id, "warehouse_id": record.warehouse_id,
            "reason": record.reason, "reason_label": REASONS.get(record.reason, record.reason), "note": record.note, "replace": record.replace,
            "amount": float(record.amount), "stock_value": float(record.stock_value), "transporter_id": record.transporter_id,
            "vehicle_number": record.vehicle_number, "created_at": record.created_at,
            "items": [{"product_id": i.product_id, "product": i.product.name, "unit": i.product.unit_of_measure, "quantity": float(i.quantity),
                       "unit_cost": float(i.unit_cost), "amount": float(i.amount), "stock_value": float(i.stock_value)} for i in record.items]}


def get(session: Session, return_id: uuid.UUID) -> Dict[str, Any]:
    record = session.execute(select(PurchaseReturn).where(PurchaseReturn.id == return_id).options(
        joinedload(PurchaseReturn.items).joinedload(PurchaseReturnItem.product), joinedload(PurchaseReturn.supplier))).unique().scalar_one_or_none()
    if record is None:
        raise NotFoundError("Purchase return not found.")
    return view(record)


def list_returns(session: Session, supplier_id: Optional[uuid.UUID] = None, purchase_order_id: Optional[uuid.UUID] = None, limit: int = 100) -> List[Dict[str, Any]]:
    stmt = select(PurchaseReturn).options(joinedload(PurchaseReturn.items).joinedload(PurchaseReturnItem.product), joinedload(PurchaseReturn.supplier)
                                          ).order_by(PurchaseReturn.created_at.desc())
    if supplier_id:
        stmt = stmt.where(PurchaseReturn.supplier_id == supplier_id)
    if purchase_order_id:
        stmt = stmt.where(PurchaseReturn.purchase_order_id == purchase_order_id)
    return [view(r) for r in session.execute(stmt.limit(limit)).unique().scalars()]
