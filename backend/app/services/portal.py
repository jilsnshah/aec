"""A customer's own enquiry page.

Each customer can be given a secret link (/e/<token>). Whoever has it sees the
business's products with that customer's prices and whether they are in stock
(not how many), and can send an enquiry, recorded as from that customer. The
link can be replaced (the old one stops working) or switched off.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..database import begin_write
from ..errors import NotFoundError, ValidationError
from ..models import (Customer, CustomerDelivery, CustomerDeliveryItem, CustomerEnquiry, OrderStatus, Product,
                      SalesOrder, SalesOrderItem, TallySync)
from . import enquiries as enquiry_service
from . import finance
from . import integration_settings as settings_service
from . import pricelists, reservations

MAX_PER_DAY = 20
MAX_LINES = 40
MAX_ORDERS = 50
INVOICE_KINDS = ("sales_invoice", "delivery_invoice")


def set_link(session: Session, customer_id: uuid.UUID, enabled: bool = True) -> Dict[str, Any]:
    """Create (or replace) a customer's link, or switch it off."""
    begin_write(session)
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError("Customer not found.")
    customer.portal_token = secrets.token_urlsafe(18) if enabled else None
    session.commit()
    return link_view(customer)


def link_view(customer: Customer) -> Dict[str, Any]:
    return {"enabled": bool(customer.portal_token), "path": "/e/{}".format(customer.portal_token) if customer.portal_token else None}


def _customer(session: Session, token: str) -> Customer:
    customer = session.execute(select(Customer).where(Customer.portal_token == token)).scalar_one_or_none() if token else None
    if customer is None or not customer.is_active:
        raise NotFoundError("This link is not valid any more. Please ask us for a new one.")
    return customer


def page(session: Session, token: str) -> Dict[str, Any]:
    customer = _customer(session, token)
    seller = settings_service.get(session, settings_service.TALLY).config.get("seller_name") or "Our shop"
    products = session.execute(select(Product).where(Product.is_active.is_(True)).order_by(Product.category.nulls_last(), Product.name)).scalars().all()
    prices = {line["product_id"]: line for line in pricelists.resolve(session, customer.id, [{"product_id": p.id, "quantity": "1"} for p in products])["lines"]} if products else {}
    reserved = reservations.reserved_map(session, [p.id for p in products])
    return {
        "business": seller,
        "customer": customer.name,
        "customer_summary": _summary(session, customer),
        "products": [
            {"id": p.id, "name": p.name, "unit": p.unit_of_measure, "category": p.category, "mrp": float(p.mrp or 0),
             "price": prices.get(p.id, {}).get("net_price", float(p.mrp or 0)),
             "in_stock": (p.physical_stock - reserved.get(p.id, Decimal("0"))) > 0}
            for p in products
        ],
    }


def _check_daily_limit(session: Session, customer: Customer) -> None:
    since = datetime.now(timezone.utc) - timedelta(days=1)
    recent = session.execute(
        select(func.count(CustomerEnquiry.id)).where(CustomerEnquiry.customer_id == customer.id, CustomerEnquiry.source == "link", CustomerEnquiry.created_at >= since)
    ).scalar_one()
    if recent >= MAX_PER_DAY:
        raise ValidationError("Too many enquiries today from this link. Please call or WhatsApp us.")


def send(session: Session, token: str, items: List[Dict[str, Any]], notes: Optional[str], name: Optional[str], phone: Optional[str]) -> Dict[str, Any]:
    customer = _customer(session, token)
    _check_daily_limit(session, customer)
    lines = []
    for item in (items or [])[:MAX_LINES]:
        try:
            qty = Decimal(str(item.get("quantity")))
            product_id = uuid.UUID(str(item.get("product_id")))
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError("Each line needs a product and a quantity.")
        if qty > 0:
            lines.append({"product_id": product_id, "quantity": str(qty), "discount_percent": "0"})
    if not lines:
        raise ValidationError("Add at least one product with a quantity.")
    resolved = {line["product_id"]: line for line in pricelists.resolve(session, customer.id, [{"product_id": l["product_id"], "quantity": l["quantity"]} for l in lines])["lines"]}
    for line in lines:
        hit = resolved.get(line["product_id"])
        if hit:
            line["discount_percent"] = str(hit["discount_percent"])
    note = (notes or "").strip()[:1000] or None
    enquiry = enquiry_service.create_enquiry(
        session, customer.id, lines, notes=note, source="link", source_detail="customer link",
        sender_name=(name or "").strip()[:255] or None, sender_phone=(phone or "").strip()[:32] or None,
    )
    return {"enquiry_number": enquiry.enquiry_number, "lines": len(enquiry.items), "total": float(enquiry_service.enquiry_total(enquiry))}


