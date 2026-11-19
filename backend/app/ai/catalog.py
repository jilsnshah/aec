"""The assistant's operations: one entry per REST route it may use.

Adding a capability to the assistant is adding a line here. The argument
schema is not written by hand -- it is derived from the route's own OpenAPI
description (path, query and body), so the assistant always sends exactly
what the screens send, and the route validates it the same way.

Risk decides whether a call needs the user's confirmation:

* ``read``        runs at once.
* ``write``       routine edits (contacts, notes, follow-ups); confirmed unless
                  Settings allow routine changes without asking.
* ``financial``   money or stock: orders, purchases, receipts, deliveries.
* ``destructive`` cancels, archives, marks lost. Always confirmed.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Operation:
    name: str
    method: str
    path: str
    group: str
    description: str
    risk: str = "read"
    label: str = ""

    @property
    def mutates(self) -> bool:
        return self.risk != "read"


def op(name, method, path, group, description, risk="read", label=""):
    return Operation(name, method, path, group, description.strip(), risk, label or name.replace("_", " ").capitalize())


OPERATIONS: List[Operation] = [
    # --- Insights --------------------------------------------------------------
    op("daily_briefing", "GET", "/api/insights/briefing", "insights",
       "Today at a glance: today's and this month's trading, follow-ups due, stock at risk, open enquiries and the most urgent alerts. Start here for 'how is the business doing' or 'what should I do today'."),
    op("business_overview", "GET", "/api/insights/overview", "insights",
       "Compare a period with the previous one of the same length: orders, booked value, delivered revenue, cost of goods, gross profit, margin, enquiries, conversion rate, new customers, purchasing; plus a daily series. Use for 'this month vs last month', trends and performance questions."),
    op("inventory_health", "GET", "/api/insights/inventory", "insights",
       "Per-product inventory health: free/reserved/on order/short quantities, value at cost, stock age buckets (0-30, 31-60, 61-90, 90+ days), daily sales rate, days of cover, last sale, flags (short, dead, slow, low_cover, reorder) and a recommended reorder quantity; totals include capital at risk. Use for low stock, reorder, dead or slow stock, ageing and capital tied up."),
    op("sales_breakdown", "GET", "/api/insights/sales", "insights",
       "Booked value, delivered revenue, cost and gross profit grouped by product, customer, month or day for any period or date range. Use for best/worst products or customers, revenue by month, profitability."),
    op("enquiry_funnel", "GET", "/api/insights/enquiries", "insights",
       "The enquiry funnel: counts, conversion rate by source (manual, whatsapp, email), average days to convert, open pipeline value, lost reasons, and stale open enquiries (untouched for days) with whether they have a follow-up."),
    op("customer_ranking", "GET", "/api/insights/customers", "insights",
       "Customers ranked by value with orders, revenue, average order, outstanding deliveries, open enquiries, last order date and dormant customers (no order for 60+ days); also customers who never ordered."),
    op("supplier_performance", "GET", "/api/insights/suppliers", "insights",
       "Supplier performance: spend, purchase orders, average lead time, fill rate, on-time rate, value still due, and late purchase orders."),
    op("list_alerts", "GET", "/api/insights/alerts", "insights",
       "Everything that needs attention now, most urgent first: short stock, low cover, late purchase orders, stale enquiries, orders waiting long, overdue follow-ups, dead stock."),
    op("dashboard_summary", "GET", "/api/inventory/summary", "insights",
       "The home dashboard figures: stock totals, open orders, revenue, cost, profit, margin, discounts, products short, recent orders and receipts, and 30 days of daily sales."),

    op("sales_explorer", "GET", "/api/insights/explore", "insights",
       "Explore any sales measure (booked_value, quantity_booked, orders, discount, revenue, quantity_delivered, cost_of_goods, gross_profit) grouped by product, category, customer, month, week, weekday, day or none, for any period or date range, filtered by categories, product_ids or customer_ids (comma-separated), with the previous period alongside, share and Pareto running share. Use for 'why did sales change', contribution and comparison questions."),
    op("sales_heatmap", "GET", "/api/insights/heatmap", "insights",
       "A sales measure by weekday and week (weekly rhythm, busiest days)."),
    op("product_intelligence", "GET", "/api/insights/products", "insights",
       "Per product for a period: booked value vs the previous period (growing/declining), ABC class (Pareto), margin quadrant (star, volume_low_margin, niche_high_margin, weak), discount given, enquiry conversion, stock flags; products with many enquiries but weak conversion; products bought together (only with enough orders)."),
    op("customer_segments", "GET", "/api/insights/segments", "insights",
       "Customers by segment (champion, loyal, at_risk, dormant, new, occasional) with recency, frequency, value, average days between orders, ESTIMATED annual value, open and overdue receivables; new vs returning customers by month; repeat rate."),
    op("receivables", "GET", "/api/finance/receivables", "finance",
       "What customers owe for goods delivered: per customer open, overdue, ageing buckets past due (not_due, 1-30, 31-60, 61-90, 90+), credit limit use; plus every overdue invoice. Use for collections and 'who owes us money'."),
    op("payables", "GET", "/api/finance/payables", "finance",
       "What the business owes suppliers for goods received, with ageing and overdue bills."),
    op("customer_statement", "GET", "/api/finance/customers/{customer_id}/statement", "finance",
       "A customer's account statement: invoices (deliveries) and payments with running balance, open and overdue amounts, credit limit."),
    op("supplier_statement", "GET", "/api/finance/suppliers/{supplier_id}/statement", "finance",
       "A supplier's account statement: bills (goods received) and payments with running balance."),
    op("list_payments", "GET", "/api/payments", "finance", "Payments received (direction=in) and made (direction=out), filterable by party and dates."),
    op("record_payment", "POST", "/api/payments", "finance",
       "Record money received from a customer (direction in, customer_id) or paid to a supplier (direction out, supplier_id), with amount, date, method and reference. It settles the oldest open invoices or bills first.", "financial"),
    op("void_payment", "POST", "/api/payments/{payment_id}/void", "finance", "Void a payment entered by mistake, with a reason.", "destructive"),
    op("record_timeline", "GET", "/api/records/timeline", "insights",
       "Everything that happened to one customer, supplier, product or order (pass one id), newest first."),
    op("customer_profile", "GET", "/api/records/customers/{customer_id}/profile", "customers",
       "A customer's 360 view: segment, lifetime value, frequency, average discount, win rate, owed, credit used, monthly spend, top products."),
    op("product_prices", "GET", "/api/records/products/{product_id}/prices", "inventory",
       "Selling price history of a product (optionally to one customer_id), margin, cost by supplier with the cheapest first, top buyers."),
    op("check_order", "POST", "/api/records/order-check", "sales",
       "Check a draft order before creating it (credit limit, overdue, below cost, thin margin, unusual discount, stock short). Read-only."),
    op("order_payment_status", "GET", "/api/records/order-payments", "finance",
       "Paid, open and overdue amounts per order id (delivered orders only)."),
    op("supplier_scorecard", "GET", "/api/records/suppliers/{supplier_id}/scorecard", "purchasing",
       "A supplier's score, late orders and price on each product against the cheapest supplier."),
    op("purchase_suggestions", "GET", "/api/records/purchase-suggestions", "purchasing",
       "What to buy now, grouped by supplier, with estimated quantities and cost."),
    op("list_stock_adjustments", "GET", "/api/stock-adjustments", "inventory",
       "Stock adjustments and counts (damaged, lost, found, count differences) with value at cost and totals by reason."),
    op("stock_count_sheet", "GET", "/api/stock-adjustments/count-sheet", "inventory",
       "Products to count with the quantity the books expect, optionally for one category."),
    op("post_stock_adjustment", "POST", "/api/stock-adjustments", "inventory",
       "Post a stock count (counted_quantity per product, as_count true) or an adjustment (quantity_change with a reason: damaged, lost, expired, found, sample, correction).", "financial"),
    op("returnable_lines", "GET", "/api/orders/{order_id}/returnable", "sales",
       "An order's lines with delivered, already returned and still returnable quantities."),
    op("record_sales_return", "POST", "/api/orders/{order_id}/returns", "sales",
       "Record goods a customer sent back (credit note): reason, lines with order_item_id, quantity and restock (false if damaged). Credits their account.", "financial"),
    op("check_order_controls", "POST", "/api/controls/check", "sales",
       "Which business controls (credit limit, overdue, discount, margin, below cost) a draft order would trip, and whether they block it."),
    op("audit_log", "GET", "/api/audit", "insights", "Audit log: control overrides, stock adjustments, returns and voided payments, newest first."),
    op("list_targets", "GET", "/api/targets", "insights", "Monthly sales targets (booked or revenue)."),
    op("set_target", "PUT", "/api/targets", "insights", "Set a monthly sales target: month YYYY-MM, metric booked or revenue, amount (0 removes it).", "write"),
    op("product_categories", "GET", "/api/products/categories", "inventory", "Product categories in use with product counts."),

    # --- Products and stock -------------------------------------------------------
    op("list_products", "GET", "/api/products", "inventory",
       "Search or list products (catalogue) with stock, free stock, on order and MRP. Use search to find a product's id by name or SKU."),
    op("get_product", "GET", "/api/products/{product_id}", "inventory", "One product's details."),
    op("product_stock_history", "GET", "/api/products/{product_id}/inventory", "inventory",
       "A product's stock movements, cost layers (FIFO) and the customers waiting for it."),
    op("product_waiting_orders", "GET", "/api/products/{product_id}/pending-orders", "inventory",
       "Customer order lines still waiting for a product, oldest first, with a proposed split of a given incoming quantity."),
    op("create_product", "POST", "/api/products", "inventory", "Add a product to the catalogue.", "write"),
    op("update_product", "PATCH", "/api/products/{product_id}", "inventory",
       "Change a product's name, SKU, unit, MRP or description. Only send the fields to change.", "write"),
    op("archive_product", "POST", "/api/products/{product_id}/archive", "inventory",
       "Archive a product so it can no longer be sold or bought.", "destructive"),
    op("record_stock_in", "POST", "/api/stock-receipts", "inventory",
       "Record stock that arrived without a purchase order (quantity and unit cost). Stock rises at once; waiting customers can be given theirs via allocations.", "financial"),

    # --- Customers ---------------------------------------------------------------
    op("list_customers", "GET", "/api/customers", "customers",
       "Search or list customers with order counts and values. Use search to find a customer's id by name, phone or email."),
    op("get_customer", "GET", "/api/customers/{customer_id}", "customers",
       "One customer's details with their orders and purchase history."),
    op("create_customer", "POST", "/api/customers", "customers", "Add a customer.", "write"),
    op("update_customer", "PATCH", "/api/customers/{customer_id}", "customers",
       "Change a customer's name, phone, email, address or notes. Only send the fields to change.", "write"),
    op("archive_customer", "POST", "/api/customers/{customer_id}/archive", "customers", "Archive a customer.", "destructive"),

    # --- Enquiries ---------------------------------------------------------------
    op("list_enquiries", "GET", "/api/enquiries", "enquiries",
       "Search or list enquiries (quotes) by status (OPEN, CONVERTED, LOST), customer or product."),
    op("get_enquiry", "GET", "/api/enquiries/{enquiry_id}", "enquiries", "One enquiry with its lines and totals."),
    op("create_enquiry", "POST", "/api/enquiries", "enquiries",
       "Record an enquiry (a quote) for a customer: products, quantities and discount percent per line. Prices start at MRP.", "write"),
    op("update_enquiry", "PATCH", "/api/enquiries/{enquiry_id}", "enquiries",
       "Change an open enquiry's lines or notes. Send the full list of lines when changing lines.", "write"),
    op("convert_enquiry", "POST", "/api/enquiries/{enquiry_id}/convert", "enquiries",
       "Turn an open enquiry into a sales order at the quoted prices.", "financial"),
    op("mark_enquiry_lost", "POST", "/api/enquiries/{enquiry_id}/mark-lost", "enquiries",
       "Mark an open enquiry as lost, with a reason.", "destructive"),

    # --- Sales orders and fulfilment ----------------------------------------------
    op("list_orders", "GET", "/api/orders", "sales",
       "Search or list sales orders by status (PENDING = open, PARTIALLY_FULFILLED, FULFILLED, CANCELLED), customer or product."),
    op("get_order", "GET", "/api/orders/{order_id}", "sales",
       "One sales order: lines, what is delivered, ready, on order and short, financials (revenue, cost, profit) and its enquiry."),
    op("order_fulfilment", "GET", "/api/orders/{order_id}/fulfilment", "sales",
       "What can be delivered on an order now, line by line."),
    op("create_order", "POST", "/api/orders", "sales",
       "Place a sales order for a customer: products, quantities and discount percent per line. Free stock is reserved at once; anything not in stock waits as short.", "financial"),
    op("record_delivery", "POST", "/api/orders/{order_id}/deliveries", "sales",
       "Record goods handed to the customer on an order (quantities per order line). Stock leaves the warehouse.", "financial"),
    op("cancel_order", "POST", "/api/orders/{order_id}/cancel", "sales",
       "Cancel a whole sales order that has nothing delivered. Reserved stock is released.", "destructive"),
    op("cancel_rest_of_order", "POST", "/api/orders/{order_id}/cancel-remaining", "sales",
       "Cancel whatever is still undelivered on an order, keeping what was delivered.", "destructive"),
    op("list_deliveries", "GET", "/api/deliveries", "sales", "List deliveries made to customers."),
    op("fulfilment_board", "GET", "/api/inventory/pending-commitments", "sales",
       "Everything customers are still owed, line by line: ready to deliver, on order, short; with totals by customer."),

    # --- Purchasing ---------------------------------------------------------------
    op("list_suppliers", "GET", "/api/suppliers", "purchasing", "Search or list suppliers."),
    op("get_supplier", "GET", "/api/suppliers/{supplier_id}", "purchasing", "One supplier with their purchase orders."),
    op("create_supplier", "POST", "/api/suppliers", "purchasing", "Add a supplier.", "write"),
    op("update_supplier", "PATCH", "/api/suppliers/{supplier_id}", "purchasing",
       "Change a supplier's details. Only send the fields to change.", "write"),
    op("archive_supplier", "POST", "/api/suppliers/{supplier_id}/archive", "purchasing", "Archive a supplier.", "destructive"),
    op("list_purchase_orders", "GET", "/api/purchase-orders", "purchasing",
       "Search or list purchase orders by status (DRAFT, ORDERED, PARTIALLY_RECEIVED, RECEIVED, CANCELLED; comma-separated for several), supplier or product."),
    op("get_purchase_order", "GET", "/api/purchase-orders/{po_id}", "purchasing", "One purchase order with lines and receipts."),
    op("create_purchase_order", "POST", "/api/purchase-orders", "purchasing",
       "Raise a purchase order with a supplier: products, quantities, unit costs. confirm=false saves a draft; confirm=true places it, and it must then settle customers who are short (settlements, or null to settle oldest first).", "financial"),
    op("update_purchase_order", "PATCH", "/api/purchase-orders/{po_id}", "purchasing",
       "Change a draft purchase order. Send the full list of lines when changing lines.", "financial"),
    op("place_purchase_order", "POST", "/api/purchase-orders/{po_id}/confirm", "purchasing",
       "Place a draft purchase order with the supplier.", "financial"),
    op("settle_purchase_order", "POST", "/api/purchase-orders/{po_id}/settle", "purchasing",
       "Give a placed purchase order's unpromised quantity to customers who are short.", "financial"),
    op("cancel_purchase_order", "POST", "/api/purchase-orders/{po_id}/cancel", "purchasing",
       "Cancel a purchase order that has nothing received.", "destructive"),
    op("list_goods_receipts", "GET", "/api/goods-receipts", "purchasing", "List goods received against purchase orders."),
    op("get_goods_receipt", "GET", "/api/goods-receipts/{receipt_id}", "purchasing", "One goods receipt."),
    op("preview_goods_receipt", "POST", "/api/goods-receipts/preview", "purchasing",
       "Check a goods receipt before recording it: what each quantity would do and who would get it. Changes nothing."),
    op("record_goods_receipt", "POST", "/api/goods-receipts", "purchasing",
       "Record goods arriving against a purchase order. Stock rises and waiting customers get theirs.", "financial"),

    # --- Follow-ups -----------------------------------------------------------------
    op("list_follow_ups", "GET", "/api/tasks", "follow_ups",
       "List follow-ups (tasks) by status (OPEN, DONE, CANCELLED), due (overdue, today, week), assignee or linked record."),
    op("follow_up_counts", "GET", "/api/tasks/counts", "follow_ups", "How many follow-ups are open, overdue and due today."),
    op("list_users", "GET", "/api/tasks/assignees", "follow_ups", "Everyone a follow-up can be assigned to."),
    op("create_follow_up", "POST", "/api/tasks", "follow_ups",
       "Create a follow-up: title, due date (YYYY-MM-DD), priority, assignee, and the customer/enquiry/order/supplier/purchase order it is about.", "write"),
    op("update_follow_up", "PATCH", "/api/tasks/{task_id}", "follow_ups",
       "Change a follow-up: reschedule, reassign, set status DONE or CANCELLED. Only send the fields to change.", "write"),

    # --- Messages and Tally -----------------------------------------------------------
    op("list_inbound_messages", "GET", "/api/integrations/messages", "integrations",
       "WhatsApp and email messages received, and what the enquiry reader did with each."),
    op("list_tally_syncs", "GET", "/api/integrations/tally/syncs", "integrations", "Documents sent to Tally and their status."),
]

BY_NAME: Dict[str, Operation] = {operation.name: operation for operation in OPERATIONS}

#: Filled in by the executor, never by the model.
AUTOMATIC_FIELDS = {"idempotency_key"}

SUMMARY_FIELD = {
    "type": "string",
    "description": "One plain sentence for the user saying exactly what this change will do, "
                   "with names and numbers (shown on the confirmation card).",
}


# ---------------------------------------------------------------------------
# Schemas from OpenAPI
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _openapi() -> Dict[str, Any]:
    from ..main import app

    return app.openapi()


def _resolve(schema: Dict[str, Any], components: Dict[str, Any], depth: int = 0) -> Dict[str, Any]:
    """Turn an OpenAPI schema into the subset Gemini function calling accepts:
    refs inlined, nullables simplified, decimals as numbers, extras dropped."""
    if depth > 8:
        return {"type": "string"}
    schema = copy.deepcopy(schema)
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        target = _resolve(components.get(name, {"type": "string"}), components, depth + 1)
        if schema.get("description"):
            target["description"] = schema["description"]
        return target
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [option for option in schema[key] if option.get("type") != "null"]
            types = {option.get("type") for option in options}
            if types == {"number", "string"} or types == {"integer", "string"}:
                chosen = {"type": "number"}
            elif options:
                chosen = _resolve(options[0], components, depth + 1)
            else:
                chosen = {"type": "string"}
            for extra in ("description", "title", "default"):
                if extra in schema and extra not in chosen:
                    chosen[extra] = schema[extra]
            schema = chosen
            break
    if "allOf" in schema and len(schema["allOf"]) == 1:
        merged = _resolve(schema["allOf"][0], components, depth + 1)
        if schema.get("description"):
            merged["description"] = schema["description"]
        schema = merged

    out: Dict[str, Any] = {}
    kind = schema.get("type")
    if kind is None:
        kind = "object" if "properties" in schema else "string"
    out["type"] = kind
    notes: List[str] = []
    description = schema.get("description") or schema.get("title")
    fmt = schema.get("format")
    if fmt == "uuid":
        notes.append("an id (UUID) from a list or search tool")
    elif fmt == "date":
        notes.append("date YYYY-MM-DD")
    elif fmt == "date-time":
        notes.append("ISO date-time")
    if "default" in schema and schema["default"] not in (None, "", [], {}):
        notes.append("default {}".format(schema["default"]))
    if "pattern" in schema:
        notes.append("format {}".format(schema["pattern"]))
    for bound in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength"):
        if bound in schema:
            notes.append("{} {}".format(bound, schema[bound]))
    text = "; ".join(filter(None, [description] + notes))
    if text:
        out["description"] = text[:400]
    if "enum" in schema:
        out["enum"] = [str(value) for value in schema["enum"]]
        out["type"] = "string"
    if kind == "array":
        out["items"] = _resolve(schema.get("items", {"type": "string"}), components, depth + 1)
    if kind == "object":
        properties = schema.get("properties") or {}
        out["properties"] = {key: _resolve(value, components, depth + 1) for key, value in properties.items()}
        required = [key for key in schema.get("required", []) if key in properties]
        if required:
            out["required"] = required
        if not properties:
            out["type"] = "string"
            out["description"] = (out.get("description", "") + " (JSON object as text)").strip()
    if kind == "integer":
        out["type"] = "integer"
    return out


@dataclass
class Signature:
    """How a tool's flat arguments map back onto the HTTP request."""

    schema: Dict[str, Any]
    path_params: List[str] = field(default_factory=list)
    query_params: List[str] = field(default_factory=list)
    body_params: List[str] = field(default_factory=list)
    body_required: bool = False


