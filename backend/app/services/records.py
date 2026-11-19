"""Record-level intelligence: timelines, a customer's full picture, price and
cost history, live checks on a draft order, payment status per order, and
purchase suggestions grouped by supplier.

These follow what established ERPs put on every record (an activity trail, a
360-degree customer view, price history, credit and margin checks at order
entry, supplier price comparison) using only stored data.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from ..errors import NotFoundError
from ..models import (
    Customer,
    CustomerDelivery,
    CustomerDeliveryItem,
    CustomerEnquiry,
    EnquiryStatus,
    GoodsReceipt,
    GoodsReceiptItem,
    OrderStatus,
    Payment,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    SalesOrder,
    SalesOrderItem,
    SalesReturn,
    StockMovement,
    StockReceipt,
    Supplier,
    Task,
    TaskStatus,
)
from . import costing, finance, insights


def _f(value: Any) -> float:
    return round(float(value or 0), 2)


def _event(when: datetime, kind: str, title: str, detail: str = "", link: Optional[str] = None, amount: Optional[float] = None) -> Dict[str, Any]:
    return {"at": when, "kind": kind, "title": title, "detail": detail, "link": link, "amount": amount}


# ---------------------------------------------------------------------------
# Timelines
# ---------------------------------------------------------------------------


def timeline(session: Session, customer_id=None, supplier_id=None, product_id=None, order_id=None, limit: int = 60) -> List[Dict[str, Any]]:
    """Everything that happened to one record, newest first."""
    events: List[Dict[str, Any]] = []
    if customer_id:
        for order in session.execute(select(SalesOrder).where(SalesOrder.customer_id == customer_id)).scalars():
            events.append(_event(order.created_at, "order", "Order {} placed".format(order.order_number),
                                 order.status.value.replace("_", " ").lower(), "/orders/{}".format(order.id), _f(order.total_amount)))
            if order.cancelled_at:
                events.append(_event(order.cancelled_at, "cancel", "Order {} cancelled".format(order.order_number), "", "/orders/{}".format(order.id)))
        for enquiry in session.execute(select(CustomerEnquiry).where(CustomerEnquiry.customer_id == customer_id)).scalars():
            events.append(_event(enquiry.created_at, "enquiry", "Enquiry {} received".format(enquiry.enquiry_number), "via {}".format(enquiry.source), "/enquiries/{}".format(enquiry.id)))
            if enquiry.converted_at:
                events.append(_event(enquiry.converted_at, "won", "Enquiry {} won".format(enquiry.enquiry_number), "", "/enquiries/{}".format(enquiry.id)))
            if enquiry.lost_at:
                events.append(_event(enquiry.lost_at, "lost", "Enquiry {} lost".format(enquiry.enquiry_number), enquiry.lost_reason or "", "/enquiries/{}".format(enquiry.id)))
        rows = session.execute(
            select(CustomerDelivery, func.sum(CustomerDeliveryItem.quantity * SalesOrderItem.unit_price_net))
            .join(CustomerDeliveryItem, CustomerDeliveryItem.customer_delivery_id == CustomerDelivery.id)
            .join(SalesOrderItem, CustomerDeliveryItem.order_item_id == SalesOrderItem.id)
            .where(CustomerDelivery.customer_id == customer_id)
            .group_by(CustomerDelivery.id)
        ).all()
        for delivery, value in rows:
            events.append(_event(delivery.created_at, "delivery", "Delivered {}".format(delivery.delivery_number), "", "/orders/{}".format(delivery.sales_order_id), _f(value)))
        for payment in session.execute(select(Payment).where(Payment.customer_id == customer_id)).scalars():
            events.append(_event(payment.paid_on, "payment", "Paid {} ({})".format(payment.number, payment.method),
                                 "void: {}".format(payment.void_reason) if payment.voided_at else payment.reference or "", None, _f(payment.amount)))
        for ret in session.execute(select(SalesReturn).where(SalesReturn.customer_id == customer_id)).scalars():
            events.append(_event(ret.created_at, "return", "Returned goods ({})".format(ret.number), ret.note or "", "/orders/{}".format(ret.sales_order_id), -_f(ret.amount)))
        tasks = select(Task).where(Task.customer_id == customer_id)
    elif supplier_id:
        for po in session.execute(select(PurchaseOrder).where(PurchaseOrder.supplier_id == supplier_id)).scalars():
            events.append(_event(po.ordered_at or po.created_at, "purchase", "{} {}".format(po.po_number, "placed" if po.ordered_at else "drafted"),
                                 po.status.value.replace("_", " ").lower(), "/purchase-orders/{}".format(po.id)))
        rows = session.execute(
            select(GoodsReceipt, func.sum(GoodsReceiptItem.total_cost))
            .join(GoodsReceiptItem, GoodsReceiptItem.goods_receipt_id == GoodsReceipt.id)
            .where(GoodsReceipt.supplier_id == supplier_id).group_by(GoodsReceipt.id)
        ).all()
        for receipt, value in rows:
            events.append(_event(receipt.created_at, "receipt", "Received {}".format(receipt.receipt_number), receipt.delivery_note_reference or "", "/receipts/{}".format(receipt.id), _f(value)))
        for payment in session.execute(select(Payment).where(Payment.supplier_id == supplier_id)).scalars():
            events.append(_event(payment.paid_on, "payment", "Paid {} ({})".format(payment.number, payment.method), payment.reference or "", None, _f(payment.amount)))
        tasks = select(Task).where(Task.supplier_id == supplier_id)
    elif product_id:
        for movement in session.execute(select(StockMovement).where(StockMovement.product_id == product_id)).scalars():
            label = {"OPENING_STOCK": "Opening stock", "STOCK_RECEIPT": "Stock in", "GOODS_RECEIPT": "Goods received",
                     "CUSTOMER_DELIVERY": "Delivered", "ORDER_FULFILMENT": "Delivered", "ADJUSTMENT": "Adjusted", "SALES_RETURN": "Returned by customer"}.get(movement.movement_type.value, movement.movement_type.value)
            qty = float(movement.quantity_change)
            events.append(_event(movement.created_at, "in" if qty > 0 else "out", "{} {:+g}".format(label, qty), movement.note or ""))
        rows = session.execute(
            select(SalesOrder.id, SalesOrder.order_number, SalesOrder.created_at, Customer.name, SalesOrderItem.quantity_ordered, SalesOrderItem.unit_price_net)
            .join(SalesOrderItem, SalesOrderItem.order_id == SalesOrder.id).join(Customer, SalesOrder.customer_id == Customer.id)
            .where(SalesOrderItem.product_id == product_id)
        ).all()
        for oid, number, created, customer, qty, price in rows:
            events.append(_event(created, "order", "Sold {:g} to {}".format(float(qty), customer), "{} at {:,.2f}".format(number, float(price)), "/orders/{}".format(oid)))
        tasks = None
    elif order_id:
        order = session.get(SalesOrder, order_id)
        if order is None:
            raise NotFoundError("Order not found.")
        events.append(_event(order.created_at, "order", "Order placed", "", None, _f(order.total_amount)))
        if order.enquiry_id and order.enquiry:
            events.append(_event(order.enquiry.created_at, "enquiry", "Enquiry {} received".format(order.enquiry.enquiry_number), "", "/enquiries/{}".format(order.enquiry_id)))
        rows = session.execute(
            select(CustomerDelivery, func.sum(CustomerDeliveryItem.quantity * SalesOrderItem.unit_price_net), func.sum(CustomerDeliveryItem.quantity))
            .join(CustomerDeliveryItem, CustomerDeliveryItem.customer_delivery_id == CustomerDelivery.id)
            .join(SalesOrderItem, CustomerDeliveryItem.order_item_id == SalesOrderItem.id)
            .where(CustomerDelivery.sales_order_id == order_id).group_by(CustomerDelivery.id)
        ).all()
        for delivery, value, qty in rows:
            events.append(_event(delivery.created_at, "delivery", "Delivered {} ({:g} units)".format(delivery.delivery_number, float(qty)), delivery.reference or "", None, _f(value)))
        for payment in session.execute(select(Payment).where(Payment.sales_order_id == order_id)).scalars():
            events.append(_event(payment.paid_on, "payment", "Payment {}".format(payment.number), payment.method, None, _f(payment.amount)))
        for ret in session.execute(select(SalesReturn).where(SalesReturn.sales_order_id == order_id)).scalars():
            events.append(_event(ret.created_at, "return", "Return {}".format(ret.number), ret.note or "", None, -_f(ret.amount)))
        from ..models import AuditEvent

        for audit in session.execute(select(AuditEvent).where(AuditEvent.entity_id == str(order_id), AuditEvent.action.like("whatsapp_%"))).scalars():
            events.append(_event(audit.at, "message" if audit.action.endswith("sent") else "cancel", "WhatsApp confirmation " + ("sent" if audit.action.endswith("sent") else "not sent"), audit.summary))
        if order.cancelled_at:
            events.append(_event(order.cancelled_at, "cancel", "Cancelled", ""))
        tasks = select(Task).where(Task.sales_order_id == order_id)
    else:
        return []
    if tasks is not None:
        for task in session.execute(tasks).scalars():
            events.append(_event(task.created_at, "task", "Follow-up planned: {}".format(task.title), "due {}".format(task.due_date.date()) if task.due_date else "", "/tasks"))
            if task.completed_at:
                events.append(_event(task.completed_at, "done", "Follow-up done: {}".format(task.title), "", "/tasks"))
    events.sort(key=lambda event: event["at"], reverse=True)
    return events[:limit]


# ---------------------------------------------------------------------------
# Customer 360
# ---------------------------------------------------------------------------


def customer_profile(session: Session, customer_id: uuid.UUID) -> Dict[str, Any]:
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError("Customer not found.")
    seg = next((row for row in insights.customer_segments(session)["customers"] if row["customer_id"] == customer_id), None)
    statement = finance.statement(session, "customer", customer_id)["summary"]
    since = datetime.now().astimezone() - timedelta(days=365)
    month = func.to_char(func.timezone(insights._zone().key, SalesOrder.created_at), literal_column("'YYYY-MM'")).label("month")
    monthly = session.execute(
        select(month, func.sum(SalesOrder.total_amount), func.count(SalesOrder.id))
        .where(SalesOrder.customer_id == customer_id, SalesOrder.status != OrderStatus.CANCELLED, SalesOrder.created_at >= since)
        .group_by(literal_column("month")).order_by(literal_column("month"))
    ).all()
    top = session.execute(
        select(Product.id, Product.name, Product.unit_of_measure,
               func.sum(SalesOrderItem.quantity_ordered - SalesOrderItem.quantity_cancelled),
               func.sum((SalesOrderItem.quantity_ordered - SalesOrderItem.quantity_cancelled) * SalesOrderItem.unit_price_net),
               func.max(SalesOrder.created_at))
        .join(SalesOrderItem, SalesOrderItem.product_id == Product.id).join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .where(SalesOrder.customer_id == customer_id, SalesOrder.status != OrderStatus.CANCELLED)
        .group_by(Product.id).order_by(func.sum((SalesOrderItem.quantity_ordered - SalesOrderItem.quantity_cancelled) * SalesOrderItem.unit_price_net).desc())
        .limit(8)
    ).all()
    open_enquiries = session.execute(
        select(func.count(CustomerEnquiry.id)).where(CustomerEnquiry.customer_id == customer_id, CustomerEnquiry.status == EnquiryStatus.OPEN)
    ).scalar_one()
    decided = session.execute(
        select(CustomerEnquiry.status, func.count(CustomerEnquiry.id)).where(CustomerEnquiry.customer_id == customer_id, CustomerEnquiry.status != EnquiryStatus.OPEN).group_by(CustomerEnquiry.status)
    ).all()
    decided_map = {status.value: count for status, count in decided}
    won, lost = decided_map.get("CONVERTED", 0), decided_map.get("LOST", 0)
    discount = session.execute(
        select(func.sum((SalesOrderItem.unit_price - SalesOrderItem.unit_price_net) * SalesOrderItem.quantity_ordered),
               func.sum(SalesOrderItem.unit_price * SalesOrderItem.quantity_ordered))
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .where(SalesOrder.customer_id == customer_id, SalesOrder.status != OrderStatus.CANCELLED)
    ).one()
    limit = float(customer.credit_limit) if customer.credit_limit is not None else None
    return {
        "customer_id": customer_id,
        "segment": seg["segment"] if seg else "prospect",
        "orders": seg["orders"] if seg else 0,
        "lifetime_booked": seg["booked_value"] if seg else 0.0,
        "lifetime_revenue": seg["revenue"] if seg else 0.0,
        "average_order_value": seg["average_order_value"] if seg else 0.0,
        "average_days_between_orders": seg["average_days_between_orders"] if seg else None,
        "days_since_last_order": seg["days_since_last_order"] if seg else None,
        "estimated_annual_value": seg["estimated_annual_value"] if seg else None,
        "share_of_sales_percent": seg["share_percent"] if seg else None,
        "rank": seg["rank"] if seg else None,
        "average_discount_percent": round(float(discount[0] or 0) / float(discount[1]) * 100, 1) if discount[1] else None,
        "open_enquiries": open_enquiries,
        "enquiry_win_rate_percent": round(won / (won + lost) * 100, 1) if (won + lost) else None,
        "account": statement,
        "credit_limit": limit,
        "credit_used_percent": round(statement["open"] / limit * 100, 1) if limit else None,
        "monthly": [{"month": month, "booked": _f(total), "orders": count} for month, total, count in monthly],
        "top_products": [{"product_id": pid, "name": name, "unit": unit, "quantity": _f(qty), "value": _f(value), "last_ordered": last}
                         for pid, name, unit, qty, value, last in top],
    }


# ---------------------------------------------------------------------------
# Prices and costs
# ---------------------------------------------------------------------------


def product_prices(session: Session, product_id: uuid.UUID, customer_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    product = session.get(Product, product_id)
    if product is None:
        raise NotFoundError("Product not found.")
    stmt = (
        select(SalesOrder.id, SalesOrder.order_number, SalesOrder.created_at, Customer.id, Customer.name,
               SalesOrderItem.quantity_ordered, SalesOrderItem.unit_price, SalesOrderItem.discount_percent, SalesOrderItem.unit_price_net)
        .join(SalesOrderItem, SalesOrderItem.order_id == SalesOrder.id).join(Customer, SalesOrder.customer_id == Customer.id)
        .where(SalesOrderItem.product_id == product_id, SalesOrder.status != OrderStatus.CANCELLED)
        .order_by(SalesOrder.created_at.desc())
    )
    if customer_id:
        stmt = stmt.where(SalesOrder.customer_id == customer_id)
    sales = [
        {"order_id": oid, "order_number": number, "date": created, "customer_id": cid, "customer": cname, "quantity": _f(qty),
         "list_price": _f(price), "discount_percent": _f(disc), "net_price": _f(net)}
        for oid, number, created, cid, cname, qty, price, disc, net in session.execute(stmt.limit(30)).all()
    ]
    costs = session.execute(
        select(Supplier.id, Supplier.name, func.count(PurchaseOrderItem.id), func.min(PurchaseOrderItem.unit_cost),
               func.max(PurchaseOrderItem.unit_cost), func.avg(PurchaseOrderItem.unit_cost), func.max(PurchaseOrder.created_at))
        .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id).join(Supplier, PurchaseOrder.supplier_id == Supplier.id)
        .where(PurchaseOrderItem.product_id == product_id, PurchaseOrder.status != PurchaseOrderStatus.CANCELLED, PurchaseOrderItem.unit_cost > 0)
        .group_by(Supplier.id)
    ).all()
    last_cost = {}
    for sid, cost in session.execute(
        select(PurchaseOrder.supplier_id, PurchaseOrderItem.unit_cost)
        .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .where(PurchaseOrderItem.product_id == product_id, PurchaseOrder.status != PurchaseOrderStatus.CANCELLED, PurchaseOrderItem.unit_cost > 0)
        .order_by(PurchaseOrder.created_at)
    ).all():
        last_cost[sid] = cost
    suppliers = sorted(
        [{"supplier_id": sid, "name": name, "orders": count, "lowest": _f(low), "highest": _f(high), "average": _f(avg),
          "last": _f(last_cost.get(sid)), "last_date": last, "preferred": sid == product.preferred_supplier_id}
         for sid, name, count, low, high, avg, last in costs],
        key=lambda row: row["last"] or 1e12,
    )
    stock_in = session.execute(
        select(func.avg(StockReceipt.unit_cost), func.count(StockReceipt.id)).where(StockReceipt.product_id == product_id, StockReceipt.unit_cost > 0)
    ).one()
    valuation = costing.stock_valuation(session, product_id)
    buyers = session.execute(
        select(Customer.id, Customer.name, func.sum(SalesOrderItem.quantity_ordered - SalesOrderItem.quantity_cancelled),
               func.sum((SalesOrderItem.quantity_ordered - SalesOrderItem.quantity_cancelled) * SalesOrderItem.unit_price_net), func.max(SalesOrder.created_at))
        .join(SalesOrder, SalesOrder.customer_id == Customer.id).join(SalesOrderItem, SalesOrderItem.order_id == SalesOrder.id)
        .where(SalesOrderItem.product_id == product_id, SalesOrder.status != OrderStatus.CANCELLED)
        .group_by(Customer.id).order_by(func.sum((SalesOrderItem.quantity_ordered - SalesOrderItem.quantity_cancelled) * SalesOrderItem.unit_price_net).desc()).limit(10)
    ).all()
    nets = [row["net_price"] for row in sales]
    avg_cost = float(valuation.get("average_cost") or 0) or float(product.last_purchase_price or 0)
    return {
        "product_id": product_id,
        "mrp": _f(product.mrp),
        "average_cost": round(avg_cost, 2),
        "last_purchase_price": _f(product.last_purchase_price),
        "average_net_price": round(sum(nets) / len(nets), 2) if nets else None,
        "lowest_net_price": min(nets) if nets else None,
        "average_margin_percent": round((sum(nets) / len(nets) - avg_cost) / (sum(nets) / len(nets)) * 100, 1) if nets and avg_cost and sum(nets) else None,
        "sales": sales,
        "suppliers": suppliers,
        "stock_in_average_cost": _f(stock_in[0]) if stock_in[1] else None,
        "top_customers": [{"customer_id": cid, "name": name, "quantity": _f(qty), "value": _f(value), "last": last} for cid, name, qty, value, last in buyers],
    }


# ---------------------------------------------------------------------------
# Live checks on a draft order
# ---------------------------------------------------------------------------


def check_order(session: Session, customer_id: Optional[uuid.UUID], items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """What to know before placing an order: credit, margin, discount and stock."""
    warnings: List[Dict[str, Any]] = []
    lines: List[Dict[str, Any]] = []
    total = 0.0
    from . import reservations

    from . import units
    from ..errors import DomainError

    reserved = reservations.reserved_map(session)
    items = [dict(item) for item in items]
    for item in items:
        if "quantity_ordered" not in item and "quantity" in item:
            item["quantity_ordered"] = item["quantity"]
    try:
        units.apply(session, items, "quantity_ordered", "unit_price", "sales")
    except DomainError:
        pass
    for item in items:
        try:
            product = session.get(Product, uuid.UUID(str(item.get("product_id"))))
        except (ValueError, TypeError):
            product = None
        if product is None:
            continue
        qty = float(item.get("quantity_ordered") or item.get("quantity") or 0)
        price = float(item.get("unit_price") or product.mrp or 0)
        discount = float(item.get("discount_percent") or 0)
        net = price * (1 - discount / 100)
        total += qty * net
        valuation = costing.stock_valuation(session, product.id)
        cost = float(valuation.get("average_cost") or 0) or float(product.last_purchase_price or 0)
        margin = round((net - cost) / net * 100, 1) if net and cost else None
        last = None
        usual_discount = None
        if customer_id:
            row = session.execute(
                select(SalesOrderItem.unit_price_net, SalesOrderItem.discount_percent, SalesOrder.created_at)
                .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
                .where(SalesOrder.customer_id == customer_id, SalesOrderItem.product_id == product.id, SalesOrder.status != OrderStatus.CANCELLED)
                .order_by(SalesOrder.created_at.desc()).limit(1)
            ).first()
            if row:
                last = {"net_price": _f(row[0]), "discount_percent": _f(row[1]), "date": row[2]}
        avg_disc = session.execute(
            select(func.avg(SalesOrderItem.discount_percent)).join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
            .where(SalesOrderItem.product_id == product.id, SalesOrder.status != OrderStatus.CANCELLED)
        ).scalar_one()
        usual_discount = _f(avg_disc) if avg_disc is not None else None
        free = float(product.physical_stock or 0) - float(reserved.get(product.id, 0))
        line = {"product_id": product.id, "name": product.name, "unit": product.unit_of_measure, "net_price": round(net, 2),
                "cost": round(cost, 2), "margin_percent": margin, "free_stock": round(free, 3), "short": round(max(0.0, qty - max(0.0, free)), 3),
                "last_price_to_customer": last, "usual_discount_percent": usual_discount}
        lines.append(line)
        if cost and net < cost:
            warnings.append({"level": "critical", "kind": "below_cost", "text": "{} is priced at ₹{:,.2f}, below its cost of ₹{:,.2f}.".format(product.name, net, cost)})
        elif margin is not None and margin < 5:
            warnings.append({"level": "warning", "kind": "thin_margin", "text": "{} earns only {}% margin.".format(product.name, margin)})
        if usual_discount is not None and discount > max(usual_discount * 2, usual_discount + 5) and discount > 0:
            warnings.append({"level": "warning", "kind": "high_discount", "text": "{}% discount on {} is well above the usual {}%.".format(discount, product.name, usual_discount)})
        if last and abs(last["net_price"] - net) > 0.005 and net < last["net_price"]:
            warnings.append({"level": "info", "kind": "price_change", "text": "Last time this customer paid ₹{:,.2f} for {}; now ₹{:,.2f}.".format(last["net_price"], product.name, net)})
        if line["short"] > 0:
            warnings.append({"level": "info", "kind": "short", "text": "{:g} {} of {} is not in stock; it will wait as short.".format(line["short"], product.unit_of_measure, product.name)})
    credit = None
    if customer_id:
        customer = session.get(Customer, customer_id)
        if customer is not None:
            open_amount = finance.statement(session, "customer", customer_id)["summary"]
            outstanding_orders = session.execute(
                select(func.sum((SalesOrderItem.quantity_ordered - SalesOrderItem.quantity_fulfilled - SalesOrderItem.quantity_cancelled) * SalesOrderItem.unit_price_net))
                .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
                .where(SalesOrder.customer_id == customer_id, SalesOrder.status.in_([OrderStatus.PENDING, OrderStatus.PARTIALLY_FULFILLED]))
            ).scalar_one()
            exposure = open_amount["open"] + float(outstanding_orders or 0) + total
            credit = {"limit": _f(customer.credit_limit) if customer.credit_limit is not None else None, "owed": open_amount["open"],
                      "overdue": open_amount["overdue"], "undelivered_orders": _f(outstanding_orders), "exposure_after": round(exposure, 2)}
            if open_amount["overdue"] > 0:
                warnings.insert(0, {"level": "warning", "kind": "overdue", "text": "{} has ₹{:,.2f} overdue.".format(customer.name, open_amount["overdue"])})
            if customer.credit_limit is not None and exposure > float(customer.credit_limit):
                warnings.insert(0, {"level": "critical", "kind": "credit_limit", "text": "This order takes {} to ₹{:,.0f} owed and on order, over the ₹{:,.0f} credit limit.".format(customer.name, exposure, float(customer.credit_limit))})
    return {"total": round(total, 2), "lines": lines, "warnings": warnings, "credit": credit}


# ---------------------------------------------------------------------------
# Payment status per order, purchase suggestions
# ---------------------------------------------------------------------------


def order_payment_status(session: Session) -> Dict[str, Dict[str, Any]]:
    """For each order with deliveries: invoiced, paid (oldest-first matching per
    customer), open and how late. Orders with nothing delivered are not invoiced."""
    out: Dict[str, Dict[str, Any]] = {}
    invoices = finance._invoices(session)
    paid = finance._paid(session, "in")
    terms = dict(session.execute(select(Customer.id, Customer.payment_terms_days)).all())
    for customer_id, documents in invoices.items():
        matched, _ = finance._match(documents, paid.get(customer_id, Decimal("0")), terms.get(customer_id) or 0)
        for doc in matched:
            key = str(doc["order_id"])
            entry = out.setdefault(key, {"invoiced": 0.0, "paid": 0.0, "open": 0.0, "days_overdue": 0})
            entry["invoiced"] += _f(doc["amount"])
            entry["paid"] += _f(doc["paid"])
            entry["open"] += _f(doc["open"])
            entry["days_overdue"] = max(entry["days_overdue"], doc["days_overdue"])
    for entry in out.values():
        entry["status"] = "paid" if entry["open"] <= 0.005 else "overdue" if entry["days_overdue"] > 0 else "partly_paid" if entry["paid"] > 0 else "unpaid"
        for key in ("invoiced", "paid", "open"):
            entry[key] = round(entry[key], 2)
    return out


def purchase_suggestions(session: Session) -> Dict[str, Any]:
    """Products to buy now, grouped by the supplier to buy from (preferred, else
    the last one used), each with quantity and estimated cost."""
    health = insights.inventory_health(session)["products"]
    last_supplier = {}
    for pid, sid in session.execute(
        select(PurchaseOrderItem.product_id, PurchaseOrder.supplier_id)
        .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .where(PurchaseOrder.status != PurchaseOrderStatus.CANCELLED).order_by(PurchaseOrder.created_at)
    ).all():
        last_supplier[pid] = sid
    names = dict(session.execute(select(Supplier.id, Supplier.name)).all())
    groups: Dict[str, Dict[str, Any]] = {}
    for row in health:
        if row["action"]["code"] not in ("buy", "plan") or row["reorder_quantity"] <= 0:
            continue
        sid = row["preferred_supplier_id"] or last_supplier.get(row["product_id"])
        key = str(sid) if sid else "none"
        group = groups.setdefault(key, {"supplier_id": sid, "supplier_name": names.get(sid) if sid else None, "lines": [], "value": 0.0, "urgent": 0})
        group["lines"].append({"product_id": row["product_id"], "name": row["name"], "unit": row["unit"], "quantity": row["reorder_quantity"],
                               "unit_cost": row["unit_cost"], "value": row["reorder_value"], "order_by": row["order_by"], "reason": row["action"]["text"],
                               "short": row["short"]})
        group["value"] = round(group["value"] + row["reorder_value"], 2)
        if row["action"]["code"] == "buy":
            group["urgent"] += 1
    ordered = sorted(groups.values(), key=lambda g: (-g["urgent"], -g["value"]))
    return {"groups": ordered, "total_value": round(sum(g["value"] for g in ordered), 2),
            "note": "Quantities are estimates: recent sales over lead time plus minimum stock and a month of cover."}


def supplier_scorecard(session: Session, supplier_id: uuid.UUID) -> Dict[str, Any]:
    supplier = session.get(Supplier, supplier_id)
    if supplier is None:
        raise NotFoundError("Supplier not found.")
    row = next((r for r in insights.supplier_insights(session)["suppliers"] if r["supplier_id"] == supplier_id), None)
    late = [po for po in insights.supplier_insights(session)["late_purchase_orders"] if po["supplier_id"] == supplier_id]
    products = session.execute(
        select(Product.id, Product.name, Product.unit_of_measure, func.count(PurchaseOrderItem.id), func.sum(PurchaseOrderItem.quantity_ordered), func.max(PurchaseOrder.created_at))
        .join(PurchaseOrderItem, PurchaseOrderItem.product_id == Product.id).join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
        .where(PurchaseOrder.supplier_id == supplier_id, PurchaseOrder.status != PurchaseOrderStatus.CANCELLED)
        .group_by(Product.id).order_by(func.sum(PurchaseOrderItem.quantity_ordered * PurchaseOrderItem.unit_cost).desc())
    ).all()
    supplied = []
    for pid, name, unit, count, qty, last in products:
        prices = product_prices(session, pid)
        mine = next((s for s in prices["suppliers"] if s["supplier_id"] == supplier_id), None)
        best = prices["suppliers"][0] if prices["suppliers"] else None
        supplied.append({"product_id": pid, "name": name, "unit": unit, "orders": count, "quantity": _f(qty), "last_ordered": last,
                         "last_cost": mine["last"] if mine else None, "cheapest_supplier": best["name"] if best else None,
                         "cheapest_cost": best["last"] if best else None,
                         "is_cheapest": bool(best and mine and best["supplier_id"] == supplier_id)})
    score = None
    # Only score once something was received or is overdue: open orders not yet
    # due would otherwise count as a 0% fill rate.
    if row and (row.get("quantity_received") or late):
        parts = [value for value in (row.get("fill_rate_percent"), row.get("on_time_percent")) if value is not None]
        score = round(sum(parts) / len(parts)) if parts else None
    return {"supplier_id": supplier_id, "performance": row, "late_orders": late, "products": supplied,
            "score": score, "score_note": "Average of fill rate and on-time rate, where known."}
