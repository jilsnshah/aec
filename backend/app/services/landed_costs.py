"""Landed cost: what goods really cost to get into the godown.

The supplier's bill is the price of the goods; freight, unloading, insurance,
octroi and commission are paid on top -- often to someone else (a transporter)
and often later, when their bill arrives. A landed cost spreads those charges
over a goods receipt's lines (by quantity, value or weight) and adds them to
the cost of the units, so stock value and profit are right.

Units of the receipt still on hand get the extra cost in their FIFO layer.
Units already sold cannot be re-costed; their share is reported as charged to
cost of sales ("on goods already sold") so nothing is lost.
"""
from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..database import begin_write
from ..errors import NotFoundError, ValidationError
from ..models import (
    GoodsReceipt,
    GoodsReceiptItem,
    LandedCost,
    LandedCostCharge,
    LandedCostLine,
    MovementType,
    StockCostLayer,
    User,
)
from ..numeric import ZERO, ZERO_MONEY, money
from .common import next_document_number

KINDS = {"freight": "Freight", "unloading": "Unloading", "loading": "Loading", "insurance": "Insurance", "octroi": "Octroi / entry tax",
         "commission": "Commission", "other": "Other"}
METHODS = ("quantity", "value", "weight")
COUNTER = "landed_cost"


def _shares(items: List[GoodsReceiptItem], total: Decimal, method: str) -> Dict[uuid.UUID, Decimal]:
    if method == "weight" and any(i.product.weight_kg is None for i in items):
        method = "quantity"
    basis = {i.id: (i.total_cost if method == "value" else i.quantity * Decimal(i.product.weight_kg) if method == "weight" else i.quantity) for i in items}
    whole = sum(basis.values(), ZERO)
    if whole <= ZERO:
        basis = {i.id: i.quantity for i in items}
        whole = sum(basis.values(), ZERO)
    shares: Dict[uuid.UUID, Decimal] = {}
    given = ZERO_MONEY
    for index, item in enumerate(items):
        share = total - given if index == len(items) - 1 else money(total * basis[item.id] / whole)
        shares[item.id] = share
        given += share
    return shares


def add(session: Session, receipt_id: uuid.UUID, charges: Iterable[Dict[str, Any]], method: str = "quantity",
        note: Optional[str] = None, user: Optional[User] = None) -> Dict[str, Any]:
    """Add charges to a goods receipt and spread them into its stock cost."""
    begin_write(session)
    try:
        receipt = session.execute(
            select(GoodsReceipt).where(GoodsReceipt.id == receipt_id).options(joinedload(GoodsReceipt.items).joinedload(GoodsReceiptItem.product))
        ).unique().scalar_one_or_none()
        if receipt is None:
            raise NotFoundError("Goods receipt not found.")
        if method not in METHODS:
            raise ValidationError("Spread costs by quantity, value or weight.")
        rows = []
        for charge in charges:
            amount = money(charge.get("amount") or 0)
            if amount < ZERO:
                raise ValidationError("Charges cannot be negative.")
            if amount == ZERO:
                continue
            kind = charge.get("kind") or "freight"
            if kind not in KINDS:
                raise ValidationError("Unknown charge '{}'.".format(kind))
            transporter_id = charge.get("transporter_id")
            if transporter_id:
                from .transporters import get as get_transporter

                transporter_id = get_transporter(session, uuid.UUID(str(transporter_id))).id
            rows.append(LandedCostCharge(kind=kind, amount=amount, transporter_id=transporter_id,
                                         paid_to=(charge.get("paid_to") or "").strip() or None, bill_number=(charge.get("bill_number") or "").strip() or None))
        if not rows:
            raise ValidationError("Enter at least one charge.")
        items = [i for i in receipt.items if i.quantity > ZERO]
        if not items:
            raise ValidationError("Nothing was received on {}.".format(receipt.receipt_number))
        total = sum((r.amount for r in rows), ZERO_MONEY)
        landed = LandedCost(number=next_document_number(session, COUNTER, "LC"), goods_receipt_id=receipt.id, method=method, total=total,
                            note=(note or "").strip() or None, created_by_id=user.id if user else None)
        landed.charges = rows
        session.add(landed)
        shares = _shares(items, total, method)
        on_stock_total = ZERO_MONEY
        for item in items:
            share = shares[item.id]
            per_unit = (share / item.quantity).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            layers = session.execute(
                select(StockCostLayer).where(StockCostLayer.source == MovementType.GOODS_RECEIPT, StockCostLayer.source_id == item.id).with_for_update()
            ).scalars().all()
            on_stock = ZERO_MONEY
            for layer in layers:
                layer.unit_cost = layer.unit_cost + per_unit
                on_stock += money(layer.quantity_remaining * per_unit)
            on_stock = min(on_stock, share)
            landed.lines.append(LandedCostLine(goods_receipt_item_id=item.id, product_id=item.product_id, quantity=item.quantity, amount=share,
                                               per_unit=per_unit, on_stock=on_stock, on_sold=share - on_stock))
            on_stock_total += on_stock
        landed.on_stock = on_stock_total
        landed.on_sold = total - on_stock_total
        from .controls import log

        log(session, user, "landed_cost", "goods_receipt", str(receipt.id),
            "{} on {}: Rs {:,.2f} ({}) spread by {}".format(landed.number, receipt.receipt_number, float(total),
                                                       ", ".join(KINDS[r.kind] for r in rows), method))
        session.commit()
    except Exception:
        session.rollback()
        raise
    return view(session, landed.id)


def view(session: Session, landed_id: uuid.UUID) -> Dict[str, Any]:
    landed = session.execute(
        select(LandedCost).where(LandedCost.id == landed_id).options(joinedload(LandedCost.charges), joinedload(LandedCost.lines).joinedload(LandedCostLine.product))
    ).unique().scalar_one_or_none()
    if landed is None:
        raise NotFoundError("Landed cost not found.")
    receipt = session.get(GoodsReceipt, landed.goods_receipt_id)
    from ..models import Transporter

    return {
        "id": landed.id, "number": landed.number, "goods_receipt_id": landed.goods_receipt_id, "receipt_number": receipt.receipt_number if receipt else None,
        "method": landed.method, "total": float(landed.total), "on_stock": float(landed.on_stock), "on_sold": float(landed.on_sold),
        "note": landed.note, "created_at": landed.created_at,
        "charges": [{"id": c.id, "kind": c.kind, "label": KINDS.get(c.kind, c.kind), "amount": float(c.amount), "transporter_id": c.transporter_id,
                     "transporter": (session.get(Transporter, c.transporter_id).name if c.transporter_id else None), "paid_to": c.paid_to,
                     "bill_number": c.bill_number} for c in landed.charges],
        "lines": [{"product_id": l.product_id, "product": l.product.name, "unit": l.product.unit_of_measure, "quantity": float(l.quantity),
                   "amount": float(l.amount), "per_unit": float(l.per_unit), "on_stock": float(l.on_stock), "on_sold": float(l.on_sold)} for l in landed.lines],
    }


def for_receipt(session: Session, receipt_id: uuid.UUID) -> List[Dict[str, Any]]:
    ids = session.execute(select(LandedCost.id).where(LandedCost.goods_receipt_id == receipt_id).order_by(LandedCost.created_at)).scalars().all()
    return [view(session, i) for i in ids]


def list_all(session: Session, limit: int = 100) -> List[Dict[str, Any]]:
    ids = session.execute(select(LandedCost.id).order_by(LandedCost.created_at.desc()).limit(limit)).scalars().all()
    return [view(session, i) for i in ids]