@lru_cache(maxsize=None)
def signature(name: str) -> Signature:
    operation = BY_NAME[name]
    spec = _openapi()
    components = spec.get("components", {}).get("schemas", {})
    entry = spec["paths"][operation.path][operation.method.lower()]
    properties: Dict[str, Any] = {}
    required: List[str] = []
    sig = Signature(schema={})
    for parameter in entry.get("parameters", []):
        if parameter.get("in") not in ("path", "query"):
            continue
        prop = _resolve(parameter.get("schema", {"type": "string"}), components)
        own = parameter.get("description")
        if own and own not in (prop.get("description") or ""):
            prop["description"] = (own + ("; " + prop["description"] if prop.get("description") else ""))[:400]
        properties[parameter["name"]] = prop
        if parameter.get("required"):
            required.append(parameter["name"])
        (sig.path_params if parameter["in"] == "path" else sig.query_params).append(parameter["name"])
    body = entry.get("requestBody")
    if body:
        content = body.get("content", {}).get("application/json", {})
        body_schema = _resolve(content.get("schema", {}), components)
        sig.body_required = bool(body.get("required"))
        for key, value in (body_schema.get("properties") or {}).items():
            if key in properties or key in AUTOMATIC_FIELDS:
                continue
            properties[key] = value
            sig.body_params.append(key)
        if sig.body_required:
            required.extend(key for key in body_schema.get("required", []) if key in sig.body_params)
    if operation.mutates:
        properties["summary"] = SUMMARY_FIELD
        required.append("summary")
    sig.schema = {"type": "object", "properties": properties}
    if required:
        sig.schema["required"] = sorted(set(required))
    return sig


@lru_cache(maxsize=None)
def _takes_idempotency_key(name: str) -> bool:
    operation = BY_NAME[name]
    spec = _openapi()
    entry = spec["paths"][operation.path][operation.method.lower()]
    schema = entry.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
    ref = schema.get("$ref", "").rsplit("/", 1)[-1]
    target = spec.get("components", {}).get("schemas", {}).get(ref, schema)
    return "idempotency_key" in (target.get("properties") or {})


def split_arguments(name: str, args: Dict[str, Any]) -> Tuple[str, Dict[str, Any], Optional[Dict[str, Any]]]:
    """Flat tool arguments -> (path, query, body)."""
    operation = BY_NAME[name]
    sig = signature(name)
    path = operation.path
    for key in sig.path_params:
        value = args.get(key)
        if value in (None, ""):
            raise ValueError("{} is required.".format(key))
        path = path.replace("{" + key + "}", str(value))
    query = {key: args[key] for key in sig.query_params if args.get(key) not in (None, "")}
    body = {key: args[key] for key in sig.body_params if key in args}
    if not body and not sig.body_required:
        body = None
    if body is not None and _takes_idempotency_key(name):
        import uuid

        body["idempotency_key"] = str(uuid.uuid4())
    return path, query, body
