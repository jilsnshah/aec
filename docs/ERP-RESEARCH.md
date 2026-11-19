# ERP research, competitive matrix, gap analysis and roadmap

*19 November 2026, branch `frontend-v2`.*

## 1. How this was researched

We read three sets of product documentation, not marketing pages:

1. **SAP Business One / S/4HANA, Oracle NetSuite, Microsoft Dynamics 365 Business Central, Oracle Fusion Cloud ERP.**
   Sources: learn.microsoft.com, docs.oracle.com and help.sap.com.
2. **Odoo 17–19, ERPNext v15, Acumatica, Sage X3, Infor CloudSuite Distribution.**
   Sources: odoo.com/documentation, docs.frappe.io, Acumatica's help (through MYOB's white-label build, which uses the same form IDs), the Sage X3 online help and docs.infor.com.
3. **Zoho Inventory, Books and CRM; TallyPrime; Marg; BUSY; Vyapar; building-supply ERPs.**
   Sources: help.tallysolutions.com, zoho.com/help, busy.in, care.margcompusoft.com and advantive.com (DDI).
   The building-supply ERPs are ECI Spruce, Epicor BisTrack and DDI Inform.

**Caveats:**

- SAP B1 help on help.sap.com is mostly from the 9.x era.
- The ECI Spruce, Epicor BisTrack and Marg vendor pages blocked automated reading. Their claims below rest on search snippets and are marked *(unverified)*.
- AI features of SAP Business One come from a partner blog, not SAP.

The question asked of every feature was not "does SAP have it?". It was: **does a building-materials trader that buys by PO, sells on credit to contractors and quotes over WhatsApp need it, and can we do it more simply?**

## 2. Competitive feature matrix

Key to the columns:

- **Level:** B = basic, A = advanced, E = enterprise.
- **Value:** value to this business.
- **Status:** ✅ built and tested; 🟡 partly built; ⬜ not built; ✖ deliberately not built.

### 2.1 Essential ERP capabilities

| Feature | Who has it (source) | Problem it solves | Level | Value | Status |
|---|---|---|---|---|---|
| Physical stock count with variance | ERPNext Stock Reconciliation [E1]; Odoo Physical Inventory [O1]; BC physical inventory orders [M8]; Marg Stock Receive [T10] | Book stock drifts from the yard (breakage, theft, sand shrinkage) | B | High | ✅ Stock count: counted vs books, variance valued at FIFO cost, posted in one go |
| Stock adjustments with reasons | Tally stock journal [T9]; BC item journal | Damage, loss, samples and found stock must leave a trail | B | High | ✅ Damaged, lost, expired, sample, found, correction; audit-logged |
| Sales returns / credit notes | BC return orders, exact cost reversal [M5]; ERPNext Sales Return [E6]; Zoho RMA with restock or credit only [Z7]; Acumatica RMA [A3] | Site returns of excess or broken material distort stock and receivables | B | Very high | ✅ Credit settles the oldest invoices, sellable lines restock at the delivered cost, damaged lines are credited only, revenue and COGS net out |
| Quotation document | Odoo quotation templates [O5]; DDI quote-to-order [T17] | The customer wants a quote on paper or WhatsApp | B | High | ✅ Quotation PDF from any enquiry (validity date, discounts shown) |
| Customer price lists with quantity breaks | Tally price levels [T2]; Odoo pricelists [O6]; ERPNext Pricing Rule [E7]; BC price lists [M4]; NetSuite price levels [N34] | Dealers, contractors and builders each pay different rates | B | Very high | ✅ Price lists: a default discount, plus a fixed price or discount per product from a minimum quantity, with validity dates and an on/off switch. Applied automatically on orders and quotes |
| Credit limit and overdue hold | NetSuite Warn/Enforce holds [N28]; Zoho Books Restrict/Warn [Z4]; ERPNext credit controller [E8]; Fusion credit check [F47]; Infor aging hold [I3] | Contractor bad debt, the biggest risk in this trade | A | **Very high** | ✅ Credit control set to off, warn or hold. Exposure = owed + undelivered orders + this order. Overdue hold has a grace period. An admin overrides with a reason |
| Payment reminders (dunning) | BC reminder terms [M1][M2]; Odoo follow-up levels [O8]; SAP B1 dunning wizard [S42]; Tally and Zoho WhatsApp reminders [T5][Z5] | Collections; most of the cash cycle depends on chasing | B | **Very high** | ✅ Friendly, firm and final levels by days late. The message is ready for WhatsApp or a call; each reminder is logged and a follow-up is planned |
| Payment terms and receivables ageing | Every product; Tally F6 ageing [T14] | Knowing what is due and how late it is | B | High | ✅ (earlier work) |
| Audit trail | Tally Edit Log [T20]; BC change log [M19]; ERPNext versioning [E10] | Accountability once more than one person edits; MCA audit-trail rules | B | High | 🟡 Audit log covers control overrides, counts, adjustments, returns, voids and reminders. Field-level change history is not built yet |
| Purchase returns / debit notes | NetSuite Vendor Return Authorization [N37]; BC [M5]; Infor RM PO [I2]; Tally Rejections Out [T7] | Damaged or short lots go back to the supplier | B | High | ⬜ P2 |
| Units-of-measure conversion | Tally compound units [T11]; Zoho unit groups [Z11]; Spruce *(unverified)* | Bag ↔ tonne, piece ↔ bundle, brass ↔ cft | B | High | ⬜ P2 (schema change on every line) |

