# AEC Desk — frontend plan

A desktop application for the AEC backend, not a website. The window never
scrolls as a page: every view is a fixed workspace of panes, and only lists
inside panes scroll.

## What the backend does (and what the app must cover)

| Area | Endpoints | What people do |
|---|---|---|
| Sign-in | `/api/auth/*` | Sign in, change password, sign out |
| Home | `/api/inventory/summary` | See what needs doing today |
| Fulfilment | `/api/inventory/pending-commitments`, `/orders/{id}/deliveries`, goods receipts, purchase orders | Deliver what is ready, receive what is on order, buy what is short |
| Enquiries | `/api/enquiries*` | Quote with per-line discounts, convert to an order or mark lost |
| Sales orders | `/api/orders*`, `/orders/{id}/fulfilment` | Place, deliver, cancel the rest, see profit and invoice |
| Customers | `/api/customers*` | Contacts, what they still wait for, their orders |
| Purchase orders | `/api/purchase-orders*` | Draft, place (choosing which short customers it settles), receive, cancel |
| Goods receipts | `/api/goods-receipts*` | Book in a delivery against a PO, choosing who gets it |
| Suppliers | `/api/suppliers*` | Contacts, open POs, receipts |
| Products | `/api/products*`, `/products/{id}/inventory` | Catalogue, stock (bought − sold), movement ledger, cost layers |
| Stock in | `/api/stock-receipts`, `/products/{id}/pending-orders` | Stock that arrived without a PO, assigned to waiting customers |
| Integrations | `/api/integrations*` | AI, WhatsApp, email, Tally settings; message and sync logs |

## The window

```
┌───────────────────────────────────────────────────────────────────────┐
│ ◼ AEC    Sales Orders            ⌕ Search or jump…  ⌘K     ＋ New   ◯ │  title bar (glass)
├────┬──────────────────────┬───────────────────────────────────────────┤
│ ⌂  │ Orders        13     │  SO-2026-000011            Deliver  ⋯     │
│ ⇄  │ ⌕ filter  [Open ▾]   │  Mixwell Builders · placed 7 Nov          │
│ ── │ ┌──────────────────┐ │  ┌─────┬─────┬─────┬─────┐                │
│ ✉  │ │▌SO-…011  ₹38,600 │ │  │ 68  │ 26  │ 10  │ 13  │  figures       │
│ ▤  │ │ Mixwell  ▮▮▮▯▯   │ │  └─────┴─────┴─────┴─────┘                │
│ ☺  │ ├──────────────────┤ │  Lines · Deliveries · Profit · Tally      │  tabs
│ ── │ │ SO-…010   ₹160   │ │  …                                        │
│ ▦  │ │ Hillcrest ▮▮▮▮▮  │ │                                           │
│    │ └──────────────────┘ │                                           │
└────┴──────────────────────┴───────────────────────────────────────────┘
 dock   list pane (scrolls)   inspector (scrolls)
```

* **Dock** (left, 76 px): module icons with short labels, grouped Sales,
  Purchasing, Stock. A live count on Fulfilment.
* **Title bar**: module name, global search / command palette (⌘K), a
  "New" menu for every create action, account menu.
* **Split view** for every record module: a compact list on the left (search,
  status filter, sort) and an inspector on the right with tabs. Selecting a
  row never leaves the screen; the URL follows the selection so links and the
  back button still work.
* **Sheets** for create and edit: they drop from the title bar like a macOS
  sheet, with the form on the left and a live summary on the right.
* **Home**: a bento board that fits one screen — headline figures, a sales
  chart, a to-do queue and recent activity.
* **Fulfilment**: a board with three lanes — Ready, On order, Short — each
  card carrying its one next action (Deliver, Receive, Buy).
* **Integrations**: a settings window — list of connections on the left,
  one form on the right.

## Look

Black, white and light blue only; professional and calm.

* Surfaces: `#0a0b0d` window, `#101216` panes, `#16191e` raised, hairlines at
  7 % white. Text white with three greys. Accent light blue `#7cc4ff`; primary
  buttons solid blue `#2f80ed` with white text.
* Status colours are muted and only carry meaning (short = red, warnings =
  amber, done = soft green).
* Artistic touches, kept quiet: a frosted title bar, a soft light-blue aurora
  behind Home's headline, a selection highlight that glides between rows,
  figures that count up, a chart that draws in, sheets that spring open.
  No neon, no glow, no gradient text.
* Inter (variable, self-hosted), tabular figures everywhere numbers line up.

## Stack

* Vite + React 18 + TypeScript.
* Tailwind CSS v4 with the palette as theme tokens.
* TanStack Query for server state (cache, refetch, mutations, invalidation).
* `openapi-typescript` generates types from the backend's OpenAPI schema;
  a small typed `fetch` client calls `/api` with the session cookie.
* Radix UI primitives (dialog, dropdown, tooltip, tabs, switch, popover) for
  accessible behaviour; `cmdk` for the command palette; `motion` for
  animation; `sonner` for toasts; `lucide-react` icons.
