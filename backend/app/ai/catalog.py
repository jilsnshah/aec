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
       "Post a stock count (counted_quantity per product, as_count true) or an adjustment (quantity_change with a reason: damaged, lost, expired, found, sample, correction). warehouse_id per line counts or adjusts one warehouse.", "financial"),
    op("list_transporters", "GET", "/api/transporters", "purchasing",
       "Transporters (lorry owners, transport companies, brokers, tempos) with vehicles, rate card size, trips and what we owe them; search by name, area or vehicle number."),
    op("get_transporter", "GET", "/api/transporters/{transporter_id}", "purchasing", "One transporter: contacts, vehicles, rate card, trips, bookings and balance."),
    op("create_transporter", "POST", "/api/transporters", "purchasing",
       "Add a transporter: name, kind (company, fleet_owner, broker, tempo, courier, own_fleet), phone, email, address, gstin, pan, tally_ledger_name, service_areas, payment_terms_days, booking_channel (whatsapp, call, either), vehicles [{number, vehicle_type, capacity_kg, driver_name, driver_phone}], rates [{from_place, to_place, vehicle_type, basis (trip, km, tonne, quintal, kg, unit, hour), rate, min_charge}].", "write"),
    op("update_transporter", "PATCH", "/api/transporters/{transporter_id}", "purchasing", "Change a transporter's details, rating or close them (is_active false).", "write"),
    op("add_transporter_vehicle", "POST", "/api/transporters/{transporter_id}/vehicles", "purchasing", "Add a vehicle to a transporter.", "write"),
    op("add_transporter_rate", "POST", "/api/transporters/{transporter_id}/rates", "purchasing", "Add a rate card line to a transporter.", "write"),
    op("estimate_freight", "GET", "/api/transporters/estimate", "purchasing",
       "Freight for a trip from every matching rate card, cheapest first: from_place, to_place, vehicle_type, weight_kg, units, km."),
    op("transporter_statement", "GET", "/api/transporters/{transporter_id}/statement", "finance", "Freight bills and payments to a transporter with the balance."),
    op("list_transport_bookings", "GET", "/api/transport-bookings", "purchasing", "Vehicle bookings with transporters (draft, requested, confirmed, declined, done)."),
    op("book_transport", "POST", "/api/transport-bookings", "purchasing",
       "Book a vehicle: transporter_id, reference_type (sales_order, purchase_order, stock_transfer) and reference_id fill route, load and weight; or from_place, to_place, needed_at, vehicle_type, load.", "write"),
    op("update_transport_booking", "PATCH", "/api/transport-bookings/{booking_id}", "purchasing",
       "Move a booking on: status requested/confirmed/declined/done/cancelled, agreed_amount, vehicle_number, driver_phone.", "write"),
    op("list_landed_costs", "GET", "/api/landed-costs", "purchasing", "Freight and other charges added to goods receipts, with how much went on stock and on goods already sold."),
    op("add_landed_cost", "POST", "/api/goods-receipts/{receipt_id}/landed-costs", "purchasing",
       "Add freight, unloading, insurance, octroi or other charges to a goods receipt (charges [{kind, amount, transporter_id, bill_number}], method quantity/value/weight); they raise the goods' cost.", "financial"),
    op("returnable_receipt_lines", "GET", "/api/goods-receipts/{receipt_id}/returnable", "purchasing", "A goods receipt's lines with what can still be returned to the supplier."),
    op("list_purchase_returns", "GET", "/api/purchase-returns", "purchasing", "Goods sent back to suppliers (debit notes)."),
    op("record_purchase_return", "POST", "/api/purchase-returns", "purchasing",
       "Send goods back to a supplier: goods_receipt_id, lines [{goods_receipt_item_id, quantity}], reason (damaged, quality, wrong_item, excess, expired, other), replace (supplier sends again). Raises a debit note.", "financial"),
    op("list_rate_contracts", "GET", "/api/rate-contracts", "purchasing", "Rate contracts with suppliers and customers: status, dates, rates and quantity used against the agreed quantity."),
    op("create_rate_contract", "POST", "/api/rate-contracts", "purchasing",
       "Agree rates for a period with a supplier (supplier_id) or customer (customer_id): title, valid_from, valid_until, items [{product_id, rate or discount_percent, unit, min_quantity, committed_quantity}].", "financial"),
    op("update_rate_contract", "PATCH", "/api/rate-contracts/{contract_id}", "purchasing", "Change a rate contract's dates, terms or lines.", "financial"),
    op("list_warehouses", "GET", "/api/warehouses", "inventory",
       "Warehouses (godowns, yards, shops, site stores, and 'In transit') with products, units and value held; which is the default."),
    op("warehouse_stock", "GET", "/api/warehouses/stock", "inventory",
       "Quantity, value and average cost per product per warehouse; filter by warehouse_id or product_id. Use to say where stock is."),
    op("create_warehouse", "POST", "/api/warehouses", "inventory", "Add a warehouse: name, kind (godown, yard, shop, site), address, contact, Tally godown name.", "write"),
    op("update_warehouse", "PUT", "/api/warehouses/{warehouse_id}", "inventory", "Change a warehouse, make it the default (is_default) or close it (is_active false, only when empty).", "write"),
    op("list_stock_transfers", "GET", "/api/stock-transfers", "inventory", "Transfers between warehouses (draft, in_transit, received, cancelled) with goods value and transfer costs."),
    op("get_stock_transfer", "GET", "/api/stock-transfers/{transfer_id}", "inventory", "One transfer: lines, quantities sent and received, costs and how they were spread, cost per unit before and after."),
    op("create_stock_transfer", "POST", "/api/stock-transfers", "inventory",
       "Move stock between warehouses: from_warehouse_id (default warehouse if omitted), to_warehouse_id, items [{product_id, quantity, unit}], costs [{kind: freight/loading/unloading/toll/insurance/other, amount, paid_to}], cost_method (quantity, value, weight), vehicle, transporter; dispatch true sends it now.", "financial"),
    op("update_stock_transfer", "PUT", "/api/stock-transfers/{transfer_id}", "inventory", "Change a draft transfer; on the road only costs, method and notes.", "write"),
    op("dispatch_stock_transfer", "POST", "/api/stock-transfers/{transfer_id}/dispatch", "inventory", "Send a draft transfer: goods leave the source and are in transit.", "financial"),
    op("receive_stock_transfer", "POST", "/api/stock-transfers/{transfer_id}/receive", "inventory",
       "Receive a transfer: lines [{item_id, quantity_received}] (omit when all arrived); costs are added to the goods' cost, shortages written off as lost in transit.", "financial"),
    op("cancel_stock_transfer", "POST", "/api/stock-transfers/{transfer_id}/cancel", "inventory", "Drop a draft, or bring goods in transit back to the source at their original cost.", "financial"),
    op("returnable_lines", "GET", "/api/orders/{order_id}/returnable", "sales",
       "An order's lines with delivered, already returned and still returnable quantities."),
    op("record_sales_return", "POST", "/api/orders/{order_id}/returns", "sales",
       "Record goods a customer sent back (credit note): reason, lines with order_item_id, quantity and restock (false if damaged). Credits their account.", "financial"),
    op("check_order_controls", "POST", "/api/controls/check", "sales",
       "Which business controls (credit limit, overdue, discount, margin, below cost) a draft order would trip, and whether they block it."),
    op("audit_log", "GET", "/api/audit", "insights", "Audit log: control overrides, stock adjustments, returns and voided payments, newest first."),
    op("payment_reminders", "GET", "/api/finance/reminders", "finance",
       "Customers to remind about overdue invoices with reminder level (friendly, firm, final), a ready message and when last reminded."),
    op("mark_reminder_sent", "POST", "/api/finance/reminders/{customer_id}/sent", "finance",
       "Record that a payment reminder was sent (channel whatsapp, call, email or visit) and plan a follow-up.", "write"),
    op("resolve_prices", "POST", "/api/price-lists/resolve", "sales",
       "The price a customer gets per product and quantity (best of their own prices, their discount and their groups' prices), as discount_percent off MRP. Use before drafting orders or quotes."),
    op("order_returns", "GET", "/api/orders/{order_id}/returns", "sales", "Returns (credit notes) recorded on an order."),
    op("update_order_controls", "PUT", "/api/controls/settings", "sales",
       "Change order controls: credit_check (off, warn, block), block_on_overdue, overdue_grace_days, max_discount_percent, min_margin_percent, block_below_cost.", "financial"),
    op("document_link", "GET", "/api/documents/{kind}/{record_id}", "sales",
       "Link to a printable PDF: kind quotation (enquiry id) or invoice (order id). Give the url to the user as a markdown link."),
    op("get_follow_up", "GET", "/api/tasks/{task_id}", "tasks", "One follow-up task."),
    op("stock_in_allocations", "GET", "/api/stock-receipts/{receipt_id}/allocations", "inventory", "Which customers got the stock from a stock-in receipt."),
    op("retry_tally_sync", "POST", "/api/integrations/tally/syncs/{sync_id}/retry", "sales", "Retry sending a failed voucher to Tally.", "write"),
    op("retry_inbound_message", "POST", "/api/integrations/messages/{message_id}/retry", "enquiries", "Re-read a WhatsApp or email message that failed to become an enquiry.", "write"),
    op("party_profile", "GET", "/api/parties/{kind}/{party_id}/profile", "customers",
       "A customer's or supplier's full details (kind customer or supplier): GSTIN, PAN, contacts, all phone numbers and emails, billing address and delivery sites with their ids."),
    op("add_party_contact", "POST", "/api/parties/{kind}/{party_id}/contacts", "customers", "Add a person (name, role) at a customer or supplier.", "write"),
    op("update_party_contact", "PATCH", "/api/parties/{kind}/{party_id}/contacts/{contact_id}", "customers", "Change or remove (is_active false) a contact person.", "write"),
    op("add_party_number_or_email", "POST", "/api/parties/{kind}/{party_id}/points", "customers",
       "Add a phone number or email (kind phone or email) to a customer or supplier, optionally for one contact. Fails if it already belongs to someone else.", "write"),
    op("update_party_number_or_email", "PATCH", "/api/parties/{kind}/{party_id}/points/{point_id}", "customers", "Change, make primary or remove (is_active false) a phone number or email.", "write"),
    op("add_party_address", "POST", "/api/parties/{kind}/{party_id}/addresses", "customers",
       "Add a billing address, office, warehouse or delivery site (kind site, with a label like the project name).", "write"),
    op("update_party_address", "PATCH", "/api/parties/{kind}/{party_id}/addresses/{address_id}", "customers", "Change or remove (is_active false) an address or site.", "write"),
    op("find_party_duplicates", "GET", "/api/parties/{kind}/duplicates", "customers",
       "Before creating a customer or supplier: existing records with the same phone, email or GSTIN (blocking) or a similar name."),
    op("lookup_party", "GET", "/api/parties/lookup", "customers", "Which customer or supplier a phone number or email belongs to."),
    op("merge_parties", "POST", "/api/parties/{kind}/{party_id}/merge", "customers",
       "Merge a duplicate (merge_id) into this customer or supplier: everything moves here and the duplicate is archived.", "destructive"),
    op("product_names", "GET", "/api/products/{product_id}/names", "inventory", "A product's other names, barcodes, supplier codes and units."),
    op("add_product_alias", "POST", "/api/products/{product_id}/aliases", "inventory",
       "Add another name customers use (kind alias), a barcode, or a supplier item code (kind supplier_code with supplier_id).", "write"),
    op("add_product_unit", "POST", "/api/products/{product_id}/units", "inventory", "Add a unit (e.g. tonne = 20 bags: name tonne, factor 20).", "write"),
    op("match_products", "GET", "/api/products/match", "inventory",
       "Find products from free text as customers write it (other names, barcodes, supplier codes). Prefer this over list_products when reading messages."),
    op("assign_enquiry_customer", "POST", "/api/enquiries/{enquiry_id}/customer", "enquiries",
       "Say who an enquiry from an unknown sender is from: customer_id of an existing customer (search first), or new_customer details. Links the sender's number/email to that customer.", "write"),
    op("customer_group_fields", "GET", "/api/customer-groups/fields", "customers", "What group rules can test (orders, spend, years with us, overdue, segment, city...)."),
    op("list_customer_groups", "GET", "/api/customer-groups", "customers", "Customer groups (picked by hand and/or by rules) with their members' discount, number of product prices and member count."),
    op("get_customer_group", "GET", "/api/customer-groups/{group_id}", "customers", "One group with its members and its product prices."),
    op("preview_customer_group", "POST", "/api/customer-groups/preview", "customers", "Who a set of rules would put in a group, without saving."),
    op("create_customer_group", "POST", "/api/customer-groups", "customers",
       "Create a customer group: name; rules [{field, op, value}] with match all/any, or no rules for a hand-picked group; members' discount_percent off MRP; items (product prices: product_id, min_quantity, price or discount_percent). Add members by hand with set_customer_group_member.", "write"),
    op("update_customer_group", "PUT", "/api/customer-groups/{group_id}", "customers", "Change a group's name, rules, discount_percent or items (send ALL product prices; they replace the old ones).", "write"),
    op("set_customer_group_member", "PUT", "/api/customer-groups/{group_id}/members/{customer_id}", "customers",
       "Add a customer to a group by hand (source manual), keep them out (excluded), or undo (null).", "write"),
    op("customer_pricing", "GET", "/api/customers/{customer_id}/pricing", "customers", "A customer's own discount, own product prices and the groups they are in (by rules or by hand)."),
    op("set_customer_pricing", "PUT", "/api/customers/{customer_id}/pricing", "customers",
       "Set a customer's flat discount_percent and/or own product prices (items replace them).", "write"),
    op("apply_best_prices_to_enquiry", "POST", "/api/enquiries/{enquiry_id}/apply-prices", "enquiries",
       "Set an open enquiry's lines to the customer's best prices (own, discount, list, groups) and report the changes.", "write"),
    op("customer_enquiry_link", "GET", "/api/customers/{customer_id}/enquiry-link", "customers", "A customer's own enquiry page path (/e/...), if on. Share as the app's address + path."),
    op("set_customer_enquiry_link", "POST", "/api/customers/{customer_id}/enquiry-link", "customers",
       "Create (or replace) a customer's own enquiry page link, or switch it off with enabled false.", "write"),
    op("order_confirmation_text", "GET", "/api/orders/{order_id}/confirmation", "sales", "The order confirmation message text for WhatsApp."),
    op("send_order_confirmation", "POST", "/api/orders/{order_id}/send-confirmation", "sales", "Send the order confirmation to the customer on WhatsApp now.", "write"),
    op("automation_library", "GET", "/api/automation/library", "insights", "Step types the automation flows can use and what each supports."),
    op("get_automation_flow", "GET", "/api/automation/flows/{key}", "insights", "The sales or purchase automation flow: steps with who does them, modes, limits, AI settings."),
    op("automation_approvals", "GET", "/api/automation/approvals", "insights", "Replies and orders the agents are holding for a person to approve."),
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
