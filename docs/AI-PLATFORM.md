# AEC Desk — AI platform and business intelligence plan

## 1. What the application is today (audit)

AEC Desk runs a trading business that buys goods from suppliers and sells them
to customers by quantity (cement bags, steel rods, sand, cartons…).

| Area | What exists | Where |
| --- | --- | --- |
| Products | Catalogue with SKU, unit, MRP, archive; stock figure = bought − sold; FIFO cost layers; movement history | `services/products.py`, `inventory.py`, `costing.py` |
| Customers | Masters with contact details, archive, order history | `services/customers.py` |
| Enquiries | Quotes with per-line discounts; sources: manual, WhatsApp, email; convert to order; mark lost | `services/enquiries.py` |
| Sales orders | Orders priced from MRP, reservations of free stock, short quantities, cancellations | `services/orders.py`, `reservations.py` |
| Fulfilment | Deliveries (partial), board of ready / on order / short | `services/deliveries.py` |
| Purchasing | Suppliers, purchase orders (draft → placed → received), settlement of short customers, goods receipts with allocation | `services/purchasing.py`, `assignments.py` |
| Stock in | Ad-hoc receipts with allocation to waiting customers | `services/inventory.py` |
| Integrations | Inbound WhatsApp/email turned into enquiries by a LangChain agent; Tally sync; invoice PDF | `services/inbound.py`, `ai_agent.py`, `tally_sync.py` |
| Auth | Users with HttpOnly session cookie, admin flag | `services/auth.py` |

Every API route is a thin wrapper over a service function; services own
validation, locking and transactions. Not present: payments/receivables, tasks
and follow-ups, employees beyond users, analytics beyond the home summary.

### Gaps that matter to this business
1. **No follow-up discipline.** Enquiries sit open with no owner, no due date
   and no reminder; nothing shows which quotes went cold.
2. **Stock is a number, not a picture.** There is no ageing of stock, no view
   of capital tied up per product, no dead-stock or reorder signal — although
   FIFO cost layers already hold every receipt date and cost.
3. **No period comparison.** The dashboard shows totals, not "this month vs last".
4. **No customer or supplier performance view.** Who buys most, who went
   quiet, which supplier is late or short-ships.
5. **No reports to hand to management.** Nothing exports to PDF or Excel.
6. **Everything is clicks.** No way to ask a question or delegate a task.

## 2. AI architecture

```
Browser (floating assistant / Assistant page)
   │  POST /api/ai/conversations/{id}/messages  (Server-Sent Events)
   ▼
AI service ── LangChain create_agent (ReAct loop) ── Gemini (API key from Settings)
   │                │
   │                ├─ Operation tools  ──► in-process call to the app's own REST API
   │                │     (same routes, validation, permissions, Tally side effects;
   │                │      the user's session cookie is forwarded)
   │                ├─ Insight tools     ──► /api/insights/* (new analytics service)
   │                ├─ Output tools      ──► tables, charts, PDF/Excel/CSV reports
   │                └─ Document tools    ──► uploaded files (PDF/images sent to Gemini natively;
   │                                          spreadsheets/CSV parsed to tables)
   ▼
Postgres: ai_conversations, ai_messages, ai_actions, ai_files, ai_tool_calls, tasks
```

**Single agent, many tools.** One orchestrating agent with a catalogue of
~60 tools grouped by module is simpler and more reliable than a multi-agent
graph for this data size; tool groups keep the catalogue modular (add a route
to the catalogue and it becomes a tool).

**Tools are the API.** Each operation tool names one REST route. Its argument
schema is derived from the route's own path/query/body models, and it executes
by calling the route in-process with the user's cookie. The AI therefore can
never do something the user's UI could not, and never bypasses a rule.

**Grounded outputs.** Every data tool stores its result as a *dataset* with an
id. Tables, charts and reports are built from dataset ids — the model cannot
type numbers into a chart. Records mentioned in replies are linked.

**Confirmation.** Read tools run immediately. Write tools never run during the
model's turn: they create a *pending action* (tool, validated arguments,
plain-language summary, risk level) that the user confirms or cancels in the
chat. The confirmed action runs through the same route; the outcome (success
or the exact error) goes back to the agent, which then reports it. Policy in
Settings: confirm every change (default) or only financial/destructive ones.

**Audit.** Every tool call is logged (user, conversation, tool, route, status,
duration) in `ai_tool_calls`; actions keep their arguments and results.

**Context.** The browser sends the current page and selected record; the
agent sees it in the system prompt. History is rebuilt from stored messages
(last 30 turns), with tool results summarised.

**Configuration.** Settings → AI: Gemini API key (encrypted with the server
secret, write-only — the API returns only "set, ends in 1234"), model (list
fetched from Gemini when a key is set, plus a custom id), change policy, test
button. Without a key the app works normally and the assistant explains how
to connect. `AI_DEV_MODE=scripted` runs a clearly labelled scripted model for
UI development and tests; it is never used when a key is configured.

## 3. Business intelligence (new `/api/insights`)

| Endpoint | Answers |
| --- | --- |
| `overview?period=` | This period vs the previous: orders, booked, delivered revenue, gross profit, margin, enquiries, conversion, new customers, purchase spend |
| `inventory` | Per product: free/reserved/on order/short, value at cost, stock age buckets (0–30/31–60/61–90/90+ days, from FIFO layers), last sale, 30/90-day velocity, days of cover, flags (dead, slow, low cover, overstock, short) and a reorder quantity |
| `sales?group_by=` | Revenue, quantity, profit by product, customer or month for any date range |
| `enquiries` | Funnel, conversion by source, time to convert, value in pipeline, stale open quotes, lost reasons |
| `customers` | Revenue, orders, last order, average order, open value, dormant customers |
| `suppliers` | Spend, purchase orders, lead time, fill rate, late deliveries, still due |
| `alerts` | Prioritised list of things to act on, each with a link and a suggested action |
| `briefing` | Today: what happened and what needs attention |

## 4. Follow-ups (new)

Tasks with due date, priority, assignee (user), status and a link to a
customer, enquiry, order, supplier or purchase order. Stale enquiries and
overdue tasks surface as alerts; the assistant can create, reschedule and
close them.

## 5. Milestones

1. Insights service + API + tests.
2. Follow-ups model, migration, API + tests.
3. AI backend: settings (key, model, policy), provider, tool catalogue,
   datasets/outputs, reports (PDF/XLSX/CSV), uploads, conversations,
   streaming, confirmations, audit, scripted dev model + tests.
4. AI UI: floating assistant, Assistant page with history, attachments, rich
   blocks (markdown, tables, charts, files, record links, action cards), page
   context.
5. Insights page and alerts in the app; follow-ups on Home and records.
6. Settings → AI; docs; full regression (pytest + browser end-to-end).

## 6. Status (19 November 2026)

Delivered on branch `frontend-v2`:

- Milestones 1–6 above: insights service and page, alerts bell, follow-ups
  (model, API, page), the assistant backend (60 operation tools + analysis and
  output tools, confirmations, audit, reports, attachments, streaming) and its
  interface (floating panel, full page with history), Settings → AI · Gemini,
  and grouped navigation (Sales, Buying, Stock menus).
- Tests: backend suite (including `tests/test_ai.py` with a scripted model
  driving the real tools, and `tests/test_insights.py`) and the browser
  end-to-end suite pass.

Waiting on the Gemini API key to evaluate live answer quality; the
architecture does not change when it is added.

Next candidates: payments and receivables (not in the data model yet),
scheduled briefings by email/WhatsApp, bulk actions from tables, and richer
seed history so trends and forecasts have more to work with.