### 2.2 Advanced business management

| Feature | Who has it | Problem | Level | Value | Status |
|---|---|---|---|---|---|
| Discount and margin approval | ERPNext Authorization Rule [E9]; B1 approval on gross profit [S39]; Odoo Studio approvals [O10] | Salespeople giving away margin | A | High | ✅ Maximum discount, minimum margin and below-cost holds; admin approval with a reason |
| Activity timeline on every record | Odoo chatter [O9]; ERPNext Connections [E11]; B1 Relationship Map [S45] | One customer's story was spread over five screens | A | High | ✅ Orders, customers, suppliers and products (orders, deliveries, payments, returns, enquiries, tasks, stock movements) |
| Customer 360 | NetSuite Customer 360 [N32] | Seeing value, rhythm and risk in one place | A | High | ✅ (previous pass) |
| Supplier scorecard | ERPNext Supplier Scorecard [E5]; Fusion [F51] | Choosing reliable suppliers | A | Med | ✅ Fill rate and on-time. Blocking a supplier on score is not built |
| Supplier price comparison | Odoo and BC vendor price lists [O7][M4]; Sage X3 [X1] | Paying more than needed | B | High | ✅ Product Prices tab, cheapest supplier first |
| Reorder worksheet that creates POs | BC planning worksheet [M21]; Odoo replenishment [O2]; ERPNext auto material request [E2]; B1 order recommendations [S44] | Stock-outs and over-buying | A | High | ✅ Purchase suggestions by supplier, opening a pre-filled PO; reorder point = lead-time sales + minimum |
| Saved views and pivot analysis | BC analysis mode [M10]; NetSuite saved searches [N36]; Odoo pivot [O11] | Owners want their own cut of the numbers | A | High | ✅ Explorer with saved views (earlier work) |
| Blanket orders / rate contracts | BC [M17]; Odoo [O4]; ERPNext [E4] | Annual rates with mills; staged builder supply | A | Med–High | ⬜ P3 |
| Landed cost | Odoo [O3]; ERPNext Landed Cost Voucher [E3] | Freight is a large share of cost on cement and steel | A | High | ⬜ P2 |
| Multi-godown and transfers | Tally godowns [T9]; BC transfer orders [M11]; BUSY material centres | Yard, shop and site stock | B | Med (later) | ⬜ P3 (single location today) |
| Post-dated cheques | Tally PDC register [T15]; BUSY | Contractors pay with PDCs | B | High | ⬜ P2 |
| GST e-invoice and e-way bill | Tally [T1]; Zoho Books [Z1] | Compliance on every truck | B (India) | High | ✖ Stays in Tally: our orders already sync to Tally, which raises the IRN and EWB |
| Delivery proof (photo, signature) | BisTrack Delivery app [T6]; DDI | "Not received" disputes at sites | E | Med–High | ⬜ P4 |

### 2.3 AI capabilities