# ---------------------------------------------------------------------------
# The customer's own records: orders, deliveries, account, invoices. Every
# query below is filtered by the token's customer; nothing shows cost or margin.
# ---------------------------------------------------------------------------

def _f(value: Any) -> float:
    return float(value or 0)


def _status(order: SalesOrder) -> str:
    return order.status.value if hasattr(order.status, "value") else str(order.status)


def _summary(session: Session, customer: Customer) -> Dict[str, Any]:
    open_orders = session.execute(
        select(func.count(SalesOrder.id)).where(
            SalesOrder.customer_id == customer.id,
            SalesOrder.status.in_([OrderStatus.PENDING, OrderStatus.PARTIALLY_FULFILLED]),
        )
    ).scalar_one()
    last = session.execute(select(func.max(SalesOrder.created_at)).where(SalesOrder.customer_id == customer.id)).scalar_one()
    account = finance.statement(session, "customer", customer.id)["summary"]
    return {
        "open_orders": int(open_orders or 0),
        "amount_open": account["open"],
        "overdue": account["overdue"],
        "payment_terms_days": account["payment_terms_days"],
        "last_order_date": last.date().isoformat() if last else None,
    }


def _qty(item: SalesOrderItem, value: Decimal) -> float:
    """A base-unit quantity in the unit the customer ordered in."""
    return float(item._in_unit(value) or 0)


def orders(session: Session, token: str) -> Dict[str, Any]:
    customer = _customer(session, token)
    rows = session.execute(
        select(SalesOrder)
        .where(SalesOrder.customer_id == customer.id)
        .options(selectinload(SalesOrder.items).selectinload(SalesOrderItem.product))
        .order_by(SalesOrder.created_at.desc())
        .limit(MAX_ORDERS)
    ).scalars().all()
    order_ids = [o.id for o in rows]
    deliveries: Dict[uuid.UUID, List[CustomerDelivery]] = {}
    if order_ids:
        for d in session.execute(
            select(CustomerDelivery)
            .where(CustomerDelivery.customer_id == customer.id, CustomerDelivery.sales_order_id.in_(order_ids))
            .options(selectinload(CustomerDelivery.items).selectinload(CustomerDeliveryItem.order_item).selectinload(SalesOrderItem.product),
                     selectinload(CustomerDelivery.transporter))
            .order_by(CustomerDelivery.created_at)
        ).scalars().all():
            deliveries.setdefault(d.sales_order_id, []).append(d)
    result = []
    for order in rows:
        lines = []
        for item in order.items:
            pending = item.quantity_pending
            lines.append({
                "id": item.id,
                "product": item.product.name,
                "unit": item.unit_name,
                "ordered": _qty(item, item.quantity_ordered),
                "delivered": _qty(item, item.quantity_fulfilled),
                "ready": _qty(item, min(item.quantity_reserved, pending) if pending > 0 else Decimal("0")),
                "pending": _qty(item, pending if pending > 0 else Decimal("0")),
                "cancelled": _qty(item, item.quantity_cancelled),
                "rate": float(item.unit_rate),
            })
        result.append({
            "id": order.id,
            "number": order.order_number,
            "date": order.created_at.date().isoformat(),
            "status": _status(order),
            "total": _f(order.total_amount),
            "lines": lines,
            "deliveries": [
                {
                    "id": d.id,
                    "number": d.delivery_number,
                    "date": d.created_at.date().isoformat(),
                    "vehicle_number": d.vehicle_number,
                    "lr_number": d.lr_number,
                    "transporter": d.transporter.name if d.transporter is not None else None,
                    "eway_bill_number": d.eway_bill_number,
                    "lines": [
                        {"product": line.order_item.product.name, "unit": line.order_item.unit_name, "quantity": _qty(line.order_item, line.quantity)}
                        for line in d.items if line.quantity > 0
                    ],
                }
                for d in deliveries.get(order.id, [])
            ],
        })
    return {"orders": result}


def statement(session: Session, token: str) -> Dict[str, Any]:
    customer = _customer(session, token)
    data = finance.statement(session, "customer", customer.id)
    summary = data["summary"]
    return {
        "summary": {key: summary.get(key) for key in ("invoiced", "paid", "open", "overdue", "payment_terms_days")},
        "entries": [
            {"date": e["date"], "kind": e["kind"], "number": e["number"], "debit": e["debit"], "credit": e["credit"],
             "balance": e["balance"], "due_date": e.get("due_date"), "days_overdue": e.get("days_overdue", 0)}
            for e in data["entries"]
        ],
    }


