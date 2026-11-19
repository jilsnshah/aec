"""Customer price lists (price levels).

A list carries quantity breaks per product -- a fixed net price or a discount
off MRP from a minimum quantity -- and a default discount for everything else.
A customer is put on one list; order and enquiry lines for them start at the
list's price. The best break is the one with the highest minimum quantity the
line reaches. Like Tally price levels, Odoo pricelists and ERPNext pricing
rules. Prices stay suggestions: the person entering the order can change them,
and the order controls still apply.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..database import begin_write
from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import Customer, PriceList, PriceListItem, Product


def _d(value: Any, label: str) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        raise ValidationError("{} must be a number.".format(label))


def view(price_list: PriceList, session: Optional[Session] = None) -> Dict[str, Any]:
    customers = None
    if session is not None:
        customers = session.execute(select(func.count(Customer.id)).where(Customer.price_list_id == price_list.id)).scalar_one()
    return {
        "id": price_list.id,
        "name": price_list.name,
        "discount_percent": float(price_list.discount_percent),
        "notes": price_list.notes,
        "valid_from": price_list.valid_from,
        "valid_until": price_list.valid_until,
        "is_active": price_list.is_active,
        "customers": customers,
        "items": [
            {"id": item.id, "product_id": item.product_id, "product_name": item.product.name if item.product else None,
             "unit": item.product.unit_of_measure if item.product else None, "mrp": float(item.product.mrp) if item.product else None,
             "min_quantity": float(item.min_quantity), "price": float(item.price) if item.price is not None else None,
             "discount_percent": float(item.discount_percent) if item.discount_percent is not None else None}
            for item in sorted(price_list.items, key=lambda i: ((i.product.name if i.product else ""), i.min_quantity))
        ],
    }


def _load(session: Session, list_id: uuid.UUID) -> PriceList:
    row = session.execute(
        select(PriceList).where(PriceList.id == list_id).options(joinedload(PriceList.items).joinedload(PriceListItem.product))
    ).unique().scalar_one_or_none()
    if row is None:
        raise NotFoundError("Price list not found.")
    return row


def list_all(session: Session, include_inactive: bool = False) -> List[Dict[str, Any]]:
    stmt = select(PriceList).options(joinedload(PriceList.items).joinedload(PriceListItem.product)).order_by(PriceList.name)
    if not include_inactive:
        stmt = stmt.where(PriceList.is_active.is_(True))
    return [view(row, session) for row in session.execute(stmt).unique().scalars()]


def get(session: Session, list_id: uuid.UUID) -> Dict[str, Any]:
    return view(_load(session, list_id), session)


def save(session: Session, data: Dict[str, Any], list_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    """Create or replace a price list (its items are replaced as a whole)."""
    begin_write(session)
    try:
        name = (data.get("name") or "").strip()
        if not name:
            raise ValidationError("Give the price list a name.")
        clash = session.execute(select(PriceList).where(func.lower(PriceList.name) == name.lower())).scalar_one_or_none()
        if clash is not None and clash.id != list_id:
            raise ConflictError("A price list called '{}' already exists.".format(name))
        row = _load(session, list_id) if list_id else PriceList(name=name)
        if list_id is None:
            session.add(row)
        row.name = name
        discount = _d(data.get("discount_percent"), "Discount") or Decimal("0")
        if not Decimal("0") <= discount <= Decimal("100"):
            raise ValidationError("The list discount must be between 0 and 100%.")
        row.discount_percent = discount
        row.notes = (data.get("notes") or "").strip() or None
        row.valid_from = data.get("valid_from")
        row.valid_until = data.get("valid_until")
        if row.valid_from and row.valid_until and row.valid_until < row.valid_from:
            raise ValidationError("The list ends before it starts.")
        if data.get("is_active") is not None:
            row.is_active = bool(data["is_active"])
        if data.get("items") is not None:
            row.items.clear()
            session.flush()
            seen = set()
            for item in data["items"]:
                product_id = uuid.UUID(str(item["product_id"]))
                if session.get(Product, product_id) is None:
                    raise ValidationError("A product on the list no longer exists.")
                minimum = _d(item.get("min_quantity"), "Minimum quantity") or Decimal("0")
                price = _d(item.get("price"), "Price")
                pct = _d(item.get("discount_percent"), "Discount")
                if (price is None) == (pct is None):
                    raise ValidationError("Give each line either a fixed price or a discount, not both.")
                if price is not None and price < 0 or pct is not None and not Decimal("0") <= pct <= Decimal("100"):
                    raise ValidationError("Prices cannot be negative and discounts must be 0–100%.")
                key = (product_id, minimum)
                if key in seen:
                    raise ValidationError("A product has two lines with the same minimum quantity.")
                seen.add(key)
                row.items.append(PriceListItem(product_id=product_id, min_quantity=minimum, price=price, discount_percent=pct))
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get(session, row.id)


def _active(price_list: PriceList) -> bool:
    now = datetime.now(timezone.utc)
    return price_list.is_active and (price_list.valid_from is None or price_list.valid_from <= now) and (price_list.valid_until is None or price_list.valid_until >= now)


def resolve(session: Session, customer_id: Optional[uuid.UUID], lines: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """The price each line gets for this customer: the best quantity break on
    their list, else the list discount, else MRP. Returned as a discount off
    MRP (what order lines carry) and as a net price."""
    customer = session.get(Customer, customer_id) if customer_id else None
    price_list = _load(session, customer.price_list_id) if customer and customer.price_list_id else None
    usable = price_list is not None and _active(price_list)
    out = []
    for line in lines:
        product = session.get(Product, uuid.UUID(str(line["product_id"])))
        if product is None:
            continue
        qty = _d(line.get("quantity"), "Quantity") or Decimal("0")
        mrp = product.mrp or Decimal("0")
        rule = "MRP"
        pct = Decimal("0")
        if usable:
            breaks = sorted((i for i in price_list.items if i.product_id == product.id and i.min_quantity <= qty), key=lambda i: i.min_quantity, reverse=True)
            if breaks:
                best = breaks[0]
                if best.price is not None:
                    pct = (Decimal("1") - best.price / mrp) * 100 if mrp > 0 else Decimal("0")
                    rule = "{}: fixed price{}".format(price_list.name, " from {:g}".format(float(best.min_quantity)) if best.min_quantity else "")
                else:
                    pct = best.discount_percent
                    rule = "{}: {:g}% off{}".format(price_list.name, float(pct), " from {:g}".format(float(best.min_quantity)) if best.min_quantity else "")
            elif price_list.discount_percent:
                pct = price_list.discount_percent
                rule = "{}: list discount {:g}%".format(price_list.name, float(pct))
        pct = max(Decimal("0"), min(Decimal("100"), pct)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        out.append({"product_id": product.id, "mrp": float(mrp), "discount_percent": float(pct),
                    "net_price": float((mrp * (1 - pct / 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)), "rule": rule})
    return {"price_list": price_list.name if price_list else None, "price_list_active": usable, "lines": out}
