# AEC Business Management

A business management system covering **enquiries, sales, purchasing,
inventory and fulfilment**, from a customer asking for a price to the goods
leaving the building.

- **Phase 1** — product and customer masters, multi-product sales orders,
  inventory with compulsory settlement of pending orders, FIFO costing and
  profit.
- **Phase 2** — customer enquiries: negotiate a discount per product, then
  close the deal and convert it into a real sales order.
- **Phase 3** — suppliers, purchase orders, partial goods receipts, compulsory
  reservation of incoming stock against waiting orders, and customer delivery
  with a pending-commitments view.

It is built around one non-negotiable rule:

> When stock is received, outstanding customer orders are settled **before** any
> of that stock becomes freely available.

- **Backend** — Python 3.9+, FastAPI, SQLAlchemy 2.x, Pydantic v2, Alembic and
  **PostgreSQL**. PostgreSQL is required, not merely preferred: the inventory
  rules depend on `SELECT ... FOR UPDATE` row locking, so the application
  refuses to start against anything else rather than quietly losing that
  guarantee.
- **Frontend** — React 18, Vite, TypeScript, with its own design system
  (light and dark themes, no UI framework) and lucide icons.
- **Tests** — pytest, 195 tests covering the business rules, reservation and
  delivery, purchasing, pricing, costing, the API, migrations and concurrency.

---

## The stock figures

### What the screens show

Stock is **bought less sold**. A purchase order adds its units the moment it
is confirmed; a sales order takes its units the moment it is placed. Goods
arriving in or leaving the warehouse change nothing.

| On screen | Meaning | API field |
| --- | --- | --- |
| **Stock** | `physical + to receive − to deliver`. Negative means **short**: more sold than bought. | `stock` |
| **To receive** | Bought on a confirmed purchase order, not arrived yet. Drafts and cancelled orders do not count. | `on_order_quantity` |
| **To deliver** | Sold, truck not gone yet. | `pending_quantity` |

Per sales order line, *to deliver* splits three ways:

| On screen | Meaning | API field |
| --- | --- | --- |
| **Ready** | In the warehouse and set aside for this line. | `quantity_reserved` |
| **On order** | Covered by a confirmed purchase order whose goods have not arrived. | `quantity_incoming` |
| **Short** | Nothing covers it yet. Only this makes a product short. | `quantity_unallocated` |

### Settlement when a purchase is made

Because a purchase counts as stock at once, it settles at once:

- **Confirming a purchase order** must settle customers already short: per
  product exactly `min(quantity bought, quantity short)`. **The user chooses**
  who gets it and how much each (`settlements` on create or confirm; every
  amount starts at zero in the interface, with an optional *Fill oldest first*
  shortcut). Only an API call that omits `settlements` altogether falls back to
  oldest order first.
- **Placing a sales order** takes what is free in the warehouse first, then
  what is free on purchase orders still on the way.
- **Receiving goods** gives them first to the customers that purchase was
  covering (their *on order* becomes *ready*), then to anyone short; the rest
  is free. Stock does not change, unless more arrives than was ordered.
- **Cancelling a purchase order** takes its stock back; whoever it covered
  becomes short again.
- **Cancelling a sales order** frees its cover on the purchase order. Nothing
  is handed on automatically: the purchase order shows **Settle** and the user
  chooses who gets it (`POST /api/purchase-orders/{id}/settle`).
- A new sales order is covered from free purchase quantity for itself only;
  it never takes another customer's cover.

The migration that introduced this settles purchase orders already open in the
same way.

### What the backend tracks

Underneath, five numbers, all different, never conflated:

| Figure | Meaning |
| --- | --- |
| **Physical stock** | Units actually on the shelf. Never negative. |
| **Reserved stock** | Of those, units already promised to a specific order. |
| **Available stock** | `physical − reserved`: what can still be sold to anyone else. |
| **Pending (owed)** | `ordered − delivered − cancelled`: what customers are still owed. |
| **Unallocated** | `pending − reserved`: owed with no stock behind it yet. |

and `net stock position = physical − pending`, which **may be negative** — an
outstanding obligation, not phantom inventory.

### Reserving is not delivering

This is the distinction Phase 3 introduced, and it matters:

* **Reserving** stock promises it to an order. It moves nothing. The units stay
  on the shelf and in the cost layers; they simply stop being available to
  anybody else.
* **Delivering** hands the goods over. *Only* this reduces physical stock,
  writes a `CUSTOMER_DELIVERY` movement, releases the reservation, raises the
  delivered quantity and books the cost of goods.

So receiving a supplier delivery never clears a customer obligation by itself —
it only puts stock behind it. Worked example: 20 ordered with nothing in stock,
then 10 arrive → 10 reserved, 10 still unallocated, 20 still owed, available 0.
Deliver the 10 → delivered 10, owed 10, physical stock down by 10, reservation
gone.

> Phase 1 allocated by delivering immediately, so `SalesOrderItem.quantity_fulfilled`
> means *delivered* and every historical row is a real past delivery. Nothing was
> reinterpreted by the Phase 3 migration: it only added `quantity_reserved`,
> defaulted to zero, which is exactly right for orders whose allocated stock had
> already gone out.

## Costing, pricing and profit

**Every receipt records what was paid.** A stock receipt captures a purchase
price per unit and opens a **FIFO cost layer**: a batch of stock at one price.
Every unit that leaves draws from the oldest open layers, so the cost of goods
sold is the price actually paid for those particular units, not an average
guess. The system can say which purchase paid for the units a given customer
received.

> Invariant, asserted by the tests: for each product, the open cost layers sum
> to exactly its physical stock.

