"""Batches (lots) and expiry.

A product that tracks batches gets a batch number -- and a manufacture and
expiry date -- on every receipt. The units carry the batch in their FIFO cost
layer, through transfers to other warehouses, and are picked earliest expiry
first (FEFO) for deliveries, adjustments, transfers and returns. Batches near
or past expiry are listed so they can be sold first or written off.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import ValidationError
from ..models import Batch, Product, StockCostLayer, Warehouse


def _day(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ValidationError("Dates are YYYY-MM-DD.")


def resolve(session: Session, product: Product, number: Optional[str], manufactured_on: Any = None, expires_on: Any = None,
            supplier_id: Optional[uuid.UUID] = None) -> Optional[Batch]:
    """The batch for a receipt line: found by number or created. Required
    when the product tracks batches; ignored when it does not."""
    number = (number or "").strip()
    if not product.track_batches:
        return None
    if not number:
        raise ValidationError("{} needs a batch number.".format(product.name))
    made, expires = _day(manufactured_on), _day(expires_on)
    if expires is None and made is not None and product.shelf_life_days:
        expires = made + timedelta(days=int(product.shelf_life_days))
    if made and expires and expires < made:
        raise ValidationError("Batch {} expires before it was made.".format(number))
    batch = session.execute(select(Batch).where(Batch.product_id == product.id, func.lower(Batch.number) == number.lower())).scalar_one_or_none()
    if batch is None:
        batch = Batch(product_id=product.id, number=number[:64], manufactured_on=made, expires_on=expires, supplier_id=supplier_id)
        session.add(batch)
        session.flush()
    else:
        batch.manufactured_on = batch.manufactured_on or made
        batch.expires_on = batch.expires_on or expires
    return batch


def fefo(stmt, product_id: uuid.UUID, session: Session):
    """Order layers earliest expiry first for products that track batches
    (oldest first otherwise, and within a batch)."""
    product = session.get(Product, product_id)
    if product is not None and product.track_batches:
        stmt = stmt.outerjoin(Batch, StockCostLayer.batch_id == Batch.id).order_by(Batch.expires_on.asc().nulls_last())
    return stmt.order_by(StockCostLayer.created_at.asc(), StockCostLayer.id.asc())


def stock(session: Session, product_id: Optional[uuid.UUID] = None, expiring_within_days: Optional[int] = None) -> List[Dict[str, Any]]:
    """Quantity on hand per batch and warehouse, soonest expiry first."""
    stmt = (select(Batch, StockCostLayer.warehouse_id, func.sum(StockCostLayer.quantity_remaining), func.sum(StockCostLayer.quantity_remaining * StockCostLayer.unit_cost))
            .join(StockCostLayer, StockCostLayer.batch_id == Batch.id).where(StockCostLayer.quantity_remaining > 0)
            .group_by(Batch.id, StockCostLayer.warehouse_id).order_by(Batch.expires_on.asc().nulls_last(), Batch.number))
    if product_id:
        stmt = stmt.where(Batch.product_id == product_id)
    today = date.today()
    if expiring_within_days is not None:
        stmt = stmt.where(Batch.expires_on.is_not(None), Batch.expires_on <= today + timedelta(days=int(expiring_within_days)))
    houses = {w.id: w.name for w in session.execute(select(Warehouse)).scalars()}
    out = []
    for batch, warehouse_id, qty, value in session.execute(stmt).all():
        days = (batch.expires_on - today).days if batch.expires_on else None
        out.append({"batch_id": batch.id, "number": batch.number, "product_id": batch.product_id, "product": batch.product.name,
                    "unit": batch.product.unit_of_measure, "manufactured_on": batch.manufactured_on, "expires_on": batch.expires_on,
                    "days_left": days, "state": "expired" if days is not None and days < 0 else "expiring" if days is not None and days <= 30 else "ok",
                    "warehouse_id": warehouse_id, "warehouse": houses.get(warehouse_id, "—"), "quantity": float(qty or 0), "value": float(value or 0)})
    return out
