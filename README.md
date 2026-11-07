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

The frontend follows macOS/iOS conventions: a grouped sidebar (Overview and
Fulfilment, then Sales, Purchasing and Inventory), a sticky frosted toolbar on
every page with the title, primary action and filters, and content in
rounded, lightly shadowed cards. Colour is reserved for meaning — each stock
figure has one colour used everywhere (ready, waiting, to deliver, short) —
and the accent blue marks what can be clicked.

- **Themes** — light, dark or follow the system, from the switch at the foot
  of the sidebar. The choice is remembered per browser.
- **Keyboard** — `⌘K` / `Ctrl K` opens the command palette (go to any screen,
  create any record, find orders, customers and products by number or name);
  `/` focuses the page's search box; `Esc` closes the topmost dialog, sheet or
  menu; arrow keys move through menus and the palette.
- **Deep links** — `?new=1` opens a list page's create dialog (for example
  `/orders?new=1`), `/products?open=<id>` opens a product's inspector,
  `/pending-fulfilment?filter=ready|awaiting|partial` pre-selects a filter.
- **Workflows** — Stock In and Goods Receipts are numbered steps that collapse
  to a summary once done, with a live before/after panel beside them; nothing
  is written until the final confirmation. Delivery is one shared dialog used
  from the order, the customer and the Fulfilment screen.
- **Feedback** — saves confirm with a toast (archive offers *Undo*);
  destructive actions ask first; lists show skeletons while loading and an
  explanatory empty state when there is nothing to show.
- **Motion and access** — dialogs, sheets and menus animate in and out with
  spring easing, and all motion is switched off under *Reduce motion*.
  Dialogs trap focus and restore it on close; controls carry labels for
  screen readers.
- **Phone widths** — below 960 px the sidebar becomes a drawer; tables scroll
  sideways inside their card instead of widening the page.
- **List or grid** — every listing (Sales Orders, Enquiries, Customers,
  Purchase Orders, Goods Receipts history, Suppliers, Products, Fulfilment) has
  a table view and a card view, switched from the toolbar and remembered per
  listing. Phones start on cards.
- **Pagination** — every listing ends in a pager: the range shown ("51–75 of
  312 orders"), rows per page (25, 50 or 100, remembered per listing) and page
  numbers. The page is part of the URL (`?page=3`), so Back and reloads keep
  your place; changing a filter or sort returns to page 1.
- **Export** — each listing's *Export* button downloads every row matching the
  current search, filter and sort as CSV (UTF-8, opens cleanly in Excel), not
  just the page on screen.
- **Overview chart** — value booked or delivered per day for the last 30 days,
  with a tooltip per day (pointer or arrow keys) and an equivalent table for
  screen readers. Days run midnight to midnight in `BUSINESS_TIMEZONE`.

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
cp .env.example .env                # point VITE_API_BASE_URL at your backend

npm run dev
```

The app is then on <http://localhost:5173>.

> If you run the backend on a port other than 8000, set
> `VITE_API_BASE_URL=http://localhost:<port>` in `frontend/.env` **and** add the
> frontend's origin to `CORS_ORIGINS` in `backend/.env`.

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

**`frontend/.env`**

| Variable | Default | Purpose |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Base URL of the API. |
| `VITE_PORT` | `5173` | Dev server port. |

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
  src/
    api/               Typed client and response types
    lib/               Decimal, formatting and async helpers
    components/        Design-system primitives, overlays, tables, forms,
                       navigation, command palette and shared dialogs
    pages/             One file per screen (list + detail pages, workflows)
    styles.css         Design tokens and every component style
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
  TypeScript, the production build, the backend's API tests and manual
  browser checks of the main workflows at desktop and phone widths.
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

- **AI**: on/off and the model, with a connection test. Users never see or set
  credentials: the server holds them in environment variables, and only models
  whose provider is configured are offered. `VERTEX_API_KEY` (Vertex AI
  express key) or `VERTEX_PROJECT` (Application Default Credentials, for local
  development) enables Gemini — 3.1 Flash-Lite first, the cheapest, which read
  14 of 14 test messages correctly; `ANTHROPIC_API_KEY` enables Claude.
- **WhatsApp**: on/off, phone number ID, business account ID, verify token and
  an optional app secret (when set, only requests signed by Meta are accepted).
  Copy the webhook URL into Meta for Developers → WhatsApp → Configuration and
  subscribe to `messages`.
- **Email**: on/off, IMAP server, port, address, password (an app password for
  Gmail/Outlook), folder and how often to check, plus **Check inbox now**.

Every message is recorded once (`inbound_messages`, keyed by the WhatsApp
message id or the email Message-ID) and handed to the **enquiry agent**: a
LangChain ReAct agent (`langchain.agents.create_agent`) on Claude. Its only job
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

