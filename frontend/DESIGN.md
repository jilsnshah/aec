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
│ ◆ AEC Desk  (Home)(Fulfilment 7) Enquiries Orders …  Settings  ⌕ ☾ [+ New] ◯ │
├───────────────────────────────────────────────────────────────────────┤
│ ╭──────────────────╮  ╭─────────────────────────────────────────────╮ │
│ │ Orders       13  │  │ SO-2026-000011                 Deliver  ⋯   │ │
│ │ ⌕ filter (All)…  │  │ Mixwell Builders · placed 7 Nov             │ │
│ │ SO-…011 ₹38,600  │  │  68 │ 26 │ 10 │ 13          figures         │ │
│ │ SO-…010   ₹160   │  │ Lines · Deliveries · Profit · Tally         │ │
│ ╰──────────────────╯  ╰─────────────────────────────────────────────╯ │
└───────────────────────────────────────────────────────────────────────┘
  list card (scrolls)     inspector card (scrolls)
```

* **Top bar**: the wordmark, every module as a pill with a black pill that
  glides to the open one (a live count on Fulfilment), then search (⌘K),
  light/dark switch, a "New" menu for every create action and the account
  menu. Below 1280 px the pills move to their own row and scroll sideways.
* **Split view** for every record module: a list card on the left (search,
  status filter) and an inspector card on the right with tabs. Selecting a
  row never leaves the screen; the URL follows the selection.
* **Sheets** for create and edit drop from the top, form on the left and a
  live summary on the right.
* **Home**: a board of rounded cards that fits one screen: three figure
  cards; a gauge of how much owed stock is in hand; a black "gross profit"
  card; a two-tone bar chart of booked against delivered sales; a table of
  recent orders (with To buy and To receive tabs); a dot chart of orders on
  each of the last seven days.
* **Fulfilment**: a board with three lanes (Ready, On order, Short), each card
  carrying its one next action (Deliver, Receive, Buy).
* **Integrations**: a settings window, connections on the left and one form on
  the right.

## Look

Light blue, black and white; professional and calm. Two themes share one set
of names: `:root` is light, `[data-theme='dark']` swaps the values
(`src/styles/app.css`). The choice is kept per computer; until one is made the
system setting decides.

* Light: a soft periwinkle canvas (`#dfe5f6`), white cards with 22 px corners
  and a faint shadow, near-black text. The one strong surface per screen is
  black. Primary buttons and the active pill are black.
* Dark: near-black canvas, charcoal cards, white primary buttons and pill; the
  strong card turns deep blue.
* Data colours: periwinkle `#8ea7f3` and royal blue `#1f4fe6`, used together
  as in the bars, gauge and dots. Status pills are light fills with coloured
  text (blue open, green delivered, red short).
* Plus Jakarta Sans (variable, self-hosted), tabular figures where numbers
  line up. Motion stays quiet: gliding pills and highlights, figures that count
  up, bars and gauge that grow in, sheets that spring open. No neon, no glow.

## Stack

* Vite + React 18 + TypeScript.
* Tailwind CSS v4 with the palette as theme tokens.
* TanStack Query for server state (cache, refetch, mutations, invalidation).
* `openapi-typescript` generates types from the backend's OpenAPI schema;
  a small typed `fetch` client calls `/api` with the session cookie.
* Radix UI primitives (dialog, dropdown, tooltip, tabs, switch, popover) for
  accessible behaviour; `cmdk` for the command palette; `motion` for
  animation; `sonner` for toasts; `lucide-react` icons.