| Feature | Who has it | What it actually does | Status here |
|---|---|---|---|
| Natural-language Q&A over business data | BC Copilot chat [M15]; Zoho Ask Zia [Z18]; Odoo Ask AI [O12]; NetSuite Ask Oracle [N32] | Answers and navigation. Odoo's standard agent **cannot change data** | ✅ The assistant reads every module (90+ tools) and changes data only after confirmation |
| Order intake from customer messages | BC Sales Order Agent [M12]; BC sales-line suggestions [M13] | Reads an email, finds the customer, checks stock, drafts a quote | ✅ "Draft from a message" on the order form; WhatsApp and email enquiries arrive as drafts |
| Bill capture | BC Payables Agent [M14]; NetSuite Bill Capture [N32] | Supplier bills become drafts | ✅ "Scan bill" on goods receipts |
| Narrative insights / summaries | NetSuite Narrative Insights [N32]; Zoho Zia | Plain-language explanation of KPIs | ✅ Daily briefing; "what needs attention" panels on every list |
| Anomaly and risk alerts | Acumatica *(press)*; Zoho Zia anomaly [Z18]; NetSuite Exception Management | Spot unusual activity | 🟡 Alerts cover overdue, credit, late POs, stock-outs and unusual discounts at entry. Statistical anomaly detection is not built yet |
| Late-payment prediction | BC [M7]; NetSuite Payment Date Prediction [N32] | Which invoices will be paid late | ⬜ P3: needs more payment history than the data holds today |
| Demand forecasting | BC Sales & Inventory Forecast [M9]; NetSuite Demand Planning [N30]; Acumatica seasonality [A1] | Seasonal demand | 🟡 Trend direction and lead-time reorder point only. Statistical forecasting waits for 6+ months of history |
| AI connector / MCP | NetSuite MCP tools [N32] | External AI uses the ERP as a tool | 🟡 Every route is already a typed tool for our own assistant. An external MCP endpoint is P4 |

### 2.4 Enterprise-grade

| Feature | Who has it | Status |
|---|---|---|
| Roles and permission sets | BC security groups [M24]; ERPNext user permissions [E12]; Tally security levels [T20] | 🟡 Admin vs non-admin decides who may approve holds. Full role sets (sales, stores, accounts) are P2 |
| Approval workflow engine with delegation | BC approval workflows [M3]; B1 approval stages [S38]; ERPNext Workflow [E13] | 🟡 Holds with admin approval. Multi-step routing is P3 |
| Business events and subscriptions | Acumatica Business Events [A5]; Infor event alerts [I4] | 🟡 Alerts bell and follow-ups. User-defined triggers are P4 |
| Bins, putaway, multi-step routes | Odoo [O13]; BC bins [M23] | ✖ Not needed for a single yard |
| Lot / serial / batch tracking | BC [M22]; ERPNext batch with expiry [E14] | ✖ For now: low value (cement shelf life is the only case) |

### 2.5 Differentiators (ours)

- **An assistant that acts.** Every incumbent above is mostly read-only Q&A. Ours drafts and executes orders, purchase orders, payments, returns, counts and reminders, each behind a confirmation and an audit trail.
- **Every insight is one tap from its action.** Each "what needs attention" line opens the filtered list. Purchase suggestions open a pre-filled PO. A reminder opens WhatsApp with the message ready.
- **Checks while typing, not after posting.** Credit, margin, discount, last price paid and stock are shown live on the order form. Holds are explained in plain language with the numbers.

## 3. Gap analysis of our application (before this pass)

| Area | Had | Missing / weak | Now |
|---|---|---|---|
| Inventory | FIFO layers, reservations, ageing, reorder points, purchase suggestions | No way to correct stock; `ADJUSTMENT` existed in the ledger but nothing wrote it | Stock count and adjustments |
| Sales | Enquiries, orders, partial deliveries, order check | No returns, no price lists, no quote document, no credit enforcement | Returns, price lists, quotation PDF, holds |
| Finance | Receivables, payables, ageing, statements, payments | Collection was manual; no reminder history | Reminders with levels, logging and follow-ups |
| Controls | — | One admin, no approvals, no audit | Order controls and audit log; admin approval |
| Purchasing | POs, receipts, scorecards, suggestions | Purchase returns, landed cost, RFQ comparison | P2 |
| Cross-module | Timelines, 360 | Returns invisible to revenue and receivables | Returns flow into revenue, COGS, statements, timelines and order payment status |