**Every order line is priced.** A line carries a unit price (defaulting to the
product's MRP) and a **discount percentage**, giving a net price per unit. The
order stores its subtotal, discount and total.

**Profit is recognised on delivery, not on ordering.** A line that is still
waiting on stock has order value but has earned nothing and has consumed no
cost. So, per line and per order:

```
delivered value = net price x quantity fulfilled
cost of goods   = sum of the FIFO layer draws for that line
gross profit    = delivered value - cost of goods
```

Worked example — buy 15 at 40, sell 20 at 100 less 10%:

| | |
| --- | --- |
| Order value | 20 x 90 = **1,800** (subtotal 2,000 less 200 discount) |
| Delivered now | 15 x 90 = **1,350** |
| Cost of goods | 15 x 40 = **600** |
| Gross profit | **750** (55.56% margin) |
| Still to deliver | 5 x 90 = **450**, earning nothing yet |

Then receive 10 at 50. Five settle the pending order, drawn from the new,
dearer batch: revenue +450, cost +250, profit +200. The order ends at 1,800
delivered, 850 of cost and 950 of profit — a 52.78% margin, lower than it
started, because the settling stock cost more. That drop is visible rather than
averaged away.

Stock received without a recorded price is valued at zero: honest about being
unknown rather than inventing a figure.

## The compulsory allocation rule

For a receipt of `R` units against `U` units of **unallocated** customer demand:

```
required allocation = min(R, U)
```

The allocations must sum to **exactly** that: no part of an arrival may be left
available while an order is still waiting for it. The backend recomputes `R`,
`U` and the required total from its own data on every request — a distribution
sent by the client is a proposal, never the truth, and a short or inflated one
is rejected with `422` without touching the database. If no distribution is
sent, the backend allocates FIFO (oldest order first, tie-broken by order number
and line number).

One engine applies this everywhere (`app/services/reservations.py`): stock
arriving on a purchase order, stock arriving ad hoc, and stock already on the
shelf when an order is taken all go through the same rules.

Rejected allocations change nothing: the receipt, the ledger movements, the cost
layer and every reservation are written in a single transaction.

---

## Customer enquiries (Phase 2)

An enquiry is a deal being negotiated. A customer asks for a list of products;
each line is priced from the **MRP in the product master**, and the only thing
negotiated is a **discount percentage per product**:

```
selling price per unit = MRP x (1 - discount / 100)
line total             = selling price per unit x quantity
enquiry total          = sum of line totals          (before tax)
```

Worked example: 10 of Product A at ₹1,000 less 15% is ₹8,500; 20 of Product B at
₹500 less 10% is ₹9,000; the enquiry totals ₹17,500 before tax.

Every figure is calculated by `app/services/pricing.py` on the server. An MRP or
a quoted price sent by a client is ignored — only `product_id`, `quantity` and
`discount_percent` are read. Each line stores the MRP it was opened against, so
a later change to the product's MRP cannot move an agreed price.

### Closing the deal

**Close Enquiry & Create Sales Order** calls the Phase 1 order builder inside
the enquiry's own transaction. The resulting order is an ordinary sales order:
stock is allocated, older pending orders keep their priority, and anything that
cannot be covered becomes pending quantity exactly as it would for an order
typed in directly. The order records each line's MRP snapshot, discount, agreed
unit price and line total, and links back to the enquiry it came from.

Converting is guarded three times over: the enquiry row is locked for the
duration, its status is re-read under that lock, and `sales_orders.enquiry_id`
carries a **UNIQUE** constraint. A repeat click, a retry or two concurrent
requests all end with exactly one order; the loser gets a 409 naming the order
that already exists. If anything in the conversion fails, the whole thing rolls
back and the enquiry stays OPEN — it can never be CONVERTED without an order
behind it.

**Mark as lost** closes an enquiry without creating an order or touching stock.
A converted or lost enquiry is read-only.

## Purchasing and fulfilment (Phase 3)

The flow from supplier to customer, and what each step does to stock:

| Step | Effect on stock |
| --- | --- |
| Raise or place a **purchase order** | **None.** Ordering is a promise, not an arrival. |
| Record a **goods receipt** | Physical stock rises by what arrived. `min(received, unallocated demand)` is **reserved** to waiting orders, oldest first; the rest becomes available. |
| Record a **delivery** | Physical stock falls, the reservation is released, the delivered quantity rises, the obligation shrinks and the cost of goods is booked. |

A purchase order may be received in several drops: each one updates the line's
received and remaining quantities and moves the order through
`ORDERED → PARTIALLY_RECEIVED → RECEIVED`. Receiving more than the order still
owes is rejected unless the request explicitly sets `allow_over_receipt` **and**
gives a reason for each over-received line, which is stored with it.

`POST /api/goods-receipts/preview` writes nothing and returns, per line, the
eligible demand, the FIFO proposal, the required allocation, the surplus and the
predicted stock position — which is exactly what the Goods Receipts screen shows
before anything is committed.

**Pending Fulfilment** answers the question the business actually asks: what do
we owe, to whom, and is there stock behind it? One row per outstanding order
line, oldest first, with ordered / delivered / ready / waiting / to deliver,
a per-customer roll-up, and the delivery action itself.

---

## The interface

AEC Desk is built as a desktop application, not a scrolling website. The
window never scrolls as a page: a top bar carries the modules as pills —
Home, Assistant, Insights, Fulfilment, then **Sales**, **Buying** and **Stock**
menus, Follow-ups and Settings — with search, the alerts bell, the light/dark
switch, the **New** menu and the account menu, and every module is a fixed workspace of rounded
cards. Only lists inside cards scroll. See `frontend/DESIGN.md`
for the full plan.

- **Split views** — Enquiries, Sales Orders, Customers, Purchase Orders,
  Goods Receipts, Suppliers and Products show a compact list on the left and
  the chosen record's inspector (figures, tabs, actions) on the right. The URL
  follows the selection, so links and the back button work.
- **Sheets** — every create and edit form drops from the title bar, with the
  form on the left and a live summary on the right.
- **Home** — one board that fits the window: headline figures, a gauge of
  owed stock already in hand, a gross-profit card, booked-against-delivered
  bars, recent orders with to-buy and to-receive tabs, and orders per day.
- **Fulfilment** — a board with three lanes: Ready, On order and Short. Each
  card carries its next action: Deliver, Receive or Buy.
- **Integrations** — a settings window: connections on the left (AI,
  WhatsApp, Email, Tally) and the message and Tally logs.
- **Look** — light blue, black and white, in a light and a dark theme. The
  choice is kept per computer and starts from the system setting. Status
  colours carry meaning (short is red, warnings amber, done green).
- **Keyboard** — `⌘K` / `Ctrl K` opens the command palette: go to any module,
  create any record, or find orders, purchases, customers and products by
  number or name. `Esc` closes the topmost sheet, menu or palette.
- **Deep links** — `?new=1` opens a module's create sheet (for example
  `/orders?new=1`); `/receipts?new=1&po=<id>` starts a receipt for a purchase
  order; `/fulfilment?customer=<id>` filters the board; `/stock-in?product=<id>`
  opens Stock In for a product; `/integrations/<section>` opens a settings pane.
- **Narrow windows** — the module pills move to their own row and scroll
  sideways, split views show one card at a time with a way back to the list,
  and Home and Fulfilment stack.

---

## Local setup

### Prerequisites

- Python 3.9 or newer
- Node.js 18 or newer
- PostgreSQL 14 or newer — or Docker, which the bundled compose file uses

### 1. Database

```bash
docker compose up -d db             # PostgreSQL 16 on localhost:5432
```

The container matches the credentials in `backend/.env.example`. To use a
PostgreSQL you already run, change `DATABASE_URL`. The compose file is for
development only — in production run PostgreSQL as a managed service, or with
its own secrets, backups and TLS.

### 2. Backend

```bash
cd backend

python3 -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                # adjust if you want a different database

alembic upgrade head                # create the schema
python seed.py                      # optional: demo data, all prefixed DEMO-

uvicorn app.main:app --reload --port 8000
```

The API is then on <http://localhost:8000>, with interactive documentation at
<http://localhost:8000/docs> (OpenAPI schema at `/openapi.json`).

### 3. Frontend

In a second terminal:

```bash
cd frontend

npm install
npm run dev                         # proxies /api to http://127.0.0.1:8000
```

The app is then on <http://localhost:5173>. The dev server proxies `/api` to
the backend, so the session cookie stays same-origin exactly as in production.
If the backend runs elsewhere, start the dev server with
`API_PROXY_TARGET=http://127.0.0.1:<port> npm run dev`.

The frontend's API types are generated from the backend's OpenAPI schema. After
changing the API, regenerate them with the backend running:

```bash
cd frontend && npm run api:types    # reads http://127.0.0.1:8105/openapi.json by default
# or: OPENAPI_URL=http://127.0.0.1:8000/openapi.json npm run api:types
```

### 4. Tests and checks

```bash
cd backend  && pytest                 # 195 backend tests
cd frontend && npm run typecheck      # TypeScript, no emit
cd frontend && npm run build          # production build
```

Each test runs in its own PostgreSQL schema, created and dropped around it, so
tests are isolated while still exercising real row locking — which the
concurrency tests depend on. By default they use `DATABASE_URL`; point
`TEST_DATABASE_URL` at a scratch database to keep test schemas out of your
development one:

```bash
cd backend
TEST_DATABASE_URL=postgresql+psycopg://aec:aec_dev_password@localhost:5432/aec_test pytest
```

---

## Configuration

Everything is environment-driven; `.env.example` in each directory lists the
variables and contains no secrets.

**`backend/.env`**

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://aec:…@localhost:5432/aec` | PostgreSQL only; startup fails on anything else. |
| `TEST_DATABASE_URL` | falls back to `DATABASE_URL` | Where the test suite creates its per-test schemas. |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `10` / `10` | Connection pool. Size against `max_connections`. |
| `DB_POOL_RECYCLE_SECONDS` | `1800` | Recycle before proxy and server idle timeouts bite. |
| `DB_STATEMENT_TIMEOUT_MS` | `30000` | Server-side runaway-query guard. `0` disables. |
| `DB_LOCK_TIMEOUT_MS` | `10000` | Fail fast instead of queueing on a row lock. `0` disables. |
| `ENVIRONMENT` | `development` | `seed.py` refuses to run unless this is `development`. |
| `CORS_ORIGINS` | `http://localhost:5173,…` | Comma-separated browser origins. |
| `ALLOW_ZERO_PRICE_LINES` | `true` | Whether a 100% discount is permitted. |
| `LOG_LEVEL` | `INFO` | Root log level. |
| `BUSINESS_TIMEZONE` | `Asia/Kolkata` | IANA zone that daily figures (the Overview chart) are counted in. |
| `SQL_ECHO` | `false` | Log every SQL statement. |

**Frontend (development only)**

| Variable | Default | Purpose |
| --- | --- | --- |
| `API_PROXY_TARGET` | `http://127.0.0.1:8000` | Where the dev server sends `/api` requests. |

In production the backend serves the built app from the same origin, so the
frontend needs no configuration.

---

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/products` | List, with `search`, `include_inactive`, `sort_by`, `sort_dir`. |
| `POST` | `/api/products` | Create, with optional `opening_stock`. |
| `GET` | `/api/products/{id}` | Read one. |
| `PATCH` | `/api/products/{id}` | Edit. **Stock is not an editable field.** |
| `POST` | `/api/products/{id}/archive` | Soft-delete. |
| `GET` | `/api/customers` | List, with `search`, `include_inactive`, `sort_by`, `sort_dir`. Each row carries open orders, owed quantity and value, ordered value and last order date. |
| `POST` | `/api/customers` | Create. |
| `GET` | `/api/customers/{id}` | Detail, with outstanding quantities and order history. |
| `PATCH` | `/api/customers/{id}` | Edit. |
| `POST` | `/api/customers/{id}/archive` | Soft-delete. |
| `GET` | `/api/suppliers` | List, with `search`, `include_inactive`, `sort_by`, `sort_dir`. Each row carries open purchase orders and what is still due. |
| `POST` | `/api/suppliers` | Create; the code is generated when not supplied. |
| `GET` | `/api/suppliers/{id}` | Detail, with purchase order and goods receipt history. |
| `PATCH` | `/api/suppliers/{id}` | Edit. |
| `POST` | `/api/suppliers/{id}/archive` | Soft-delete; history is kept. |
| `GET` | `/api/purchase-orders` | List, with `search`, `status` (one, or several comma-separated), `supplier_id`, `product_id`. |
| `POST` | `/api/purchase-orders` | Raise one; `confirm: true` places it at once. Changes no stock. |
| `GET` | `/api/purchase-orders/{id}` | Detail, with ordered/received/remaining per line. |
| `PATCH` | `/api/purchase-orders/{id}` | Edit lines while DRAFT; notes and dates thereafter. |
| `POST` | `/api/purchase-orders/{id}/confirm` | Place a draft with the supplier. |
| `POST` | `/api/purchase-orders/{id}/cancel` | Cancel; what arrived stays arrived. |
| `GET` | `/api/goods-receipts` | List, with `search`, `supplier_id`, `purchase_order_id`. |
| `POST` | `/api/goods-receipts/preview` | What a receipt would do, including the allocation proposal. Writes nothing. |
| `POST` | `/api/goods-receipts` | Book goods in and reserve them against waiting orders. |
| `GET` | `/api/goods-receipts/{id}` | Detail, with what each line was reserved to. |
| `GET` | `/api/inventory/pending-commitments` | What is owed to customers, oldest first, with filters. |
| `GET` | `/api/orders/{id}/fulfilment` | Per line: ordered, delivered, reserved, unallocated, deliverable. |
| `POST` | `/api/orders/{id}/deliveries` | Hand reserved goods over. |
| `GET` | `/api/deliveries` | Delivery history. |
| `GET` | `/api/enquiries` | List, with `search`, `status`, `customer_id`, `created_from`, `created_to`. |
| `POST` | `/api/enquiries` | Create an enquiry; each line is priced from the product master's MRP. |
| `GET` | `/api/enquiries/{id}` | Detail, with line pricing and the enquiry total. |
| `PATCH` | `/api/enquiries/{id}` | Edit notes, lines, quantities and discounts. OPEN only. |
| `POST` | `/api/enquiries/{id}/convert` | Close the deal: create the sales order and fulfil stock. |
| `POST` | `/api/enquiries/{id}/mark-lost` | Close without an order. No stock moves. |
| `GET` | `/api/orders` | List, with `search`, `status`, `customer_id`, `product_id`, `sort_by` (`created_at`, `order_number`, `total_amount`), `sort_dir`. |
| `POST` | `/api/orders` | Create a multi-line order and fulfil what stock allows. |
| `GET` | `/api/orders/{id}` | Detail, with line items, allocations and cancellations. |
| `POST` | `/api/orders/{id}/cancel` | Cancel outright (only if nothing is fulfilled). |
| `POST` | `/api/orders/{id}/cancel-remaining` | Cancel only the unfulfilled remainder. |
| `GET` | `/api/inventory/summary` | Dashboard figures, including `daily_sales`: booked and delivered value for each of the last 30 local days. |
| `GET` | `/api/products/{id}/inventory` | Stock figures, valuation, open purchase batches and the movement ledger. |
| `GET` | `/api/products/{id}/pending-orders` | Settlement preview; pass `receipt_quantity` for the FIFO proposal. |
| `POST` | `/api/stock-receipts` | Record a receipt and settle pending orders atomically. |
| `GET` | `/api/stock-receipts/{id}/allocations` | Which orders received each incoming quantity. |
| `GET` | `/api/health` | Liveness. |

### Listings are paged

Every list endpoint above (products, customers, suppliers, orders, enquiries,
purchase orders, goods receipts, deliveries) is paged on the server and returns
an envelope rather than a bare array:

```json
{ "items": [ … ], "total": 312, "limit": 25, "offset": 50 }
```

`limit` defaults to 50 and may be 1–500; `offset` defaults to 0. `total` counts
every row matching the filters, so a client can draw "51–75 of 312" and a pager
without fetching the rest. Sorting and filtering happen in the database before
the window is applied, and each sort has a unique tiebreak so pages never
overlap or skip a row.

Errors use a consistent envelope and HTTP status:

```json
{
  "code": "allocation_error",
  "message": "Allocations must total exactly 5.000 (the lesser of the 10.000 received and the 5.000 outstanding). Got 2.000. …",
  "details": { "required_allocation": "5.000", "allocated": "2.000" }
}
```

`404` not found · `409` conflict (duplicate SKU, illegal cancellation) ·
`422` validation and allocation failures · `503` database unavailable.

### Recording a stock receipt

```bash
curl -X POST http://localhost:8000/api/stock-receipts \
  -H 'Content-Type: application/json' \
  -d '{
        "product_id": "…",
        "quantity": "10",
        "note": "Lorry 42",
        "idempotency_key": "a-unique-string-per-submission"
      }'
