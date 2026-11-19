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
from typing import Any, Dict, Iterable, List, Optional, Tuple

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
    stmt = select(PriceList).options(joinedload(PriceList.items).joinedload(PriceListItem.product)).where(PriceList.customer_id.is_(None)).order_by(PriceList.name)
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


def _line_rule(price_list: PriceList, product: Product, qty: Decimal) -> Optional[Tuple[Decimal, str]]:
    """The discount (off MRP) a list gives a product at a quantity, and why."""
    mrp = product.mrp or Decimal("0")
    breaks = sorted((i for i in price_list.items if i.product_id == product.id and i.min_quantity <= qty), key=lambda i: i.min_quantity, reverse=True)
    if breaks:
        best = breaks[0]
        suffix = " from {:g}".format(float(best.min_quantity)) if best.min_quantity else ""
        if best.price is not None:
            pct = (Decimal("1") - best.price / mrp) * 100 if mrp > 0 else Decimal("0")
            return pct, "fixed price{}".format(suffix)
        return best.discount_percent, "{:g}% off{}".format(float(best.discount_percent), suffix)
    if price_list.discount_percent:
        return price_list.discount_percent, "{:g}% off everything".format(float(price_list.discount_percent))
    return None


def sources_for(session: Session, customer: Optional[Customer]) -> List[Tuple[str, Any]]:
    """Everything that can price a customer's order, each with a label:
    their own prices, their flat discount, their price list, their groups."""
    if customer is None:
        return []
    from . import groups as group_service

    out: List[Tuple[str, Any]] = []
    own = session.execute(select(PriceList).where(PriceList.customer_id == customer.id)).scalar_one_or_none()
    if own is not None and _active(own):
        out.append(("Own prices", own))
    if customer.discount_percent:
        out.append(("Customer discount", customer.discount_percent))
    if customer.price_list_id:
        assigned = _load(session, customer.price_list_id)
        if _active(assigned):
            out.append((assigned.name, assigned))
    for group in group_service.groups_of(session, customer.id):
        if group.price_list_id:
            group_list = _load(session, group.price_list_id)
            if _active(group_list) and all(src is not group_list for _, src in out):
                out.append(("{} (group)".format(group.name), group_list))
    return out


def resolve(session: Session, customer_id: Optional[uuid.UUID], lines: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """The best price each line gets for this customer: of their own product
    prices, their flat discount, their price list and the price lists of every
    group they are in, the lowest net price wins. Returned as a discount off
    MRP (what order lines carry) and a net price, with where it came from."""
    customer = session.get(Customer, customer_id) if customer_id else None
    sources = sources_for(session, customer)
    out = []
    for line in lines:
        product = session.get(Product, uuid.UUID(str(line["product_id"])))
        if product is None:
            continue
        qty = _d(line.get("quantity"), "Quantity") or Decimal("0")
        mrp = product.mrp or Decimal("0")
        best_pct, best_rule, options = Decimal("0"), "MRP", []
        for label, source in sources:
            found = (source, "{:g}% off everything".format(float(source))) if isinstance(source, Decimal) else _line_rule(source, product, qty)
            if found is None:
                continue
            pct, why = found
            options.append({"source": label, "discount_percent": float(round(pct, 2)), "rule": why})
            if pct > best_pct:
                best_pct, best_rule = pct, "{}: {}".format(label, why)
        pct = max(Decimal("0"), min(Decimal("100"), best_pct)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        out.append({"product_id": product.id, "mrp": float(mrp), "discount_percent": float(pct),
                    "net_price": float((mrp * (1 - pct / 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)), "rule": best_rule,
                    "options": options})
    names = [label for label, _ in sources]
    return {"price_list": ", ".join(names) if names else None, "price_list_active": bool(sources), "sources": names, "lines": out}


# ---------------------------------------------------------------------------
# A customer's own pricing
# ---------------------------------------------------------------------------


def customer_pricing(session: Session, customer_id: uuid.UUID) -> Dict[str, Any]:
    from . import groups as group_service

    customer = session.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError("Customer not found.")
    own = session.execute(select(PriceList).where(PriceList.customer_id == customer_id)).scalar_one_or_none()
    assigned = _load(session, customer.price_list_id) if customer.price_list_id else None
    return {
        "customer_id": customer_id,
        "discount_percent": float(customer.discount_percent) if customer.discount_percent is not None else None,
        "price_list": {"id": assigned.id, "name": assigned.name, "discount_percent": float(assigned.discount_percent)} if assigned else None,
        "own_items": view(own)["items"] if own else [],
        "groups": [m for m in group_service.memberships(session, customer_id) if m["source"] != "excluded" and m["is_active"]],
        "kept_out": [m for m in group_service.memberships(session, customer_id) if m["source"] == "excluded"],
    }


def save_customer_pricing(session: Session, customer_id: uuid.UUID, discount_percent: Any = ..., items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Set a customer's flat discount and/or their own product prices."""
    begin_write(session)
    try:
        customer = session.get(Customer, customer_id)
        if customer is None:
            raise NotFoundError("Customer not found.")
        if discount_percent is not ...:
            pct = _d(discount_percent, "Discount")
            if pct is not None and not Decimal("0") <= pct <= Decimal("100"):
                raise ValidationError("The discount must be between 0 and 100%.")
            customer.discount_percent = pct if pct else None
        if items is not None:
            own = session.execute(select(PriceList).where(PriceList.customer_id == customer_id)).scalar_one_or_none()
            if own is None:
                own = PriceList(name="Own prices · {} · {}".format(customer.name[:40], str(customer.id)[:8]), customer_id=customer_id, discount_percent=Decimal("0"))
                session.add(own)
                session.flush()
            session.commit()
            save(session, {"name": own.name, "discount_percent": "0", "items": items}, own.id)
            return customer_pricing(session, customer_id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return customer_pricing(session, customer_id)
