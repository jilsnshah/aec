"""Plain-language details for a proposed change, with ids resolved to the
names and numbers people recognise; and a link to what a change created."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import Customer, CustomerEnquiry, Product, PurchaseOrder, SalesOrder, Supplier, Task, User

LOOKUPS = {
    "customer_id": (Customer, "Customer", lambda r: r.name),
    "supplier_id": (Supplier, "Supplier", lambda r: r.name),
    "product_id": (Product, "Product", lambda r: "{} ({})".format(r.name, r.sku)),
    "order_id": (SalesOrder, "Order", lambda r: r.order_number),
    "sales_order_id": (SalesOrder, "Order", lambda r: r.order_number),
    "enquiry_id": (CustomerEnquiry, "Enquiry", lambda r: r.enquiry_number),
    "po_id": (PurchaseOrder, "Purchase order", lambda r: r.po_number),
    "purchase_order_id": (PurchaseOrder, "Purchase order", lambda r: r.po_number),
    "task_id": (Task, "Follow-up", lambda r: r.title),
    "assignee_id": (User, "Assigned to", lambda r: r.username),
}
SKIP = {"summary", "idempotency_key"}


def _lookup(session: Session, key: str, value: Any) -> Optional[str]:
    entry = LOOKUPS.get(key)
    if not entry:
        return None
    model, _label, render = entry
    try:
        row = session.get(model, uuid.UUID(str(value)))
    except (ValueError, TypeError):
        return "unknown id {}".format(value)
    return render(row) if row is not None else "not found ({})".format(value)


def _label(key: str) -> str:
    if key in LOOKUPS:
        return LOOKUPS[key][1]
    return key.replace("_", " ").capitalize()


def describe_action(session: Session, operation, args: Dict[str, Any]) -> Dict[str, Any]:
    fields: List[Dict[str, str]] = []
    lines: List[Dict[str, str]] = []
    for key, value in args.items():
        if key in SKIP or value in (None, "", []):
            continue
        if isinstance(value, list) and value and isinstance(value[0], dict):
            for item in value:
                line = {}
                for sub, sub_value in item.items():
                    if sub_value in (None, ""):
                        continue
                    shown = _lookup(session, sub, sub_value) if sub in LOOKUPS else sub_value
                    line[_label(sub)] = str(shown)
                lines.append(line)
            continue
        shown = _lookup(session, key, value) if key in LOOKUPS else value
        fields.append({"label": _label(key), "value": str(shown)})
    return {"fields": fields, "lines": lines}


ROUTES = {
    "create_order": ("/orders/", "order_number"), "create_customer": ("/customers/", "name"),
    "update_customer": ("/customers/", "name"), "create_product": ("/products/", "name"),
    "update_product": ("/products/", "name"), "create_enquiry": ("/enquiries/", "enquiry_number"),
    "update_enquiry": ("/enquiries/", "enquiry_number"), "mark_enquiry_lost": ("/enquiries/", "enquiry_number"),
    "create_supplier": ("/suppliers/", "name"), "update_supplier": ("/suppliers/", "name"),
    "create_purchase_order": ("/purchase-orders/", "po_number"), "update_purchase_order": ("/purchase-orders/", "po_number"),
    "place_purchase_order": ("/purchase-orders/", "po_number"), "settle_purchase_order": ("/purchase-orders/", "po_number"),
    "cancel_purchase_order": ("/purchase-orders/", "po_number"), "cancel_order": ("/orders/", "order_number"),
    "cancel_rest_of_order": ("/orders/", "order_number"), "record_goods_receipt": ("/receipts/", "receipt_number"),
    "archive_product": ("/products/", "name"), "archive_customer": ("/customers/", "name"),
    "archive_supplier": ("/suppliers/", "name"),
}


def result_link(tool: str, data: Any) -> Optional[Dict[str, str]]:
    """Where to open what a change created or changed."""
    if not isinstance(data, dict):
        return None
    if tool == "convert_enquiry":
        order = data.get("order") or {}
        if order.get("id"):
            return {"path": "/orders/{}".format(order["id"]), "label": order.get("order_number") or "Open order"}
    if tool == "record_delivery":
        order_id = data.get("sales_order_id") or data.get("order_id")
        if order_id:
            return {"path": "/orders/{}".format(order_id), "label": data.get("delivery_number") or "Open order"}
    if tool in ("create_follow_up", "update_follow_up"):
        return {"path": "/tasks", "label": data.get("title") or "Follow-ups"}
    if tool == "record_stock_in":
        product = data.get("product_id")
        if product:
            return {"path": "/products/{}".format(product), "label": data.get("receipt_number") or "Open product"}
    route = ROUTES.get(tool)
    if route and data.get("id"):
        return {"path": "{}{}".format(route[0], data["id"]), "label": str(data.get(route[1]) or "Open")}
    return None
