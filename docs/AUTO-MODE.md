# Auto mode: letting the AI run the business, and what stands in the way

*19 November 2026. Starting point: the assistant has 102 tools and can do everything a person can do on the screens. Every change waits for a person to confirm it.*

## 1. The goal

A message arrives, and the business runs itself:

1. **Read the message.** WhatsApp or email comes in, and the AI decides whether it is an enquiry.
2. **Understand it.** Find the customer, the products and the quantities.
3. **Check the facts.** Is there stock? What is on their price list? What is their credit? What have they paid before, and how do they buy?
4. **Decide.** Pick a price and a discount, and choose between sending a quote and placing an order.
5. **Reply to the customer.** Send the quote or the order confirmation.
6. **Place the order.** Stock is set aside and the order goes to Tally.
7. **Buy what is short.** Draft a purchase order to the right supplier, then place it.
8. **Deliver and invoice.** Schedule the delivery, invoice it and send the invoice.
9. **Collect.** Remind the customer when payment falls due, and record the money when it arrives.

## 2. What already exists

| Step | Today |
|---|---|
| 1. Read message | ✅ The inbound agent reads WhatsApp and email and turns sales messages into **enquiries**. It never replies and leaves unclear messages for a person. |
| 2. Understand | 🟡 It matches customers by phone/name and products by name search. There are no product aliases and no unit conversion. |
| 3. Check facts | ✅ There are tools for stock, price lists, the customer 360 view, credit and order controls, last prices paid and margin. |
| 4. Decide | 🟡 Price lists and order controls exist. There is **no written discount policy**, so the AI would be improvising. |
| 5. Reply | ❌ The app cannot write to a customer. WhatsApp is only used to send invoices through one approved template. Email is read-only. |
| 6. Order | ✅ `convert_enquiry` / `create_order` work. Holds stop risky orders. |
| 7. Buy | ✅ Purchase suggestions, then `create_purchase_order`, then place it. |
| 8. Deliver / invoice | 🟡 Deliveries are recorded by a person. Invoices come from Tally. There is no delivery scheduling. |
| 9. Collect | 🟡 Reminders are drafted and logged, but a person sends them. **Payments are only known when someone records them.** |

The assistant itself only acts **when a person writes to it**, and every change waits for a person to tap Confirm.

## 3. The real gaps, most serious first

### A. Nothing wakes the AI up
The AI only runs when someone chats with it, or when a message arrives (and then only to make an enquiry). Nothing makes it act when:
- a new enquiry is created;
- a goods receipt lands;
- an invoice turns overdue;
- stock falls below the reorder point;
- a purchase order becomes late.

**Needed:** an event trigger layer (event → which agent task runs) and a scheduler for daily jobs (morning buying run, collections run).

### B. No way to decide what may run without a person
Today every change needs a human tap. Auto mode needs a policy that sets, for each kind of action, whether the AI may:
- **do it** within limits;
- **draft it** for approval;
- **never do it**.

Some examples:
- "Convert an enquiry to an order automatically if: the customer is not new, stock covers it, there are no holds, the discount is within the policy and the value is under ₹50,000."
- "Draft purchase orders automatically; placing one over ₹1,00,000 needs approval."

There is also no **approval inbox** where a person clears the AI's queued decisions in one place, and no **AI identity**. Today the assistant acts with the signed-in user's own access.

### C. It cannot talk to customers or suppliers
- **WhatsApp rules:** a business may send free text only within 24 hours of the customer's last message. After that it must use a template Meta has approved.
- **Missing pieces:** we have no sending of quotes, order confirmations, reminders or supplier POs. There are no templates for them, and no sending email (SMTP).
- **Why it matters:** without this, "auto" stops at the edge of the building.

### D. Understanding messages is not reliable enough to act on
- **Product names:** customers write "ultratech 50 bag", "8mm sariya", "2 brass reti". We have no **product aliases** and no **unit conversion** (bags ↔ tonnes, brass ↔ cft). A wrong product or a wrong unit means a wrong order with money attached.
- **New numbers:** an unknown phone number is either a new customer or a duplicate of an existing one. Nothing settles that safely.
- **Repeats:** the same request sent twice, or edited on WhatsApp, could become two orders. There is no de-duplication per customer per hour.

### E. No written discount policy
"Analyse customer behaviour and give a discount" must not be left to the model's judgement.
- **Needed:** a policy table the AI applies and quotes back:
  - base price from the price list;
  - plus up to X% for champions, Y% for at-risk customers worth keeping, Z% on dead stock;
  - never below the minimum margin;
  - never more than the maximum discount.
