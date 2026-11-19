# AEC Desk — from business dashboard to business operating system

## 1. The business, as the data describes it

A trading business (building materials, hardware, packaging) that buys by
quantity from suppliers and sells by quantity to builders, retailers and
contractors.

**How goods flow.** Supplier → purchase order → goods receipt (or ad-hoc stock
in) → warehouse (FIFO cost layers) → reserved for a customer's order →
delivered (stock leaves, revenue and cost of goods are recognised).

**How sales happen.** Enquiry (WhatsApp, email or typed in) → quote at MRP with
negotiated discounts → won (converted to an order) or lost → order reserves
free stock, the rest waits as "short" → a purchase settles the short customers
→ deliveries, often partial, over days or weeks.

**What the owner decides every day.** What to buy, how much and from whom;
whom to deliver to first; which quotes to chase; whom to chase for money;
which stock is not moving and must be cleared; whether this month is better
than the last and why.

**What the data already holds but nobody uses.** Every receipt's date and cost
(stock age, turnover, holding period); every order line's price and discount
(discount leakage, margin by product and customer); enquiry outcomes and
reasons (conversion by source and by product); delivery and receipt dates
(lead times, how long customers wait); open short quantities (sales at risk).

**What was missing entirely.**

| Gap | Why it matters |
| --- | --- |
| Money owed and money due | A trading business lives on credit. There were no payments, no receivables, no payables, no credit terms or limits. |
| Product grouping and reorder settings | No category, minimum stock, preferred supplier or lead time — so no category analysis and no lead-time-aware reorder point. |
| Targets | No way to see actual against plan. |
| Preferences and saved views | Every screen reset on every visit; no personal dashboard. |
| Connected history | A customer's or product's story was spread over five screens. |

## 2. Module audit

| Module | Before | Built now |
| --- | --- | --- |
| Home | Fixed board, last 30 days | Command centre: period switch, target progress, receivables and payables, cash collected, every figure links to the filtered detail; widgets can be hidden and re-ordered per user; AI briefing on demand |
| Products / inventory | List and stock history | Category, minimum stock, preferred supplier, lead time; filters by category, health flag and supplier; sorting; multi-select; "buy selected" opens a purchase order pre-filled with the recommended quantities; CSV export; product intelligence card (demand trend, turnover, holding period, days to clear, open enquiry demand, recommendation) |
| Stock health | Ageing table | Reorder point = sales during lead time + minimum stock; "order by" date; days to clear; liquidation priority (value × age); demand trend (rising / falling); sales at risk from shortages; clickable age buckets |
| Sales analytics | Product, customer, month | Explorer: any measure (booked, delivered, profit, quantity, orders, discount) by product, category, customer, month, week, weekday or day, any date range, filters, previous-period comparison, chart ↔ table, saved views, export. Product intelligence: growth, Pareto (ABC), margin quadrant, enquiry-to-order conversion per product. Weekday × week heatmap. |
| Customers | Contact and orders | Statement (deliveries, payments, running balance), receivables ageing, credit terms and limit, payment recording, segment (champion, loyal, at risk, dormant, new), purchase frequency, lifetime value estimate (labelled), activity timeline |
| Suppliers | Contact and purchase orders | Payables and payments, terms and lead time, reliability |
| Enquiries | List and convert | Priority score with reasons, call and WhatsApp links, one-click follow-up |
| Finance (new) | — | Receivables and payables ageing, overdue invoices, record money in and out, collections list |
| Assistant | 60 tools | Every new route is a tool automatically: payments, statements, receivables, explorer, product and customer intelligence, targets |

## 3. Principles

- **Every insight leads to an action, every action carries its context.**
  Alerts link to the record; age buckets filter the table; reorder rows open a
  pre-filled purchase order; KPI cards open the filtered list.
- **No invented numbers.** Every figure is computed from stored records.
  Estimates (lifetime value, days to clear, order-by dates) are labelled as
  estimates and say what they assume. Where history is too short (forecasting,
  bought-together), the screen says so instead of guessing.
- **One source of truth.** The screens and the assistant call the same
  endpoints.

## 4. Roadmap (priority order)

1. Data foundations: product, customer and supplier fields; payments; targets;
   preferences and saved views. *(migration, services, API, tests)*
2. Finance: receivables, payables, statements, ageing, overdue alerts.
3. Analytics engine: inventory intelligence, product and customer
   intelligence, explorer, heatmap.