```

Omit `allocations` for FIFO. Send them to override the distribution:

```json
"allocations": [
  { "order_item_id": "…", "quantity": "4" },
  { "order_item_id": "…", "quantity": "6" }
]
```

`unit_cost` is the purchase price per unit; it opens the FIFO cost layer this
stock will be sold from. `supplier_reference` is free text for an invoice or
supplier name.

`idempotency_key` is optional but recommended: a retry or a double-click with
the same key replays the original result instead of recording a second receipt.

### Pricing an order line

```json
{
  "customer_id": "…",
  "items": [
    { "product_id": "…", "quantity_ordered": "20",
      "unit_price": "100.00", "discount_percent": "10" }
  ]
}
```

Omit `unit_price` to use the product's MRP. `discount_percent` must be between
0 and 100. The response carries the order's subtotal, discount and total, and a
`financials` block with per-line and whole-order cost and profit.

---

## Architecture

```
backend/
  app/
    main.py            FastAPI wiring, error translation, OpenAPI metadata
    config.py          Environment-driven settings
    database.py        Engine, session factory, SQLite/PostgreSQL locking strategy
    models.py          ORM models and database constraints
    schemas.py         Pydantic request/response models
    errors.py          Domain errors → HTTP statuses
    numeric.py         Fixed-scale decimal helpers
    services/          ← ALL business logic lives here
      common.py        Locking, document numbering, movements, status derivation
      products.py      Product master
      customers.py     Customer master
      orders.py        Order creation, priority fulfilment, cancellation
      costing.py       FIFO cost layers: what stock cost and what it earned
      pricing.py       The one place a selling price is worked out
      enquiries.py     Customer enquiries and conversion into a sales order
      reservations.py  The one allocation engine: reserve, release, consume
      suppliers.py     Supplier master and its purchasing history
      purchasing.py    Purchase orders and goods receipts
      deliveries.py    Customer deliveries and pending commitments
      inventory.py     Stock receipts and compulsory settlement
    api/               Thin HTTP routers; no business logic
  alembic/             Migrations
  tests/               pytest suite
  seed.py              Development-only demo data

frontend/
  DESIGN.md            The plan: modules, window layout, look, stack
  src/
    api/               Generated schema types, fetch client, endpoints, query hooks
    app/               Window shell: title bar, dock, command palette, sign-in gate
    ui/                Building blocks: buttons, sheets, menus, tabs, split view,
                       pickers, line editor, allocation editor, charts
    features/          One folder per module (home, fulfilment, orders, …)
    lib/               Formatting, statuses, URL helpers
    styles/app.css     Tailwind theme tokens (black, white, light blue)