**Redundant or confusing items found:**

- The old "health" dropdown on Products was replaced by chips (previous pass).
- Two places explained credit (the customer form and Finance). Both now point to the same rule, which is configured in Settings → Order controls.

## 4. Prioritised roadmap

Ranked by business value, user impact, differentiation, complexity and dependencies.

**Priority 1: critical gaps (done in this pass)**

1. ✅ Credit-limit and overdue holds with admin override.
2. ✅ Sales returns and credit notes.
3. ✅ Payment reminders (dunning).
4. ✅ Customer price lists with quantity breaks.
5. ✅ Stock count and adjustments.
6. ✅ Discount, margin and below-cost holds.
7. ✅ Audit log.
8. ✅ Quotation PDF.

**Priority 2: advanced and cross-module**

9. Purchase returns and debit notes, mirroring sales returns, with payables credited.
10. Roles (sales, stores, accounts, owner) with permission sets; holds route to the right approver.
11. Units-of-measure conversion (bag/tonne, piece/bundle).
12. Landed cost on goods receipts, spread into FIFO layers.
13. PDC register: cheques count only from their date; bounce alerts.
14. Field-level change history on orders, prices and customers.

**Priority 3: AI and automation**

15. Statistical demand forecast, with seasonality, once 6+ months of history exist; feeds the reorder point.
16. Late-payment prediction per customer, trained on our own history.
17. Scheduled WhatsApp reminders through an approved template, so they go out without a click.
18. Anomaly detection: unusual discount, unusual quantity, margin dip, per salesperson.
19. Blanket orders and rate contracts with mills and builders.

**Priority 4: enterprise and differentiating**

20. Multi-godown and site stock with transfers and transit loss.
21. Proof of delivery from a driver's phone (photo, signature, location).
22. Customer portal: statements, invoices and re-ordering.
23. An external MCP endpoint so other AI tools can use the ERP.

## 5. Traceability

| Feature | Precedent | Module | Implementation | Tests |
|---|---|---|---|---|
| Stock count and adjustments | ERPNext, Odoo, BC, Marg | Stock | `services/adjustments.py`, `/api/stock-adjustments`, Stock Count page, Adjust stock on product | `tests/test_adjustments.py`: variance value, newest-order release, found stock reserved, validation |
| Sales returns | BC, ERPNext, Zoho, Acumatica | Sales, Finance, Insights | `services/returns.py`, `/api/orders/{id}/returns`, Return sheet, timeline, statement credit notes | `tests/test_returns.py`: credit, restock at delivered cost, damaged not restocked, revenue/COGS reversal, over-return refused |
| Order controls | NetSuite, Zoho Books, ERPNext, Fusion | Sales, Settings | `services/controls.py`; enforced on `POST /api/orders` and enquiry convert; Settings → Order controls; hold panel with approval | `tests/test_controls.py`: warn vs block, override needs reason, non-admin refused, discount cap |
| Audit log | Tally Edit Log, BC change log | Settings | `AuditEvent`, `/api/audit`, Settings → Audit log | Covered in the control and reminder tests |
| Payment reminders | BC, Odoo, SAP B1, Tally, Zoho | Finance | `services/reminders.py`, `/api/finance/reminders`, Finance → Reminders | `tests/test_controls.py`: level by lateness, message, logged, follow-up task |
| Price lists | Tally, Odoo, ERPNext, BC, NetSuite | Sales | `services/pricelists.py`, `/api/price-lists`, Price Lists page, customer field, auto-pricing on orders and quotes | `tests/test_pricelists.py`: breaks, fixed price, list discount, inactive list, validation |
| Quotation PDF | Odoo, DDI | Enquiries | `enquiries.quotation`, `/api/enquiries/{id}/quotation.pdf` | `tests/test_adjustments.py::test_quotation_pdf` |

Every new route is also an assistant tool (see `app/ai/catalog.py`).

## 6. Sources

**Microsoft Dynamics 365 Business Central**

