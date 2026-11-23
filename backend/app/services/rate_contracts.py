"""Rate contracts: an agreed rate for a period.

* With a **supplier** -- a mill's rate for the year ("Rs 340 a bag till
  March, 5,000 bags"). New purchase orders to that supplier take the
  contract rate for its products while it runs.
* With a **customer** -- a builder's project rate. Their quotes and orders
  take the contract price (it competes with their other prices and the best
  one wins, like everything in pricing).

The rates live in a price list carrying the contract's dates, so they stop
applying on the day the contract ends. What has been bought or sold against
each line is tracked against the quantity agreed.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import begin_write
from ..errors import NotFoundError, ValidationError
from ..models import (
    Customer,
    OrderStatus,
    PriceList,
    PriceListItem,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    RateContract,
    SalesOrder,
    SalesOrderItem,
    Supplier,
)
from ..numeric import ZERO
from .common import next_document_number

COUNTER = "rate_contract"


def _zone() -> ZoneInfo:
    return ZoneInfo(get_settings().business_timezone)


def _today() -> date:
    return datetime.now(_zone()).date()


def _day(value: Any, end: bool = False) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    if not isinstance(value, date):
        raise ValidationError("Dates are YYYY-MM-DD.")
    # A contract day runs midnight to midnight where the business trades, not in UTC.
    return datetime.combine(value, time(23, 59, 59) if end else time(0, 0), tzinfo=_zone())


def status(contract: RateContract, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    if contract.is_cancelled:
        return "cancelled"
    if contract.valid_from > now:
        return "upcoming"
    if contract.valid_until < now:
        return "expired"
    return "expiring" if contract.valid_until - now <= timedelta(days=15) else "active"


def _usage(session: Session, contract: RateContract) -> Dict[uuid.UUID, Decimal]:
    """Quantity bought or sold against each product during the contract."""
    if contract.supplier_id:
        rows = session.execute(
            select(PurchaseOrderItem.product_id, func.sum(PurchaseOrderItem.quantity_ordered))
            .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
            .where(PurchaseOrder.supplier_id == contract.supplier_id, PurchaseOrder.status != PurchaseOrderStatus.CANCELLED,
                   PurchaseOrder.status != PurchaseOrderStatus.DRAFT,
                   PurchaseOrder.created_at >= contract.valid_from, PurchaseOrder.created_at <= contract.valid_until)
            .group_by(PurchaseOrderItem.product_id)
        ).all()
    else:
        rows = session.execute(
            select(SalesOrderItem.product_id, func.sum(SalesOrderItem.quantity_ordered - SalesOrderItem.quantity_cancelled))
            .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
            .where(SalesOrder.customer_id == contract.customer_id, SalesOrder.status != OrderStatus.CANCELLED,
                   SalesOrder.created_at >= contract.valid_from, SalesOrder.created_at <= contract.valid_until)
            .group_by(SalesOrderItem.product_id)
        ).all()
    return {pid: Decimal(q or 0) for pid, q in rows}


def view(session: Session, contract: RateContract, with_usage: bool = True) -> Dict[str, Any]:
    used = _usage(session, contract) if with_usage else {}
    items = []
    for item in sorted(contract.price_list.items, key=lambda i: (i.product.name if i.product else "", i.min_quantity)):
        committed = item.committed_quantity
        done = used.get(item.product_id, ZERO)
        items.append({"id": item.id, "product_id": item.product_id, "product": item.product.name if item.product else None,
                      "unit": item.product.unit_of_measure if item.product else None, "mrp": float(item.product.mrp) if item.product else None,
                      "rate": float(item.price) if item.price is not None else None,
                      "discount_percent": float(item.discount_percent) if item.discount_percent is not None else None,
                      "min_quantity": float(item.min_quantity), "committed_quantity": float(committed) if committed is not None else None,
                      "used_quantity": float(done), "left_quantity": float(committed - done) if committed is not None else None,
                      "used_percent": round(float(done / committed * 100), 1) if committed else None})
    party = contract.supplier or contract.customer
    return {"id": contract.id, "number": contract.number, "title": contract.title, "party": "supplier" if contract.supplier_id else "customer",
            "supplier_id": contract.supplier_id, "customer_id": contract.customer_id, "party_name": party.name if party else None,
            "address_id": contract.address_id, "valid_from": contract.valid_from, "valid_until": contract.valid_until, "reference": contract.reference,
            "terms": contract.terms, "status": status(contract), "days_left": max(0, (contract.valid_until - datetime.now(timezone.utc)).days),
            "items": items, "created_at": contract.created_at}


def _load(session: Session, contract_id: uuid.UUID) -> RateContract:
    row = session.get(RateContract, contract_id)
    if row is None:
        raise NotFoundError("Rate contract not found.")
    return row


def get(session: Session, contract_id: uuid.UUID) -> Dict[str, Any]:
    return view(session, _load(session, contract_id))


def list_contracts(session: Session, party: Optional[str] = None, party_id: Optional[uuid.UUID] = None, include_old: bool = True) -> List[Dict[str, Any]]:
    stmt = select(RateContract).order_by(RateContract.valid_until.desc())
    if party == "supplier":
        stmt = stmt.where(RateContract.supplier_id.is_not(None))
    elif party == "customer":
        stmt = stmt.where(RateContract.customer_id.is_not(None))
    if party_id:
        stmt = stmt.where((RateContract.supplier_id == party_id) | (RateContract.customer_id == party_id))
    out = [view(session, c) for c in session.execute(stmt).scalars()]
    return out if include_old else [c for c in out if c["status"] not in ("expired", "cancelled")]


def save(session: Session, data: Dict[str, Any], contract_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    from . import pricelists, units

    begin_write(session)
    try:
        contract = _load(session, contract_id) if contract_id else None
        if contract is None:
            supplier_id, customer_id = data.get("supplier_id"), data.get("customer_id")
            if bool(supplier_id) == bool(customer_id):
                raise ValidationError("A rate contract is with one supplier or one customer.")
            if supplier_id and session.get(Supplier, uuid.UUID(str(supplier_id))) is None:
                raise NotFoundError("Supplier not found.")
            if customer_id and session.get(Customer, uuid.UUID(str(customer_id))) is None:
                raise NotFoundError("Customer not found.")
            number = next_document_number(session, COUNTER, "RC")
            plist = PriceList(name="Contract {} · {}".format(number, str(uuid.uuid4())[:6]), discount_percent=Decimal("0"), is_active=True)
            session.add(plist)
            session.flush()
            contract = RateContract(number=number, supplier_id=uuid.UUID(str(supplier_id)) if supplier_id else None,
                                    customer_id=uuid.UUID(str(customer_id)) if customer_id else None, price_list_id=plist.id,
                                    title=(data.get("title") or "").strip() or "Rate contract", valid_from=_day(data.get("valid_from") or _today()),
                                    valid_until=_day(data.get("valid_until") or (_today() + timedelta(days=365)), end=True))
            session.add(contract)
        if contract.is_cancelled:
            raise ValidationError("{} is cancelled.".format(contract.number))
        if "title" in data and data["title"] is not None:
            contract.title = data["title"].strip() or contract.title
        if data.get("valid_from"):
            contract.valid_from = _day(data["valid_from"])
        if data.get("valid_until"):
            contract.valid_until = _day(data["valid_until"], end=True)
        if contract.valid_until < contract.valid_from:
            raise ValidationError("The contract ends before it starts.")
        for key in ("reference", "terms"):
            if key in data:
                setattr(contract, key, (data[key] or "").strip() or None)
        if "address_id" in data:
            contract.address_id = uuid.UUID(str(data["address_id"])) if data["address_id"] else None
        session.flush()
        plist = session.get(PriceList, contract.price_list_id)
        plist.valid_from, plist.valid_until = contract.valid_from, contract.valid_until
        items = data.get("items")
        commitments: Dict[Tuple[uuid.UUID, Decimal], Optional[Decimal]] = {}
        if items is not None:
            lines = [dict(i) for i in items if i.get("product_id")]
            purpose = "purchase" if contract.supplier_id else "sales"
            # Rates and quantities may be per tonne, per brass...: converted to the base unit below.
            clean = []
            for line in lines:
                product = session.get(Product, uuid.UUID(str(line["product_id"])))
                if product is None:
                    raise NotFoundError("Product not found.")
                _, factor = units.find(session, product, line.get("unit"), purpose)
                rate = line.get("rate")
                discount = line.get("discount_percent")
                if (rate in (None, "")) == (discount in (None, "")):
                    raise ValidationError("Give {} a rate or a discount.".format(product.name))
                committed = line.get("committed_quantity")
                clean.append({"product_id": product.id, "min_quantity": str(Decimal(str(line.get("min_quantity") or 0)) * factor),
                              "price": str((Decimal(str(rate)) / factor).quantize(Decimal("0.0001"))) if rate not in (None, "") else None,
                              "discount_percent": str(discount) if discount not in (None, "") else None})
                commitments[(product.id, Decimal(clean[-1]["min_quantity"]))] = Decimal(str(committed)) * factor if committed not in (None, "") else None
            session.commit()
            pricelists.save(session, {"name": plist.name, "discount_percent": "0", "items": clean, "is_active": True,
                                      "valid_from": contract.valid_from, "valid_until": contract.valid_until}, plist.id)
            begin_write(session)
            for item in session.execute(select(PriceListItem).where(PriceListItem.price_list_id == plist.id)).scalars():
                item.committed_quantity = commitments.get((item.product_id, item.min_quantity))
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get(session, contract.id)


def cancel(session: Session, contract_id: uuid.UUID) -> Dict[str, Any]:
    begin_write(session)
    contract = _load(session, contract_id)
    contract.is_cancelled = True
    plist = session.get(PriceList, contract.price_list_id)
    plist.is_active = False
    session.commit()
    return get(session, contract_id)


def supplier_rate(session: Session, supplier_id: uuid.UUID, product_id: uuid.UUID, quantity: Decimal = ZERO,
                  on: Optional[datetime] = None) -> Optional[Tuple[Decimal, RateContract]]:
    """The lowest running contract rate (per base unit) for a product from a supplier."""
    on = on or datetime.now(timezone.utc)
    best: Optional[Tuple[Decimal, RateContract]] = None
    for contract in session.execute(select(RateContract).where(
            RateContract.supplier_id == supplier_id, RateContract.is_cancelled.is_(False),
            RateContract.valid_from <= on, RateContract.valid_until >= on)).scalars():
        breaks = [i for i in contract.price_list.items if i.product_id == product_id and i.min_quantity <= quantity]
        if not breaks:
            breaks = [i for i in contract.price_list.items if i.product_id == product_id]
        for item in sorted(breaks, key=lambda i: i.min_quantity, reverse=True)[:1]:
            product = item.product
            rate = item.price if item.price is not None else (product.mrp * (1 - item.discount_percent / 100))
            if best is None or rate < best[0]:
                best = (Decimal(rate), contract)
    return best


def customer_lists(session: Session, customer_id: uuid.UUID) -> List[Tuple[str, PriceList]]:
    """A customer's running contracts as pricing sources."""
    out = []
    for contract in session.execute(select(RateContract).where(RateContract.customer_id == customer_id, RateContract.is_cancelled.is_(False))).scalars():
        out.append(("Contract {}".format(contract.number), contract.price_list))
    return out