def _invoice_rows(session: Session, customer: Customer) -> List[TallySync]:
    order_ids = select(SalesOrder.id).where(SalesOrder.customer_id == customer.id)
    delivery_ids = select(CustomerDelivery.id).where(CustomerDelivery.customer_id == customer.id)
    return list(session.execute(
        select(TallySync).where(
            TallySync.status == "synced",
            ((TallySync.kind == "sales_invoice") & TallySync.entity_id.in_(order_ids))
            | ((TallySync.kind == "delivery_invoice") & TallySync.entity_id.in_(delivery_ids)),
        ).order_by(TallySync.synced_at.desc().nulls_last(), TallySync.created_at.desc())
    ).scalars().all())


def invoices(session: Session, token: str) -> Dict[str, Any]:
    customer = _customer(session, token)
    rows = _invoice_rows(session, customer)
    orders_by_id = {o.id: o for o in session.execute(
        select(SalesOrder).where(SalesOrder.id.in_([r.entity_id for r in rows if r.kind == "sales_invoice"]))
    ).scalars()} if rows else {}
    deliveries_by_id = {d.id: d for d in session.execute(
        select(CustomerDelivery).where(CustomerDelivery.id.in_([r.entity_id for r in rows if r.kind == "delivery_invoice"]))
        .options(selectinload(CustomerDelivery.items).selectinload(CustomerDeliveryItem.order_item), selectinload(CustomerDelivery.sales_order))
    ).scalars()} if rows else {}
    out = []
    for row in rows:
        if row.kind == "sales_invoice":
            order = orders_by_id.get(row.entity_id)
            amount = _f(order.total_amount) if order else None
            order_number = order.order_number if order else None
        else:
            delivery = deliveries_by_id.get(row.entity_id)
            amount = round(sum(float(l.order_item.unit_price_net * l.quantity) for l in delivery.items), 2) if delivery else None
            order_number = delivery.sales_order.order_number if delivery else None
        when = row.synced_at or row.created_at
        out.append({
            "id": row.id,
            "number": row.tally_number or row.reference,
            "date": when.date().isoformat() if when else None,
            "order_number": order_number,
            "amount": amount,
            "eway_bill_number": row.eway_bill_no,
            "download": "/api/public/e/{}/invoices/{}.pdf".format(token, row.id),
        })
    return {"invoices": out}


def invoice_pdf(session: Session, token: str, sync_id: uuid.UUID):
    """The invoice for one of this customer's synced rows, as (filename, pdf bytes)."""
    from . import invoice_pdf as pdf
    from . import tally_sync

    customer = _customer(session, token)
    row = session.get(TallySync, sync_id)
    if row is None or row.status != "synced" or row.kind not in INVOICE_KINDS:
        raise NotFoundError("Invoice not found.")
    model = SalesOrder if row.kind == "sales_invoice" else CustomerDelivery
    owner = session.get(model, row.entity_id)
    if owner is None or owner.customer_id != customer.id:
        raise NotFoundError("Invoice not found.")
    invoice = tally_sync.build_invoice(session, row)
    return "Invoice-{}.pdf".format(invoice.number.replace("/", "-")), pdf.render(invoice)


def reorder(session: Session, token: str, order_id: uuid.UUID) -> Dict[str, Any]:
    """An enquiry (not an order) with the same lines as one of their orders."""
    customer = _customer(session, token)
    order = session.get(SalesOrder, order_id)
    if order is None or order.customer_id != customer.id:
        raise NotFoundError("Order not found.")
    _check_daily_limit(session, customer)
    products = set(session.execute(select(Product.id).where(Product.is_active.is_(True))).scalars())
    source = [item for item in order.items if item.product_id in products and item.quantity_ordered > 0][:MAX_LINES]
    if not source:
        raise ValidationError("None of the products on this order can be ordered now. Please call or WhatsApp us.")
    resolved = {line["product_id"]: line for line in pricelists.resolve(
        session, customer.id, [{"product_id": i.product_id, "quantity": str(i.quantity_ordered)} for i in source])["lines"]}
    lines = []
    for item in source:
        hit = resolved.get(item.product_id)
        line: Dict[str, Any] = {"product_id": item.product_id, "discount_percent": str(hit["discount_percent"]) if hit else "0"}
        if item.unit:
            line.update(unit=item.unit, quantity=str(item.unit_quantity))
        else:
            line["quantity"] = str(item.quantity_ordered)
        lines.append(line)
    enquiry = enquiry_service.create_enquiry(
        session, customer.id, lines, notes="Order again: {}".format(order.order_number), source="link", source_detail="customer link (order again)",
    )
    return {"enquiry_number": enquiry.enquiry_number, "lines": len(enquiry.items), "total": float(enquiry_service.enquiry_total(enquiry))}