4. Screens: command-centre Home, Finance, Products with filters and bulk buy,
   customer and supplier money tabs, Insights explorer, enquiry priority.
5. Productivity: command palette actions and recently viewed records,
   contextual "ask AI" throughout.
6. Assistant: tools for all of the above; prompt distinguishes facts from
   estimates.
7. Regression: backend suite, browser end-to-end, screenshots.

Deliberately not built: salesperson performance (the data has no
salesperson), category-level targets (business-level targets first),
statistical forecasting (months of history are needed; the screens show
trend direction and say when data is insufficient).

## 5. Status (19 November 2026)

Built and tested on `frontend-v2`: steps 1–7 above. Backend tests cover
payments and open-item matching, ageing with terms, statements, voids,
credit-limit alerts, product settings driving reorder points, the explorer,
heatmap, product intelligence, segments, targets, preferences and saved
views. Browser end-to-end runs cover bulk buy into a pre-filled purchase
order, the product intelligence card, recording a payment and seeing
receivables fall, the customer statement, Home customisation persisting,
explorer grouping and drill-down, and palette actions — plus the earlier
suites, unchanged.

Next candidates: invoices with tax from Tally numbers, partial payment
allocation to a chosen invoice, category-level targets, scheduled briefings
by WhatsApp/email, demand forecasting once 6+ months of history exist.

## 6. Second pass: every existing screen upgraded (19 November 2026)

What leading ERPs put on every record, researched before building:
Microsoft Dynamics 365 Business Central (Copilot sales-line suggestions, the
Sales Order Agent drafting orders from customer emails, credit checks at order
entry), Odoo 19 (next-action suggestions, AI reorder timing and draft purchase
orders), Oracle NetSuite (excessive-discount flags on draft orders, per-line
pricing explanations, vendor scoring on price, quality and delivery) and Indian
distribution software (Marg, BUSY, Zoho, Vyapar: low-stock alerts, approvals,
audit trail).

| Screen | Added |
| --- | --- |
| Every list | Quick-filter chips with live counts and icons (a dot marks chips that need action); a sky "what needs attention" panel computed from the data, each line opening the filtered list; one-tap questions for the assistant; a "?" guide explaining the page |
| Sales orders | Paid / part paid / overdue badge per order (open-item matching against deliveries); "ready" marker; status stepper (placed → stock ready → delivered → paid); Paid figure; activity timeline; repeat order; WhatsApp status update; Ask AI |
| New order | Live order check while typing (credit limit with undelivered orders, overdue money, price below cost, thin margin, discount far above the usual, price lower than this customer paid last time, stock shortfall); per-line margin, last price paid and free stock; "draft from a message" hands a pasted WhatsApp order to the assistant |
| Customers | Segment badges and chips (champion, loyal, at risk, dormant, new), owes / overdue per row; 360 overview: lifetime value and rank, average order, buying rhythm with "later than usual" warning, average discount, quote win rate, credit-used gauge, spend by month, what they buy; timeline; "next best action" |
| Products | Health chips (to reorder, short, running out, demand rising or falling, slow, dead); Prices tab: margin, cost from each supplier with the cheapest first, recent selling prices with discounts, top buyers; timeline |
| Purchase orders | Chips (drafts to place, arriving, late); late badge; buying suggestions grouped by supplier opening a pre-filled order; supplier WhatsApp chase; Ask AI price review |
| Suppliers | Score (fill rate and on-time) on every row; scorecard tab: lead time, gauges, late orders, each product's last price against the cheapest supplier; timeline |
| Enquiries | Chips (hot, going cold, from messages, won, lost), sorted by priority; pipeline panel (open value, win rate, days to win, top lost reason); priority panel with reasons; the order check on the quoted prices; "draft quote reply" and "what discount can I give" |
| Goods receipts | "Scan bill": a photo or PDF of the supplier bill goes to the assistant, which matches it to the purchase order and lists differences before proposing the receipt |
| Fulfilment | Today panel: units ready by customer, longest wait, what is short; plan-deliveries question |

New endpoints (all read-only, all assistant tools): `GET /api/records/timeline`,
`GET /api/records/customers/{id}/profile`, `GET /api/records/products/{id}/prices`,
`POST /api/records/order-check`, `GET /api/records/order-payments`,
`GET /api/records/suppliers/{id}/scorecard`, `GET /api/records/purchase-suggestions`.