- **Today:** price lists and the order controls give the floor and the ceiling. The middle is missing.

### F. It cannot promise dates or know about money
- **Delivery dates:** there is no available-to-promise date ("can deliver Thursday") and no delivery schedule or vehicles.
- **Payments:** these are known only when a person records them. There is no bank feed, UPI collect link or payment-link webhook. Collections cannot close the loop automatically, and credit holds stay stale until someone records the money.

### G. No way to measure accuracy before trusting it
- **No test set:** we have no evaluation set of real messages with the correct outcome, so we cannot say "the AI gets 96% of enquiries right".
- **No shadow mode:** the AI cannot decide alongside a person, have both decisions logged and compared, and act on nothing.
- **Weaker default model:** Gemini 3.1 Flash-Lite (now the default) is cheap but weaker at long reasoning. Auto mode may need Flash for the decision step.

### H. Hard to see what it did, and some things can't be undone
- **Missing record:** the audit log covers approvals, counts, returns and reminders. Auto mode also needs a **decision record** for each run: what it saw, which rules applied, what it did and why.
- **Missing summary:** a daily digest ("AI handled 14 enquiries, placed 9 orders worth ₹3.2 lakh, held 2, needs you on 3").
- **Missing off switch:** one kill switch.
- **Can't take back:** an order can be cancelled, but a message sent to a customer cannot be unsent. Anything customer-facing needs the strictest limits.

### I. Things outside our walls
- **Tally:** sync failures still need a person.
- **GST:** e-invoice and e-way bill stay in Tally.
- **Cost:** model spend needs a daily cap.

## 4. Proposed design

### Autonomy ladder, set per action type

| Level | Meaning | Today |
|---|---|---|
| 0 Off | The AI never does it | — |
| 1 Suggest | The AI shows what it would do | ✅ Insight panels |
| 2 Draft | The AI prepares it; a person confirms | ✅ The assistant (every action) |
| 3 Auto within limits | The AI does it, notifies, and it can be reversed | ❌ |
| 4 Auto with customer contact | The AI also messages the customer or supplier | ❌ |

### The auto enquiry pipeline (level 3, with every step logged)

1. **Trigger:** an enquiry is created (from a message, or typed in).
2. **Match:** customer and products are matched with aliases and unit conversion. If any match has low confidence, the enquiry goes to the approval inbox.
3. **Price:** the price list gives the price, then the discount policy adjusts it. Every line must stay within the margin floor and the maximum discount.
4. **Check:** the order controls run on the draft. If anything holds, it goes to the approval inbox, and the AI never overrides.
5. **Gate:** customer segment is not "new", value is under the auto-limit, stock covers it, and nothing was ordered in the last 2 hours.
6. **Act:** convert the enquiry to an order, then send the confirmation (inside the WhatsApp window or by template).
7. **Short stock:** if anything is short, draft a purchase order to the cheapest reliable supplier; placing it follows the purchasing policy.
8. **Record and report:** write the decision record and include it in the daily digest.

### Roll-out, safest first

1. **Shadow mode:** for 2–4 weeks the AI decides every enquiry but acts on nothing. A person sees its decision next to their own, and we measure agreement.
2. **Auto-draft:** the AI creates the orders and POs as drafts in the approval inbox; one tap approves each.
3. **Auto within limits:** small orders from known customers with full stock and no holds.
4. **Customer messages:** quote and confirmation templates, sent inside the 24-hour window first.

## 5. Build order

1. **Event triggers and scheduler** (gap A). This is the backbone everything else hangs on.
2. **Autonomy policy, approval inbox and the AI as its own audited actor with limits** (gap B).
3. **Shadow mode and decision records** (gaps G, H), using the client's real WhatsApp and Tally history once it is imported.
4. **Product aliases, unit conversion and message de-duplication** (gap D).
5. **Discount policy table** (gap E).
6. **Outbound WhatsApp:** replies inside the 24-hour window, approved templates for quotes, confirmations and reminders, and SMTP email (gap C).
7. **Payment links or bank feed** so the money side closes itself (gap F).
8. **Daily digest, kill switch and cost cap** (gaps H, I).

Steps 1–3 can be built without the client. Steps 4–5 are best tuned on the client's own data after the Tally import. Step 6 needs Meta template approval, which takes a few days.