```

API routers only parse, delegate and serialise. Every rule — validation,
fulfilment, allocation, status derivation — lives in `app/services/`.

### Data model

- `products`, `customers` — master data, soft-deleted via `is_active`.
- `sales_orders` → `sales_order_items` — one order, many product lines.
  Pending quantity is `ordered − fulfilled − cancelled`.
- `stock_movements` — an append-only ledger. Every change to physical stock
  writes a row in the same transaction. `Product.physical_stock` is a cached
  balance of this ledger, and a test asserts the two agree.
- `stock_receipts` — goods-receipt headers, with an optional unique
  `idempotency_key`.
- `stock_allocations` — links each allocated quantity to the order line that
  consumed it, and to the receipt it came from (`NULL` when the stock was
  already on hand at order time). Carries the cost of goods for that quantity.
- `stock_cost_layers` — a batch of stock bought at one price, drawn down FIFO.
  `quantity_remaining` across a product's layers always equals its physical
  stock.
- `stock_layer_consumptions` — one draw from one layer, for one allocation. An
  allocation that spans two differently priced batches produces two rows, so
  the cost trail stays exact.
- `order_cancellations` — audit row for every cancelled quantity.
- `customer_enquiries` → `customer_enquiry_items` — a deal being negotiated.
  Each line stores the MRP it was opened against, the agreed discount, the
  calculated unit price and the line total. `sales_orders.enquiry_id` is
  **UNIQUE**, which is what makes converting an enquiry twice impossible.
- `suppliers` — who the business buys from, soft-deleted via `is_active`.
- `purchase_orders` → `purchase_order_items` — what was ordered from a
  supplier. `quantity_remaining` is derived from ordered less received.
- `goods_receipts` → `goods_receipt_items` — what actually arrived, with the
  price actually paid (which may differ from the ordered cost) and an
  over-receipt flag and reason where one was allowed.
- `stock_reservations` — stock set aside for one order line, with
  `quantity_released` recording how much has since been delivered or cancelled.
  The open amount is `quantity − quantity_released`; a tested invariant is that
  these sum to each line's `quantity_reserved` and never exceed physical stock.
- `customer_deliveries` → `customer_delivery_items` — goods handed over, each
  line tied to the stock movement that took them out of inventory.
- `document_counters` — row-locked counters behind `SO-`, `GRN-` (ad-hoc stock
  receipts), `GR-` (goods receipts), `PO-`, `DN-`, `ENQ-` and `SUP-` numbers.

All foreign keys to products, customers and orders are `RESTRICT`. Historical
records cannot be deleted, only archived.

### Concurrency

Every operation that changes stock, reservations or delivered quantity takes
`SELECT … FOR UPDATE` on the rows it is about to touch, *before* reading any
quantity off them, so concurrent work serialises instead of racing:

- changing a product's stock or reservations locks the **product** row;
- a delivery locks the **sales order** row, then the product rows;
- a goods receipt locks the **purchase order** row, then the product rows;
- converting an enquiry locks the **enquiry** row;
- document numbering locks its **counter** row.

Product rows are always locked in a deterministic order, so two multi-product
operations cannot deadlock against each other. Reading before locking is a real
bug, not a theoretical one: it let two concurrent deliveries both validate
against the same pre-delivery snapshot, and a test now pins the fix.

Beyond the locks, `consume()` raises `quantity_released` on the reservation it
draws from, so the same reserved quantity can never go out twice, and a delivery
that cannot draw its full quantity fails rather than over-delivering.

Duplicate submissions are handled by a unique `idempotency_key` on
`stock_receipts`, `goods_receipts` and `customer_deliveries`: the stored result
is replayed rather than re-applied.

---

## Testing

```bash
cd backend && pytest -v
```

| File | Covers |
| --- | --- |
| `test_settlement.py` | Tests 1–5: the short order, settlement after receipt, FIFO across three customers, valid and invalid custom allocations, a receipt larger than demand, fractional quantities, the audit trail, idempotency. |
| `test_orders.py` | Test 8 plus multi-product orders, older-order priority, status derivation, validation failures. |
| `test_masters.py` | Test 6: duplicate SKUs, negative values, unknown ids, archiving, `RESTRICT` deletes, search and sort. |
| `test_rollback.py` | Test 7: every class of invalid receipt leaves the database byte-for-byte unchanged, and the cached balance still matches the ledger. |
| `test_concurrency.py` | Test 9: concurrent receipts never settle the same pending quantity twice, concurrent orders never oversell, concurrent duplicate submissions create one receipt. |
| `test_pricing.py` | Line pricing and discounts, order totals, FIFO cost of goods sold across batches, profit recognised on delivery only, the costing invariant through a full buy/sell/settle cycle, trading roll-ups. |
| `test_purchasing.py` | Suppliers; purchase orders that move no stock; invalid suppliers, products and quantities; partial then final receipt; over-receipt rejection and the override; receipts against cancelled and draft orders; FIFO allocation on a goods receipt; custom and invalid distributions; surplus; idempotency; rollback. |
| `test_fulfilment.py` | Reservation is not delivery; reserved stock is not offered to another customer; partial then final delivery; delivery limits; the same reservation cannot go out twice; rollback; concurrent deliveries and receipts; the ledger matching physical stock; pending commitments and their filters. |
| `test_enquiries.py` | Creating, pricing, editing and converting enquiries; discounts of 0%, 12.5% and 100%; rejections; rollback; converting twice, including concurrently; lost enquiries; identity by id. |
| `test_enquiries_api.py` | Enquiry endpoints over HTTP, through to the created sales order and its inventory effect. |
| `test_migrations.py` | The migration chain matches the models with no drift, and Phase 1 orders written before Phase 2 still read correctly after it. |
| `test_api.py` | HTTP status codes, error envelopes, the full order → receipt → settlement flow, the money flow end to end, dashboard figures. |

---

## Scope and limitations

Phase 1 deliberately stops here.

**Implemented** — suppliers, purchase orders, partial goods receipts with
compulsory reservation of incoming stock, customer delivery with partial
deliveries, the pending-commitments dashboard, customer enquiries with
per-product discounts and conversion into sales orders, product master,
customer master, multi-product sales orders,
priority-aware fulfilment, compulsory settlement on stock receipt with
adjustable FIFO allocation, the stock movement ledger, allocation audit trail,
order cancellation with audit history, purchase cost capture with FIFO stock
valuation, per-line pricing and discounts, bill totals, cost of goods sold and
gross profit per line, per order and across the business, dashboard and
inventory views.

**Not implemented (out of scope)** — quotations as a separate document, CRM,
supplier payments, accounts payable, accounting vouchers or Tally integration,
printed invoices, customer payments and receivables, tax or GST, AI features,
advanced financial reporting, authentication and authorisation, and
multi-warehouse or batch/serial tracking.

**Known limitations**

- There is no authentication. The API is open to anything that can reach it, so
  do not expose it beyond a trusted network as-is.
- A stock receipt cannot be reversed from the app. Correcting one needs a
  compensating `ADJUSTMENT` movement, which has a movement type but no endpoint
  yet.
- List endpoints are unpaginated. Fine for Phase 1 volumes; they will need
  pagination before the tables grow large.
- `Product.physical_stock` is a cached ledger balance. It is updated
  transactionally and asserted against the ledger in tests, but there is no
  periodic reconciliation job.
- The frontend has no automated tests in the repository; it is covered by
  TypeScript, the production build, the backend's API tests, and browser
  runs of the main workflows (order, deliver, buy with settlement, receive,
  enquiry conversion, stock in) at desktop and phone widths.
- Fulfilment has no date-range filter in the interface; the API supports one.
- Fulfilment is a report, not a listing: the server returns up to 500
  outstanding lines with totals across all of them, and the page divides those
  into pages in the browser. A business owing more than 500 lines at once
  would need it paged on the server too.
- Product, customer and supplier pickers in the order, enquiry and purchase
  order forms load the whole active list (in 500-row requests). That is fine
  into the low thousands; beyond that they should become search-as-you-type.
- A customer's detail page lists all of their orders without paging.
- Profit is **gross** profit only: revenue less the purchase cost of the goods
  delivered. There is no freight, tax, overhead or other operating cost in the
  model, so these figures are not a profit-and-loss statement.
- Order-level stored totals (`subtotal_amount`, `discount_amount`,
  `total_amount`) are set when the order is created and reflect the quantity
  ordered. Cancelling a remainder does not rewrite them; the delivered and
  outstanding values in the `financials` block are the ones that move.
- A receipt's purchase price cannot be corrected after the fact. A wrong price
  stays in the cost layer it opened.
- Stock that predates cost tracking is valued at zero by the migration's
  backfill, which flags each backfilled layer in its note.
- Enquiry totals are **before tax**. This phase calculates no tax at all.
- An enquiry line keeps the MRP it was opened against for as long as the
  enquiry is open. There is no "re-price at today's MRP" action; removing the
  line and adding the product again achieves it.
- `GET /api/enquiries` takes `limit` and `offset` but returns a plain list with
  no total count, matching the other Phase 1 list endpoints.
- An enquiry cannot be reopened once it is converted or lost. That is
  deliberate: both are historical records.
- There is no authentication, so the over-receipt override is gated by an
  explicit flag plus a mandatory recorded reason rather than by a permission.
  Wire it to a role when auth arrives.
- A goods receipt and a delivery cannot be reversed from the app. Correcting one
  needs a compensating `ADJUSTMENT` movement, which has a movement type but no
  endpoint yet.
- Cancelling an order releases its reserved stock but does not automatically
  re-reserve it to whoever is next in the queue; the next receipt or order picks
  it up. A background re-allocation pass would close that gap.
- `SalesOrderItem.quantity_fulfilled` is named for Phase 1 but means
  *delivered*. It was left alone rather than renamed across four phases of
  history; the API exposes it as `quantity_fulfilled` with
  `quantity_reserved` and `quantity_unallocated` beside it.


## Signing in

Every page and API call needs a signed-in user, except the sign-in itself,
`/api/health` and the WhatsApp webhook Meta calls. The first admin is created
at startup from `ADMIN_USERNAME` / `ADMIN_PASSWORD` when no user exists yet
(never overwritten afterwards); change the password from the account menu at
the foot of the sidebar, which signs out every other session. Passwords are
stored as scrypt hashes; the session is a signed, HttpOnly, SameSite=Lax
cookie (Secure in production) lasting `SESSION_DAYS` (7). Five wrong passwords
lock a username for five minutes.

In development the Vite server forwards `/api` to the backend
(`API_PROXY_TARGET`), so the app and the API share an origin as in production.

## Integrations: AI, WhatsApp and email

**Settings → Integrations** turns customer messages into sales enquiries.

- **AI · Gemini**: the Gemini API key (encrypted, write-only), the model, the
  assistant's change policy and temperature, a connection test, and the switch
  that lets the AI read messages into enquiries. See **The assistant** below.
- **WhatsApp**: on/off, phone number ID, business account ID, verify token and
  an optional app secret (when set, only requests signed by Meta are accepted).
  Copy the webhook URL into Meta for Developers → WhatsApp → Configuration and
  subscribe to `messages`.
- **Email**: on/off, IMAP server, port, address, password (an app password for
  Gmail/Outlook), folder and how often to check, plus **Check inbox now**.

Every message is recorded once (`inbound_messages`, keyed by the WhatsApp
message id or the email Message-ID) and handed to the **enquiry agent**: a
LangChain ReAct agent (`langchain.agents.create_agent`) on Gemini. Its only job
is to decide whether a message is a sales enquiry and, if so, record it. It
never replies to the customer and never asks questions. Its four tools wrap
the existing services, so no business logic is duplicated:

| Tool | Wraps |
| --- | --- |
| `search_products` | `products.list_products` |
| `find_customers` | `customers.list_customers` |
| `create_customer` | `customers.create_customer` |
| `create_enquiry` | `enquiries.create_enquiry` (with `source` = channel) |

Each message ends as **Enquiry** (linked), **Not an enquiry**, **No matching
products**, **Failed** (with the error; can be retried) or **AI was off**
(can be retried once AI is on). Captured enquiries are marked WhatsApp or Email
in the Enquiries list.

Credentials are encrypted at rest with `SECRET_KEY` and never returned by the
API. **Set `SECRET_KEY` to a long random value in production and keep it**;
changing it makes saved credentials unreadable (they must be entered again).

Code: `app/services/ai_agent.py` (agent and tools), `whatsapp.py` (webhook),
`email_inbox.py` (IMAP and the background poller), `inbound.py` (the shared
pipeline), `integration_settings.py`; API in `app/api/integrations.py`.

## The assistant

A chat assistant that understands the business, answers from live data, makes
tables, charts and reports, reads documents, and does the work in the app —
with you confirming every change. Open it with the round button at the bottom
right of any page (or **⌘J / Ctrl J**), or full screen from **Assistant** in the
top bar. Design and reasoning: [`docs/AI-PLATFORM.md`](docs/AI-PLATFORM.md).

### Connect Gemini

1. Create an API key at <https://aistudio.google.com/apikey>.
2. In the app: **Settings → AI · Gemini**, paste the key into **Gemini API key**,
   pick a model (the list is read from your key; *Gemini 3.8 Flash* is a good
   default for analysis) and **Save**.
3. Press **Test connection**. The assistant is live as soon as it answers.

The key is encrypted with `SECRET_KEY`, stored on the server, and never sent to
the browser, written to logs or returned by the API (only "ends in 1234").
Remove it with **Remove**. Without a key everything else in the app works and
the assistant explains how to connect. A server can instead use its own
Vertex AI credentials (`VERTEX_API_KEY`, or `VERTEX_PROJECT` with Application
Default Credentials); a key saved in Settings takes precedence.

For interface work without a key, start the API with `AI_DEV_MODE=scripted`:
the assistant then runs a fixed, clearly labelled script that calls the real
tools (it is never used when a key is configured).

### What it can do

- **Answer from data** across products, stock, customers, enquiries, orders,
  deliveries, suppliers, purchases, receipts, follow-ups, inbound messages and
  Tally — about 60 tools, one per API route.
- **Analyse**: period comparisons, stock ageing and capital at risk, reorder
  quantities, slow and dead stock, enquiry conversion by source and stale
  quotes, customer value and dormant customers, supplier lead time, fill and
  on-time rates — and exact calculations over any result (filter, group, sum).
- **Show**: sortable tables with links to records, and bar, line, area,
  stacked, horizontal and pie charts, drawn in the chat.
- **Report**: PDF, Excel (formatted sheets with native charts) and CSV files,
  built only from real query results.
- **Read documents**: attach PDFs, photos, spreadsheets or text (drag, paste or
  the paperclip). Invoices and bills are read by Gemini; spreadsheets become
  data it can check against your records or turn into entries.
- **Act**: create and update customers, suppliers, products, enquiries, orders,
  purchase orders, receipts, deliveries and follow-ups, convert or lose
  enquiries, cancel orders… Each change appears as a card with what will
  happen, resolved to names and numbers; nothing runs until you press
  **Confirm**, and the reply reports exactly what the app answered.

### How it stays safe

- **Same rules as the screens.** Each tool calls the app's own REST route
  in-process, as the signed-in user (their session is passed along), so every
  validation, permission, transaction and Tally side effect is identical.
- **Confirmation.** Changes are proposals until confirmed, and run once only.
  Settings can let routine edits (contacts, notes, follow-ups) through without
  asking; money, stock and cancellations always wait.
- **Grounded output.** Tables, charts and reports are built from stored tool
  results, never from numbers the model writes.
- **Audit.** Every tool call is logged with user, route, result and duration
  (**Settings → Assistant activity**). Conversations are private to each user.

Code: `app/ai/` (`agent.py` runtime and prompt, `catalog.py` the tool list,
`executor.py` in-process calls, `actions.py` confirmations, `outputs.py` tables
and charts, `reports.py` files, `documents.py` attachments, `provider.py`
Gemini), API in `app/api/ai.py`; interface in `frontend/src/features/assistant`.

## Insights and follow-ups

**Insights** (top bar) turns the same data into decisions: this period against
the last; stock health with age buckets, days of cover, capital at risk and
reorder quantities; sales by product, customer or month; the enquiry funnel
with stale quotes and one-click follow-ups; customer value and concentration;
supplier reliability and late purchase orders. The **bell** lists what needs
attention now. Figures come from `/api/insights/*` (`app/services/insights.py`),
which the assistant uses too, so the two always agree.

**Follow-ups** are dated tasks — call a customer, chase a quote, push a
supplier — linked to the customer, enquiry, order, supplier or purchase order,
with priority and an owner. Overdue follow-ups and quotes left untouched for a
week raise alerts.

## Money, targets and the command centre

- **Finance** (top bar): what customers owe for goods delivered and what you
  owe suppliers for goods received, aged past each party's payment terms, with
  credit limits, overdue invoices and bills, and every payment. Record money
  received or paid from here, from a customer's or supplier's **Account** tab,
  or from the command palette. Payments settle the oldest open invoices first;
  a mistaken payment is voided, never deleted.
- **Customers and suppliers** carry payment terms (days of credit); customers
  also a credit limit. Their **Account** tab is a statement with a running
  balance; **Follow-ups** plans calls and chases against them.
- **Products** carry a category, minimum stock, preferred supplier and lead
  time. Stock health uses them for a lead-time-aware reorder point, an
  order-by date, and one recommendation per product (buy, plan, do not
  reorder, clear, watch). The product list filters by health, category and
  supplier, sorts by cover, idle days, reorder value or capital at risk,
  exports CSV, and **Buy** turns selected products into a pre-filled purchase
  order.
- **Home** is a command centre: key figures, money, today's priorities, sales,
  the monthly target with a labelled month-end estimate, profit and more.
  **Customise** hides and re-orders panels; the layout is saved per user.
- **Insights → Explorer**: any measure (booked, delivered, profit, cost,
  discount, orders, quantities) by month, week, day, weekday, product,
  category or customer, for any period, filtered by categories, products and
  customers, compared with the previous period, as a chart or table, with
  Pareto shares, drill-down by click, saved views and CSV export; plus a
  weekday × week heatmap. **Products** shows ABC classes, margin quadrants,
  growth and enquiry conversion; **Customers** shows segments, buying
  frequency and estimated annual value (labelled as an estimate).
- **Enquiries** can be sorted by a priority score (deal size, existing
  customer, freshness, stock available) with its reasons shown; call and
  WhatsApp are one click away.
- **⌘K** also runs actions (record money, plan a follow-up, products to
  reorder…), lists recently viewed records, and hands anything else to the
  assistant.

Where data is too thin (bought-together needs 20+ multi-product orders; trends
need at least 5 units a month) the screens say so rather than guess.

## How a sale flows now

1. **Enquiry.** Typed in; from WhatsApp, email or a phone call (AI reads it);
   or sent by the customer from **their own link** (`/e/<token>`, made on the
   customer page: their products and prices, no sign-in). **Who sent it is
   decided by code**: the sender's number or email is matched exactly against
   every number and email on file. No match: the enquiry waits as a
   **new sender**, keeping their name, number and email.
2. **Prices.** Each line starts at the customer's **best price** from their own
   discount, their own product prices, and the prices of every **customer
   group** they are in (groups are picked by hand, by rules over orders, spend,
   years with us, payment behaviour, city..., or both). "Apply best prices" re-prices an enquiry.
3. **Order.** Converting needs a customer: for a new sender, choose an
   existing customer or create one; their number and email are linked so the
   next message is recognised. Credit, discount and margin holds apply.
4. **Confirmation.** If switched on (Settings → WhatsApp), an approved
   template confirms the order on WhatsApp; it can also be sent from the order.
5. **Tally and invoice.** The order goes to Tally; the invoice is made when the
   order is placed or, if chosen (Settings → Tally → When to invoice), for each
   delivery. The invoice PDF can go to the customer on WhatsApp.
6. **Deliver and collect.** Deliveries (partial allowed), payments, reminders,
   returns.

## Customers and suppliers as complete records

Each customer and supplier owns child records, as in Odoo, ERPNext and
Business Central:

- **People** (owner, site engineer, accounts), each with their own numbers.
- **Phone numbers and emails**, as many as needed, labelled, marked WhatsApp
  or primary. A number or email belongs to one party only, so WhatsApp, email,
  phone calls and the assistant always find the right customer.
- **Addresses and delivery sites** (billing, sites, offices, warehouses).
  Orders and quotes choose the site and the person who ordered.
- **GSTIN and PAN** (validated; one GSTIN per party) and the **Tally ledger
  name**, fixed on first sync so renaming here never splits a Tally account.

Creating a customer or supplier checks for duplicates (same number, email or
GSTIN blocks it; a similar name warns). **Merge** moves everything from a
duplicate (orders, enquiries, payments, returns, calls, follow-ups, people,
numbers, addresses) and archives it, with an audit entry.

Products get **other names** (what customers call them), **barcodes**,
**supplier item codes** and **units** (1 tonne = 20 bags). Search, the
WhatsApp/email reader, phone calls and the assistant match on all of them.

## Controls, returns, counts, customer groups and reminders

Benchmarked against Business Central, NetSuite, SAP Business One, Odoo,
ERPNext, Zoho and TallyPrime (see `docs/ERP-RESEARCH.md` for the matrix,
gap analysis, roadmap and sources).

- **Order controls** (Settings → Order controls): credit limit and overdue
  invoices can warn or hold an order; maximum discount, minimum margin and
  below-cost limits hold it too. An admin approves a held order with a reason;
  approvals go to the audit log (Settings → Audit log).
- **Sales returns** (order → More → Record a return): a credit note settles the
  customer's oldest invoices; sellable goods go back into stock at the cost they
  were delivered at; revenue and cost of goods net out.
- **Stock count** (Stock → Stock count): enter counted quantities, see the
  difference at FIFO cost, post in one go. Single adjustments (damage, loss,
  samples, found) from a product's menu.
- **Customer groups** (Sales → Customer Groups): members by hand and/or by
  rules, and what members pay: a discount on everything plus per-product fixed
  prices or discounts with quantity breaks. There is no separate price list
  screen; old price lists were turned into groups (migration 5b7e2c1d9a40).
- **Units of measure**: a product is stocked in one base unit and can be bought
  and sold in any others (1 tonne = 20 bags, 1 brass = 100 cft), each switched on
  for sales and/or purchases, with default units and a whole-units rule. Order,
  quote and purchase lines keep the unit they were entered in; stock and costing
  stay in the base unit. Products also carry brand, HSN, GST rate, weight and any
  details (grade, size...), which TAI and PAI use to describe them.
- **Warehouses** (Stock → Warehouses): godowns, yards, shops and site stores, one
  of them the default. Stock-in, goods receipts, counts, returns and deliveries can
  name a warehouse. Transfers go draft → dispatched (in transit) → received;
  freight, loading, unloading, toll and other costs are spread by quantity, value
  or weight and added to the goods' cost at the destination (landed cost), and
  shortages are written off as lost in transit. With Tally on, received transfers
  post as Stock Journals between godowns.
- **Transporters** (Buying → Transporters): full parties like suppliers (contacts,
  numbers, addresses, GSTIN, Tally ledger, payment terms, booking channel, rating)
  with vehicles and a rate card (per trip, km, tonne, quintal, kg, unit or hour, with
  minimum charge and validity). Deliveries, goods receipts, transfers and returns
  record the transporter, vehicle, LR number and freight; their statement shows
  freight owed and payments. Bookings ask a transporter for a vehicle.
- **Landed cost**: freight, unloading, insurance, octroi and other charges on a goods
  receipt (with it, or later when the bill comes) are spread by quantity, value or
  weight and added to the goods' FIFO cost; the share for goods already sold is shown.
- **Purchase returns**: send goods back from a receipt; stock leaves at the cost it
  came in, a debit note reduces what we owe (and goes to Tally as a Debit Note);
  optionally the supplier replaces them and the PO is owed them again.
- **Rate contracts** (Buying → Rate Contracts): agreed rates for a period with a
  supplier (purchase orders take the rate) or customer (competes for best price),
  with slabs, committed quantities and usage.
- **Book transport automation**: a flow step (sales or purchase) that books a vehicle
  when an order is placed, its stock is ready, or a PO is placed. TAI asks the
  transporter on WhatsApp or PAI calls; a YES with vehicle and rate confirms it within
  the step's limits, a NO moves to the next transporter on the rate card.
- **Triggers** (Settings → Automation, click a step): each step has its own settings.
  *Need detected* watches stock on a schedule (every N hours or a weekly review,
  chosen days and hours): customers short, below reorder point, low days of cover,
  with minimum value and supplier filters; it then asks suppliers for prices (RFQ),
  drafts a PO, or makes a task. *Ask the supplier*, *Read the reply*, *Compare and
  pick* (cheapest, fastest, best value or preferred, with deadline and minimum
  replies), *Send the PO* and *Chase the delivery* (days before/after due, repeats)
  run on their own within each step's mode and limits. On the sales side,
  *Reach out* finds customers to contact (stopped ordering, due to reorder, quotes
  not turned into orders, products they buy back in stock, chosen groups, slow
  stock to clear) and skips those with overdue bills or in excluded groups;
  *After-sales follow-up* asks for feedback a set time after delivery, with quiet
  hours and per-customer caps. **Try it** previews
  who would be picked or runs a step now; **Activity** shows what happened, the
  supplier quotes per request and customer feedback.
- **Follow-up calls by PAI**: a follow-up can be a call with instructions, a time
  and who does it. Choose *PAI · sales AI agent* and PAI rings the customer or
  supplier at exactly that time, follows the instructions (it also knows prices,
  stock and their orders, and can take an order), retries if nobody answers, and
  writes the outcome back on the follow-up.
- **Batches and expiry**: switch on *Track batches* on a product (with a shelf life
  to fill expiry from the date made). Every stock-in and goods receipt then needs a
  batch number; stock goes out earliest expiry first. The product page lists stock
  per batch with expired and expiring-soon marks.
- **Customer page** (the customer's private link): order from the catalogue, their
  orders and deliveries, invoices as PDF, account balance and statement, and
  reorder in one tap. Works on a phone.
- **Payment reminders** (Finance → Reminders): friendly, firm and final levels
  by days late, message ready for WhatsApp, each reminder logged with a
  follow-up to check payment.
- **Quotation PDF** from any enquiry.

## Tally and invoices on WhatsApp

**Settings → Integrations → Tally** connects any TallyPrime. Everything is
configurable per business: server address, company, an optional bearer token
for a gateway, ledgers, groups for new customers/suppliers, godown, voucher
type names, GST (none / CGST+SGST / IGST, rate and ledgers) and the seller
details printed on invoices. **Test connection** lists the companies open in
Tally.

- **Sales order placed** → a *Sales Order* voucher and a *Sales* invoice in
  Tally. The invoice number is Tally's own (set the Sales voucher type to
  automatic numbering). Customers and stock items are created if missing.
- **Purchase order placed** (not drafts) → a *Purchase Order* voucher.
- **Invoice to the customer**: as soon as Tally has the invoice, a PDF of it
  (Tally's number, the order's lines, GST) is uploaded to WhatsApp and sent
  with the approved template — WhatsApp card → *Send invoices*: access token,
  template name, language, default country code. The template needs a
  **Document** header and a body with `{{1}}` customer, `{{2}}` invoice number,
  `{{3}}` amount; **Check template** shows Meta's approval status.

Each document's status is in the *Tally sync* log and on the order's page.
A failure keeps Tally's or Meta's exact reason and is retried automatically
(a few times, a little later each time) or by hand.

**Connecting.** Tally has no hosted cloud API: the app talks XML to
TallyPrime's own HTTP server (F1 → Settings → Connectivity → acts as Server,
port 9000) — XML works on every release. Tally's server has no authentication,
so expose that port **only to this app** (firewall / IP allow-list), or put a
gateway in front of it and set the access token. Tally on cloud hosting works
the same way; ask the provider to open the port to Render's outbound IPs.

Code: `app/services/tally.py` (XML client), `tally_sync.py` (queue, push,
retries, invoice), `invoice_pdf.py`, `whatsapp.py` (sending).

## Marketing

**Marketing** (top bar) turns what the ERP knows into campaigns on Instagram and
WhatsApp. The full research and design are in `docs/marketing-module-plan.md`.

- **Home**: opportunities found by the Strategist, with the numbers behind each
  (new products, back in stock, slow or excess stock, batches near expiry, falling
  sales, rising enquiries, quiet customers, open quotes, festivals, birthdays) and
  one-click *Create campaign*; 30-day results; live campaigns; the Analyst's weekly
  review; channel status; an *Ask the Strategist* box.
- **Campaigns**: goal, products, offer, audience, dates and budget; an Instagram
  post and/or a WhatsApp broadcast written by the Creative agent (editable, with
  previews, rewrite in one click); approval (draft → waiting approval → scheduled →
  live → completed, or paused/cancelled); results (sent, delivered, read, replied,
  orders and revenue counted, cost and return); activity log.
- **Calendar** of every post and broadcast. **AI Studio**: product cards drawn in
  the brand colours, AI pictures (Gemini image model), WhatsApp marketing templates
  drafted by AI and sent to Meta for approval, an image library.
- **Audiences**: live, saved audiences from customer groups, the same figures as
  groups, products or categories bought (or not), birthdays/anniversaries, open
  enquiries, plus people left out by hand; live count and how many can be reached.
  **Consent**: who agreed to WhatsApp offers, how and when; STOP opts out at once.
- **Channels**: connect Instagram (Business/Creator account, Graph API), see posts
  with reach/likes/comments, answer comments (replies drafted by AI, posted only when
  you press Reply), hide spam; WhatsApp templates synced from Meta.
- **Automations**: when something happens (any of the opportunity triggers, a
  purchase, a schedule) suggest it, draft a campaign for approval, run it within the
  automatic policy, or create a follow-up; cooldown per customer.
- **Analytics**: funnel, channels side by side, revenue after campaigns, return on
  spend, best hour to send, every campaign compared.
- **Settings**: brand kit (name, tone, colours, hashtags, words to avoid), who
  approves, offers per customer per week, quiet hours, opt-out words, message cost,
  attribution window, festivals, the public address images are served from.

**Safety.** Agents only create drafts; the executor alone publishes or sends, and only
approved campaigns. Every WhatsApp offer needs recorded consent, respects the weekly
limit and quiet hours (checked again at send time), uses an approved marketing
template, and goes once per customer per broadcast. Instagram posts are published
once (the container id is stored before publishing); an expired token pauses
publishing and shows on the home page. Tokens are stored encrypted. Without Gemini,
copy comes from labelled templates and cards replace AI pictures.

**Results.** An order or enquiry from someone who got a message counts for the
latest campaign message before it, within the attribution window (14 days by
default); replies are marked. Instagram does not say who saw a post, so its effect
is shown as reach and engagement.

Code: `app/services/marketing*.py` (campaigns and executor, policy, audiences, media,
agents, rules, channels), `app/services/instagram.py`, `app/api/marketing.py`,
`frontend/src/features/marketing/`.

## Deploying to Render

`render.yaml` describes one Docker web service on Render that runs the API and
serves the built web app on the same address. `Dockerfile` builds the app and
starts the server; every deploy runs `alembic upgrade head` first, so the
schema is always current.

The database is **Neon** PostgreSQL. Set its connection string as the
service's `DATABASE_URL` secret. Use Neon's **direct** endpoint, not the
`-pooler` one: the app sets statement and lock timeouts per connection, which
the pooler does not accept. A `postgres://` or `postgresql://` URL is fine; the
app picks the psycopg driver itself.

The service uses Render's free plan, which sleeps after 15 minutes idle (the
first request then takes about a minute). Switch to `starter` for real use.

