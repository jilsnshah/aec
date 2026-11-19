"""Money in and out: payments, receivables, payables and statements.

* An **invoice** is a delivery to a customer: delivered quantity x the line's
  net price, due ``payment_terms_days`` after the delivery.
* A **bill** is a goods receipt from a supplier: received quantity x unit
  cost, due ``payment_terms_days`` after it arrived.
* **Payments** settle a party's oldest open invoices or bills first (open-item
  matching by date). Anything paid beyond what is invoiced is an advance.

Everything is derived from stored deliveries, receipts and payments; nothing
is estimated.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import begin_write
from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import (
    Customer,
    CustomerDelivery,
    CustomerDeliveryItem,
    GoodsReceipt,
    GoodsReceiptItem,
    Payment,
    PurchaseOrder,
    SalesOrder,
    SalesOrderItem,
    Supplier,
    utcnow,
)
from ..numeric import ZERO_MONEY, money
from .common import count_matching, next_document_number, windowed

METHODS = ("cash", "bank", "upi", "cheque", "card", "other")
BUCKETS = [("not_due", None, 0), ("1-30", 1, 30), ("31-60", 31, 60), ("61-90", 61, 90), ("90+", 91, None)]
ZERO = Decimal("0.00")


def _zone() -> ZoneInfo:
    return ZoneInfo(get_settings().business_timezone)


def _today() -> date:
    return datetime.now(_zone()).date()


def _local_day(value: datetime) -> date:
    return value.astimezone(_zone()).date()


def _f(value: Any) -> float:
    return round(float(value or 0), 2)


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


def record_payment(
    session: Session,
    direction: str,
    amount: Any,
    paid_on: Optional[date] = None,
    customer_id: Optional[uuid.UUID] = None,
    supplier_id: Optional[uuid.UUID] = None,
    method: str = "bank",
    reference: Optional[str] = None,
    notes: Optional[str] = None,
    sales_order_id: Optional[uuid.UUID] = None,
    purchase_order_id: Optional[uuid.UUID] = None,
    created_by_id: Optional[uuid.UUID] = None,
) -> Payment:
    if direction not in ("in", "out"):
        raise ValidationError("direction must be in (from a customer) or out (to a supplier).")
    value = money(amount, "Amount")
    if value <= 0:
        raise ValidationError("The amount must be more than zero.")
    method = (method or "bank").lower()
    if method not in METHODS:
        raise ValidationError("Method must be one of: {}.".format(", ".join(METHODS)))
    day = paid_on or _today()
    if day > _today() + timedelta(days=1):
        raise ValidationError("A payment cannot be dated in the future.")
    begin_write(session)
    if direction == "in":
        if customer_id is None or supplier_id is not None:
            raise ValidationError("Money in comes from a customer: give customer_id only.")
        if session.get(Customer, customer_id) is None:
            raise NotFoundError("Customer not found.")
        if sales_order_id is not None:
            order = session.get(SalesOrder, sales_order_id)
            if order is None or order.customer_id != customer_id:
                raise ValidationError("That order does not belong to this customer.")
        purchase_order_id = None
    else:
        if supplier_id is None or customer_id is not None:
            raise ValidationError("Money out goes to a supplier: give supplier_id only.")
        if session.get(Supplier, supplier_id) is None:
            raise NotFoundError("Supplier not found.")
        if purchase_order_id is not None:
            po = session.get(PurchaseOrder, purchase_order_id)
            if po is None or po.supplier_id != supplier_id:
                raise ValidationError("That purchase order does not belong to this supplier.")
        sales_order_id = None
    number = next_document_number(session, "payment_" + direction, "RCV" if direction == "in" else "PAY")
    payment = Payment(
        number=number, direction=direction, customer_id=customer_id, supplier_id=supplier_id,
        sales_order_id=sales_order_id, purchase_order_id=purchase_order_id, amount=value,
        paid_on=datetime.combine(day, time(12), tzinfo=_zone()), method=method,
        reference=(reference or "").strip()[:128] or None, notes=(notes or "").strip() or None,
        created_by_id=created_by_id,
    )
    session.add(payment)
    session.commit()
    return payment


def void_payment(session: Session, payment_id: uuid.UUID, reason: Optional[str]) -> Payment:
    begin_write(session)
    payment = session.get(Payment, payment_id, with_for_update=True)
    if payment is None:
        raise NotFoundError("Payment not found.")
    if payment.voided_at is not None:
        raise ConflictError("This payment is already void.")
    payment.voided_at = utcnow()
    payment.void_reason = (reason or "").strip() or "No reason given"
    from .controls import log

    log(session, None, "payment_void", "payment", str(payment.id),
        "Voided {} of {:,.2f}: {}".format(payment.number, payment.amount, payment.void_reason))
    session.commit()
    return payment


def _payment_filter(direction=None, customer_id=None, supplier_id=None, start=None, end=None, search=None, include_voided=False):
    stmt = select(Payment)
    if direction:
        stmt = stmt.where(Payment.direction == direction)
    if customer_id:
        stmt = stmt.where(Payment.customer_id == customer_id)
    if supplier_id:
        stmt = stmt.where(Payment.supplier_id == supplier_id)
    if start:
        stmt = stmt.where(Payment.paid_on >= datetime.combine(start, time.min, tzinfo=_zone()))
    if end:
        stmt = stmt.where(Payment.paid_on < datetime.combine(end + timedelta(days=1), time.min, tzinfo=_zone()))
    if search:
        pattern = "%{}%".format(search.strip())
        stmt = stmt.outerjoin(Customer, Payment.customer_id == Customer.id).outerjoin(Supplier, Payment.supplier_id == Supplier.id)
        stmt = stmt.where(or_(Payment.number.ilike(pattern), Payment.reference.ilike(pattern), Customer.name.ilike(pattern), Supplier.name.ilike(pattern)))
    if not include_voided:
        stmt = stmt.where(Payment.voided_at.is_(None))
    return stmt


def list_payments(session: Session, limit: int = 50, offset: int = 0, **filters: Any) -> List[Payment]:
    stmt = _payment_filter(**filters).order_by(Payment.paid_on.desc(), Payment.created_at.desc())
    return list(session.execute(windowed(stmt, limit, offset)).scalars().all())


def count_payments(session: Session, **filters: Any) -> int:
    return count_matching(session, _payment_filter(**filters))


def payment_view(payment: Payment) -> Dict[str, Any]:
    return {
        "id": payment.id,
        "number": payment.number,
        "direction": payment.direction,
        "customer_id": payment.customer_id,
        "supplier_id": payment.supplier_id,
        "party_name": payment.customer.name if payment.customer else payment.supplier.name if payment.supplier else None,
        "sales_order_id": payment.sales_order_id,
        "purchase_order_id": payment.purchase_order_id,
        "amount": payment.amount,
        "paid_on": _local_day(payment.paid_on),
        "method": payment.method,
        "reference": payment.reference,
        "notes": payment.notes,
        "voided": payment.voided_at is not None,
        "void_reason": payment.void_reason,
        "created_at": payment.created_at,
    }


# ---------------------------------------------------------------------------
# Invoices, bills and open items
# ---------------------------------------------------------------------------


def _invoices(session: Session, customer_id: Optional[uuid.UUID] = None) -> Dict[uuid.UUID, List[Dict[str, Any]]]:
    stmt = (
        select(CustomerDelivery.id, CustomerDelivery.customer_id, CustomerDelivery.delivery_number, CustomerDelivery.created_at,
               CustomerDelivery.sales_order_id, SalesOrder.order_number,
               func.sum(CustomerDeliveryItem.quantity * SalesOrderItem.unit_price_net))
        .join(CustomerDeliveryItem, CustomerDeliveryItem.customer_delivery_id == CustomerDelivery.id)
        .join(SalesOrderItem, CustomerDeliveryItem.order_item_id == SalesOrderItem.id)
        .join(SalesOrder, CustomerDelivery.sales_order_id == SalesOrder.id)
        .group_by(CustomerDelivery.id, SalesOrder.order_number)
        .order_by(CustomerDelivery.created_at)
    )
    if customer_id:
        stmt = stmt.where(CustomerDelivery.customer_id == customer_id)
    out: Dict[uuid.UUID, List[Dict[str, Any]]] = defaultdict(list)
    for row in session.execute(stmt).all():
        out[row[1]].append({"id": row[0], "number": row[2], "date": row[3], "order_id": row[4], "order_number": row[5],
                            "amount": money(row[6] or 0)})
    return out


def _bills(session: Session, supplier_id: Optional[uuid.UUID] = None) -> Dict[uuid.UUID, List[Dict[str, Any]]]:
    stmt = (
        select(GoodsReceipt.id, GoodsReceipt.supplier_id, GoodsReceipt.receipt_number, GoodsReceipt.created_at,
               GoodsReceipt.purchase_order_id, PurchaseOrder.po_number, func.sum(GoodsReceiptItem.total_cost))
        .join(GoodsReceiptItem, GoodsReceiptItem.goods_receipt_id == GoodsReceipt.id)
        .join(PurchaseOrder, GoodsReceipt.purchase_order_id == PurchaseOrder.id)
        .group_by(GoodsReceipt.id, PurchaseOrder.po_number)
        .order_by(GoodsReceipt.created_at)
    )
    if supplier_id:
        stmt = stmt.where(GoodsReceipt.supplier_id == supplier_id)
    out: Dict[uuid.UUID, List[Dict[str, Any]]] = defaultdict(list)
    for row in session.execute(stmt).all():
        out[row[1]].append({"id": row[0], "number": row[2], "date": row[3], "order_id": row[4], "order_number": row[5],
                            "amount": money(row[6] or 0)})
    return out


def _paid(session: Session, direction: str) -> Dict[uuid.UUID, Decimal]:
    party = Payment.customer_id if direction == "in" else Payment.supplier_id
    rows = session.execute(
        select(party, func.sum(Payment.amount)).where(Payment.direction == direction, Payment.voided_at.is_(None)).group_by(party)
    ).all()
    paid = {party_id: money(total or 0) for party_id, total in rows}
    if direction == "in":
        # Credit notes (sales returns) settle invoices like payments do.
        from . import returns

        for customer_id, credit in returns.credits_by_customer(session).items():
            paid[customer_id] = paid.get(customer_id, ZERO_MONEY) + credit
    return paid


def _match(documents: List[Dict[str, Any]], paid: Decimal, terms: int) -> Tuple[List[Dict[str, Any]], Decimal]:
    """Settle the oldest documents first; return each with what is still open."""
    today = _today()
    remaining = paid
    out = []
    for document in documents:
        settled = min(document["amount"], remaining)
        remaining -= settled
        due = _local_day(document["date"]) + timedelta(days=terms)
        open_amount = document["amount"] - settled
        out.append(dict(document, date=_local_day(document["date"]), due_date=due, paid=settled, open=open_amount,
                        days_overdue=max(0, (today - due).days) if open_amount > 0 else 0))
    return out, remaining  # remaining > 0 is an advance


def _bucket(days_overdue: int, due: date) -> str:
    if due >= _today():
        return "not_due"
    for name, low, high in BUCKETS[1:]:
        if days_overdue >= low and (high is None or days_overdue <= high):
            return name
    return "90+"


def _ageing(direction: str, session: Session) -> Dict[str, Any]:
    receivable = direction == "in"
    documents = _invoices(session) if receivable else _bills(session)
    paid = _paid(session, direction)
    model = Customer if receivable else Supplier
    parties = {row.id: row for row in session.execute(select(model)).scalars()}
    rows = []
    overdue_documents = []
    totals = {"invoiced": ZERO, "paid": ZERO, "open": ZERO, "overdue": ZERO, "advances": ZERO,
              "buckets": {name: ZERO for name, _, _ in BUCKETS}}
    for party_id in set(documents) | set(paid):
        party = parties.get(party_id)
        if party is None:
            continue
        docs, advance = _match(documents.get(party_id, []), paid.get(party_id, ZERO), party.payment_terms_days or 0)
        buckets = {name: ZERO for name, _, _ in BUCKETS}
        for doc in docs:
            if doc["open"] > 0:
                name = _bucket(doc["days_overdue"], doc["due_date"])
                buckets[name] += doc["open"]
                if name != "not_due":
                    overdue_documents.append(dict(doc, party_id=party_id, party_name=party.name))
        invoiced = sum((doc["amount"] for doc in docs), ZERO)
        open_total = sum((doc["open"] for doc in docs), ZERO)
        overdue = open_total - buckets["not_due"]
        oldest = max((doc["days_overdue"] for doc in docs if doc["open"] > 0), default=0)
        row = {
            "party_id": party_id,
            "name": party.name,
            "payment_terms_days": party.payment_terms_days or 0,
            "invoiced": _f(invoiced),
            "paid": _f(paid.get(party_id, ZERO)),
            "open": _f(open_total),
            "advance": _f(advance),
            "overdue": _f(overdue),
            "oldest_overdue_days": oldest,
            "buckets": {name: _f(value) for name, value in buckets.items()},
        }
        if receivable:
            limit = party.credit_limit
            row["credit_limit"] = _f(limit) if limit is not None else None
            row["over_credit_limit"] = bool(limit is not None and open_total > limit)
            row["credit_available"] = _f(limit - open_total) if limit is not None else None
        rows.append(row)
        totals["invoiced"] += invoiced
        totals["paid"] += paid.get(party_id, ZERO)
        totals["open"] += open_total
        totals["overdue"] += overdue
        totals["advances"] += advance
        for name in buckets:
            totals["buckets"][name] += buckets[name]
    rows.sort(key=lambda row: (-row["overdue"], -row["open"]))
    overdue_documents.sort(key=lambda doc: (-doc["days_overdue"], -doc["open"]))
    return {
        "as_of": _today(),
        "totals": {key: (_f(value) if not isinstance(value, dict) else {k: _f(v) for k, v in value.items()}) for key, value in totals.items()},
        "parties": rows,
        "overdue": [
            {"document_id": doc["id"], "number": doc["number"], "date": doc["date"], "due_date": doc["due_date"],
             "order_id": doc["order_id"], "order_number": doc["order_number"], "amount": _f(doc["amount"]),
             "open": _f(doc["open"]), "days_overdue": doc["days_overdue"], "party_id": doc["party_id"],
             "party_name": doc["party_name"]}
            for doc in overdue_documents
        ],
    }


def receivables(session: Session) -> Dict[str, Any]:
    """What customers owe for goods delivered, by age past the due date."""
    return _ageing("in", session)


def payables(session: Session) -> Dict[str, Any]:
    """What the business owes suppliers for goods received, by age."""
    return _ageing("out", session)


def statement(session: Session, party: str, party_id: uuid.UUID) -> Dict[str, Any]:
    """A party's account: invoices (or bills) and payments, with a running balance."""
    receivable = party == "customer"
    model = Customer if receivable else Supplier
    record = session.get(model, party_id)
    if record is None:
        raise NotFoundError("{} not found.".format(party.capitalize()))
    documents = (_invoices(session, party_id) if receivable else _bills(session, party_id)).get(party_id, [])
    payments = session.execute(
        select(Payment).where(
            (Payment.customer_id if receivable else Payment.supplier_id) == party_id, Payment.voided_at.is_(None)
        ).order_by(Payment.paid_on)
    ).scalars().all()
    credits = []
    if receivable:
        from ..models import SalesReturn

        credits = session.execute(select(SalesReturn).where(SalesReturn.customer_id == party_id).order_by(SalesReturn.created_at)).scalars().all()
    paid_total = sum((p.amount for p in payments), ZERO) + sum((c.amount for c in credits), ZERO)
    matched, advance = _match(documents, paid_total, record.payment_terms_days or 0)
    entries = [
        {"date": doc["date"], "kind": "invoice" if receivable else "bill", "number": doc["number"], "id": doc["id"],
         "order_id": doc["order_id"], "order_number": doc["order_number"], "debit": _f(doc["amount"]), "credit": 0.0,
         "due_date": doc["due_date"], "open": _f(doc["open"]), "days_overdue": doc["days_overdue"]}
        for doc in matched
    ] + [
        {"date": _local_day(p.paid_on), "kind": "payment", "number": p.number, "id": p.id, "order_id": p.sales_order_id or p.purchase_order_id,
         "order_number": None, "debit": 0.0, "credit": _f(p.amount), "method": p.method, "reference": p.reference}
        for p in payments
    ] + [
        {"date": _local_day(c.created_at), "kind": "credit_note", "number": c.number, "id": c.id, "order_id": c.sales_order_id,
         "order_number": None, "debit": 0.0, "credit": _f(c.amount), "method": "return", "reference": c.note}
        for c in credits
    ]
    entries.sort(key=lambda entry: (entry["date"], 0 if entry["kind"] != "payment" else 1))
    balance = 0.0
    for entry in entries:
        balance = round(balance + entry["debit"] - entry["credit"], 2)
        entry["balance"] = balance
    open_total = sum((doc["open"] for doc in matched), ZERO)
    overdue = sum((doc["open"] for doc in matched if doc["days_overdue"] > 0), ZERO)
    summary = {
        "invoiced": _f(sum((doc["amount"] for doc in matched), ZERO)),
        "paid": _f(paid_total),
        "balance": balance,
        "open": _f(open_total),
        "overdue": _f(overdue),
        "advance": _f(advance),
        "payment_terms_days": record.payment_terms_days or 0,
    }
    if receivable:
        summary["credit_limit"] = _f(record.credit_limit) if record.credit_limit is not None else None
        summary["over_credit_limit"] = bool(record.credit_limit is not None and open_total > record.credit_limit)
    return {"party": party, "party_id": party_id, "name": record.name, "summary": summary, "entries": entries}


def collected(session: Session, start: datetime, end: datetime) -> Dict[str, float]:
    """Money in and out between two instants."""
    rows = session.execute(
        select(Payment.direction, func.sum(Payment.amount))
        .where(Payment.voided_at.is_(None), Payment.paid_on >= start, Payment.paid_on < end)
        .group_by(Payment.direction)
    ).all()
    found = {direction: _f(total) for direction, total in rows}
    return {"received": found.get("in", 0.0), "paid": found.get("out", 0.0)}