- [M1] https://learn.microsoft.com/en-us/dynamics365/business-central/receivables-collect-outstanding-balances
- [M2] https://learn.microsoft.com/en-us/dynamics365/business-central/finance-automate-reminders
- [M3] https://learn.microsoft.com/en-us/dynamics365/business-central/across-how-use-approval-workflows
- [M4] https://learn.microsoft.com/en-us/dynamics365/business-central/sales-how-record-sales-price-discount-payment-agreements
- [M5] https://learn.microsoft.com/en-us/dynamics365/business-central/sales-how-process-sales-returns-orders
- [M7] https://learn.microsoft.com/en-us/dynamics365/business-central/ui-extensions-late-payment-prediction
- [M8] https://learn.microsoft.com/en-us/dynamics365/business-central/inventory-how-count-inventory-with-documents
- [M9] https://learn.microsoft.com/en-us/dynamics365/business-central/ui-extensions-sales-forecast
- [M10] https://learn.microsoft.com/en-us/dynamics365/business-central/analysis-mode
- [M11] https://learn.microsoft.com/en-us/dynamics365/business-central/inventory-how-transfer-between-locations
- [M12] https://learn.microsoft.com/en-us/dynamics365/business-central/sales-order-agent
- [M13] https://learn.microsoft.com/en-us/dynamics365/business-central/sales-suggest-sales-lines-with-copilot
- [M14] https://learn.microsoft.com/en-us/dynamics365/business-central/payables-agent
- [M15] https://learn.microsoft.com/en-us/dynamics365/business-central/chat-with-copilot
- [M17] https://learn.microsoft.com/en-us/dynamics365/business-central/sales-how-to-create-blanket-sales-orders
- [M19] https://learn.microsoft.com/en-us/dynamics365/business-central/across-log-changes
- [M21] https://learn.microsoft.com/en-us/dynamics365/business-central/design-details-handling-reordering-policies
- [M22] https://learn.microsoft.com/en-us/dynamics365/business-central/inventory-how-work-item-tracking
- [M23] https://learn.microsoft.com/en-us/dynamics365/business-central/warehouse-how-to-set-up-locations-to-use-bins
- [M24] https://learn.microsoft.com/en-us/dynamics365/business-central/ui-security-groups

**Oracle NetSuite**

- [N28] https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N1080144.html
- [N30] https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N2286970.html
- [N32] https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/article_5101751849.html
- [N34] https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N2182485.html
- [N36] https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N690632.html
- [N37] https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N2386202.html

**SAP Business One**

- [S38] https://help.sap.com/saphelp_sbo92/helpdata/en/45/06dab4d8696c30e10000000a114a6b/content.htm
- [S39] https://help.sap.com/saphelp_sbo92/helpdata/en/45/06da03d8696c30e10000000a114a6b/content.htm
- [S42] https://help.sap.com/saphelp_sbo91/helpdata/en/91/0d4d7bb79f45af84005eedf6cfc02a/content.htm
- [S44] https://help.sap.com/saphelp_sbo92/helpdata/en/5a/6957d864b3458ea5b48aa0b8249e54/content.htm
- [S45] https://learning.sap.com/courses/managing-logistics-in-sap-business-one/exploring-master-data-and-documents

**Oracle Fusion Cloud ERP**

- [F47] https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26a/faiom/overview-of-setting-up-credit-check.html
- [F51] https://docs.oracle.com/en/cloud/saas/readiness/scm/26c/proc26c/26C-procurement-wn-f46291.htm

**Odoo**

- [O1] https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp/inventory/warehouses_storage/inventory_management/count_products.html
- [O2] https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp/inventory/warehouses_storage/replenishment/reordering_rules.html
- [O3] https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp/inventory/product_management/inventory_valuation/landed_costs.html
- [O4] https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp/purchase/manage_deals/blanket_orders.html
- [O5] https://www.odoo.com/documentation/18.0/applications/sales/sales/sales_quotations/quote_template.html
- [O6] https://www.odoo.com/documentation/18.0/applications/sales/sales/products_prices/prices/pricing.html
- [O7] https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp/purchase/manage_deals/rfq.html
- [O8] https://www.odoo.com/documentation/18.0/applications/finance/accounting/payments/follow_up.html
- [O9] https://www.odoo.com/documentation/18.0/applications/productivity/discuss/chatter.html
- [O10] https://www.odoo.com/documentation/18.0/applications/studio/approval_rules.html
- [O11] https://www.odoo.com/documentation/18.0/applications/essentials/reporting.html
- [O12] https://www.odoo.com/documentation/19.0/applications/productivity/ai.html
- [O13] https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp/inventory/shipping_receiving/daily_operations/putaway.html

**ERPNext**

- [E1] https://docs.frappe.io/erpnext/user/manual/en/stock-reconciliation
- [E2] https://docs.frappe.io/erpnext/user/manual/en/auto-creation-of-material-request
- [E3] https://docs.frappe.io/erpnext/user/manual/en/landed-cost-voucher
- [E4] https://docs.frappe.io/erpnext/user/manual/en/blanket-order
- [E5] https://docs.frappe.io/erpnext/user/manual/en/supplier-scorecard
- [E6] https://docs.frappe.io/erpnext/user/manual/en/sales-return
- [E7] https://docs.frappe.io/erpnext/user/manual/en/pricing-rule
- [E8] https://docs.frappe.io/erpnext/user/manual/en/credit-limit
- [E9] https://docs.frappe.io/erpnext/authorization-rule
- [E10] https://docs.frappe.io/erpnext/user/manual/en/document-versioning
- [E11] https://docs.frappe.io/framework/user/en/basics/doctypes/actions-and-links
- [E12] https://docs.frappe.io/erpnext/user/manual/en/user-permissions
- [E13] https://docs.frappe.io/erpnext/user/manual/en/workflows
- [E14] https://docs.frappe.io/erpnext/user/manual/en/batch

**Acumatica (via MYOB's build)**

- [A1] https://help.acumatica.com/(W(353))/Wiki/ShowWiki.aspx?pageid=ae2418af-7f53-4c09-8766-556452d8f8b8
- [A3] https://help.myob.com.au/advanced/Docs/Published/UserGuide/OrderMgmt_Sales_with_Returns_Mapref.html
- [A5] https://help.myob.com.au/advanced/Docs/Published/UserGuide/SA_Using_Business_Events_GeneralInfo.html

**Sage X3**

- [X1] https://online-help.sagex3.com/erp/12/en-us/Content/FCT/GESPOH.htm

**Infor CloudSuite Distribution**

- [I2] https://docs.infor.com/csdis/latest/en-us/useradminlib_csd_cloud/poolh/dsm1503926096425.html
- [I3] https://docs.infor.com/csdis/latest/en-us/useradminlib_csd_cloud/sxepgov/fbo1503926035355.html
- [I4] https://docs.infor.com/csdis/latest/en-us/useradminlib_csd_cloud/saolh/yze1503926018504.html

**TallyPrime, Marg and building-supply ERPs**

- [T1] https://help.tallysolutions.com/tally-prime/e-invoice-tallyprime/e-invoicing-in-tallyprime/
- [T2] https://help.tallysolutions.com/tally-prime/inventory/price-lists-and-price-levels-faq/
- [T5] https://help.tallysolutions.com/share-documents-using-whatsapp-for-business/
- [T6] https://apps.apple.com/us/app/id1228385709 (BisTrack Delivery)
- [T7] help.tallysolutions.com/sales-return-tally *(snippet)*
- [T9] https://help.tallysolutions.com/inventory-entry-tally/
- [T10] https://care.margcompusoft.com/margerp/stock-receive/99/1/PHYSICAL
- [T11] https://help.tallysolutions.com/units-of-measurement/
- [T14] https://help.tallysolutions.com/tally-prime/accounting-financial-reports/manage-receivables-outstanding-tally
- [T15] https://help.tallysolutions.com/tally-prime/banking-utilities/post-dated-cheque-managment-tally
- [T17] https://www.advantive.com/brands/ddi-system/
- [T20] https://help.tallysolutions.com/security-user-management-in-talllyprime/ and https://help.tallysolutions.com/tally-prime/edit-log/tracking-modifications/

**Zoho**

- [Z1] https://www.zoho.com/in/books/help/e-way-bill/generate-eway-bills/generate-ewb.html
- [Z4] https://www.zoho.com/books/help/contacts/credit-limit.html
- [Z5] https://www.zoho.com/books/help/integrations/whatsapp-integration.html
- [Z7] https://www.zoho.com/us/inventory/help/sales-returns/sales-returns-overview.html
- [Z11] https://www.zoho.com/us/inventory/help/settings/uom.html
- [Z18] https://help.zoho.com/portal/en/kb/crm/zia-artificial-intelligence/zia/articles/zia-overview
