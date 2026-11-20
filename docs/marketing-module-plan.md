# Marketing module — research, architecture and plan

Status: plan agreed in conversation (Nov 2026); built in slices M1–M6 below on
branch `frontend-v2`.

## 1. Research: what leading platforms do

| Platform | What they do well | What they miss for a trader like ours |
|---|---|---|
| HubSpot Marketing Hub (Breeze agents) | One contact record; lists (static + active); visual workflows; campaign object tying assets together; AI agents for content, social posting, prospecting; attribution reports | Prices start around $450–800/month; no idea of stock, batches, margin or who owes money; India WhatsApp is an add-on |
| Salesforce Marketing Cloud | Journey Builder (entry events → waits → splits → actions); Einstein send-time and engagement scoring; strong consent model | Enterprise-only, heavy setup |
| Zoho Marketing Plus / Campaigns (Zia) | Unified calendar across channels; approval stages; Zia subject lines and best send time; WhatsApp + Instagram native | Weak link to inventory and purchases |
| Mailchimp | Simple audiences with tags and segments; frequency caps; A/B tests; clear campaign reports | Email-first; no ERP |
| Odoo 19 (Marketing Automation, Social, SMS, WhatsApp) | Campaigns built from ERP records (domain filters on any model); WhatsApp templates synced from Meta; social calendar; UTM tracking to sales | Rules are technical (domain filters); little AI; no proactive suggestions |
| Hootsuite / Buffer / Later | Content calendar, best time to post, approval flows, comment inbox, post metrics | No customers, no orders |

The standard building blocks that recur everywhere:
1. **One contact record** with consent per channel (opt-in source and time, opt-out).
2. **Audiences**: saved, rule-based and live, plus static snapshots at send time.
3. **Campaign object**: goal, audience, channels, content, schedule, budget, owner, status, results.
4. **Content calendar** across channels, with drafts, approvals and scheduling.
5. **Journeys/automation**: trigger → conditions → waits → actions, with re-entry rules.
6. **Templates** (WhatsApp needs Meta-approved templates for anything outside 24 hours).
7. **Engagement inbox**: comments and replies in one place.
8. **Analytics + attribution**: delivered/read/clicked/replied → enquiries → orders → revenue.
9. **AI**: copy, images, send time, segments, next best action, and weekly insights.
10. **Guardrails**: frequency caps, quiet hours, approval before publishing, audit trail.

### Platform rules that shape the design (checked Nov 2026)

**Instagram (Graph API, Instagram Business/Creator account).**
- Publishing is two steps. First create a media container from a **public image URL** (JPEG), then call `media_publish`.
- Containers expire after 24 hours.
- Publishing is capped per account per rolling 24 hours. Meta's own pages say 50 in one place and 100 in another, so we read the account's live quota from `content_publishing_limit` and enforce it.
- Insights cover reach, impressions/views, likes, comments, saved and shares. Comments can be read, replied to and hidden through the API.
- There is no DM marketing.
- Consequence for us: generated images must be served at a public, unguessable URL from our own server.

**WhatsApp Cloud API.**
- Promotional messages outside a customer's 24-hour reply window must use a **Meta-approved MARKETING template**, sent only to opted-in users.
- Meta adapts how many marketing templates one person receives. Some messages are not delivered (error 131049, per-user marketing limit), and that must not count as our failure.
- Pricing is per delivered marketing message (India about $0.011–0.012).
- Portfolio messaging tiers start at 250 unique users per 24 hours.
- Delivery, read and failure statuses arrive on the webhook. An opt-out ("STOP") must be honoured.

## 2. What we already have (reuse, don't duplicate)

| Need | Existing piece |
|---|---|
| Contacts | `Customer` (phone, email, GSTIN, contacts, addresses), `CustomerEnquiry` (leads), portal link |
| Segments | `CustomerGroup` smart rules + manual members (`services/groups.py`) |
| Behaviour data | orders, deliveries, enquiries, payments, `insights.py` (RFM-like stats, dormant, reorder gap), batches/expiry, stock ageing |
| WhatsApp | Cloud API settings (encrypted token, WABA id, templates status), `outbox` queue + approvals, inbound webhook, TAI agent |
| AI | Gemini via `ai/provider.py` (scripted dev mode for tests), Settings → AI model/key |
| Automation | Flow editor + `automation_config` schemas + `triggers.py` engine ticking in `background.py` |
| Outreach | `trigger_outreach` (dormant, reorder due, quotes, back in stock, groups, slow stock) — becomes a marketing trigger |
| Approvals | `OutboundMessage` hold/approve; flow step modes auto/limits/approval/off |
| Secrets | `integration_settings` Fernet-encrypted credentials |
| Audit | `controls.log` audit log |

## 3. Module map (sections)

1. **Marketing home (dashboard)**
   - Opportunities found by the agents ("what to promote this week"), each with one-click *Create campaign*.
   - Active campaigns with their health.
   - Reach, engagement, enquiries and orders from campaigns, revenue and ROI.
   - The channel comparison and the approval queue.
2. **Campaigns**
   - List with filters: status, channel, objective, search.
   - Detail tabs: Plan (goal, products, offer, dates, budget), Audience (rule + live count + who is excluded and why), Content (Instagram post and WhatsApp message variants, AI-generated, editable), Approval, Activity (execution log), Results (funnel + orders attributed).
   - Lifecycle: draft → in review → approved → scheduled → running → completed, or paused / cancelled / failed.
3. **Calendar**: month and week view of scheduled Instagram posts and WhatsApp broadcasts. Click to open; drag to reschedule.
4. **AI Studio**
   - Generate campaign ideas, captions, hashtags, WhatsApp copy and product creatives (designed cards, or Gemini images).
   - Brand kit: colours, logo, tone, words to avoid, signature, default hashtags.
   - Saved assets library.
5. **Audiences**
   - Saved audiences built from rules over ERP data: group membership, bought product or category, spend, last order, dormant days, enquiry open, city, outstanding, birthday or anniversary this week, opted-in channel.
   - Live count and preview; reuses customer groups.
6. **Channels**
   - Instagram: connect, account info, publishing quota, posts with metrics, comments inbox (reply/hide).
   - WhatsApp marketing: templates (sync from Meta, create with AI, approval status), consent overview, opt-outs, sending limits.
7. **Automations (marketing rules)**
   - Trigger + conditions + action + approval policy + cooldown.
   - Triggers: new product, back in stock, excess / aged stock, batch near expiry, new category, festival/season approaching, customer inactive N days, birthday/anniversary, new enquiry, purchase made (thank-you / cross-sell after N days), declining product sales, segment interest rising, scheduled date.
   - Actions: suggest an opportunity, draft a campaign (audience + content), draft an Instagram post, draft a WhatsApp broadcast, create a follow-up task, send a 1:1 personalised message (within approval policy).
8. **Analytics**
   - Funnel per campaign and channel: sent → delivered → read → replied → enquiry → order → revenue.
   - ROI against cost: message cost estimate + spend entered.
   - Best time / day; top products promoted; post performance; inactive-customer trend.
   - The Analyst agent's weekly summary.
9. **Consent & compliance** (cross-cutting)
   - Per-customer, per-channel marketing consent with source, time and evidence.
   - Global opt-out keywords; frequency cap (max N marketing messages per customer per X days); quiet hours.
   - Suppression list; every send logged.

## 4. AI agents (coordinated, permission-bound)

Agents never hold "send" or "publish" tools. They produce **records** (opportunities, campaign drafts, content, replies). A deterministic **executor** publishes or sends only an approved campaign, and only when the approval policy allows. This is the same pattern as TAI/PAI with outbox approvals.

| Agent | Runs when | Reads | Produces |
|---|---|---|---|
| **Strategist** | daily scan + on triggers | sales trends, stock age, batches near expiry, new products, back-in-stock, dormant customers, festivals, margins | `MarketingOpportunity` (why, products, audience rule, channel and timing suggestion, expected value) |
| **Creative** | when a campaign needs content | brand kit, product details/specs/prices, audience, past winners | caption, hashtags, WhatsApp template text + variables, image (designed card or Gemini image) — editable versions |
| **Execution** (deterministic, not LLM) | every tick | approved schedule | Instagram containers + publish, WhatsApp template sends with throttling, retries, idempotency, logs |
| **Engagement** | inbound replies, Instagram comments, dormant customers | customer history, campaign context | reply drafts, personalised follow-up messages, follow-up tasks; replies with buying intent hand over to TAI (enquiry/order) |
| **Analyst** | weekly + campaign end | metrics + attributed orders | campaign health, winners/losers, recommendations → new opportunities |

All agents run in scripted mode when no Gemini key is set (tests, dev), with deterministic, clearly labelled output. With a key they use the configured Gemini model (images use a Gemini image model).

## 5. Data model (new tables)

- `marketing_consents`: customer_id, channel (whatsapp/email/sms), status (opted_in/opted_out), source (portal, whatsapp keyword, manual, import, enquiry form), evidence, at. Latest row wins; unique per (customer, channel).
- Customer gains `birthday`, `anniversary`, `city`, `tags`.
- `marketing_audiences`: name, rules JSON, group_ids, exclude rules; live.
- `marketing_campaigns`: name, objective (awareness / sales / clearance / reactivation / launch / festival / loyalty), status, channels, audience_id or rules snapshot, product_ids, offer text, start/end, budget, cost, owner (person/agent), opportunity_id, approved_by/at, utm code, metrics cache.
- `marketing_contents`: campaign_id, channel, kind (instagram_post / whatsapp_message), caption, hashtags, template name + variables, media_id, version, status, ai_generated, scheduled_at.
- `marketing_media`: bytes in DB (Render has no disk), mime, width/height, public token (`/api/public/media/{token}.jpg`), source (upload / card / gemini), prompt.
- `marketing_sends`: campaign × customer. Unique per (campaign, customer). Status: queued, sent, delivered, read, replied, failed, skipped (reason). wamid, cost, error, timestamps.
- `instagram_posts`: content_id, campaign_id, status (scheduled / publishing / published / failed), container id, media id, permalink, scheduled_at, published_at, metrics JSON, synced_at, attempts, error.
- `instagram_comments`: post, comment id, user, text, at, reply text, replied_at, hidden.
- `whatsapp_templates`: name, language, category, status (APPROVED / PENDING / REJECTED), body, variables, header, synced_at.
- `marketing_rules`: name, trigger, conditions, action, approval (auto / approval), cooldown, active, last_run.
- `marketing_opportunities`: kind, title, why, data JSON, product_ids, audience rules, suggested channel/time, score, status (new / accepted / dismissed / done), campaign_id, dedupe key.
- `marketing_conversions`: campaign_id, customer_id, order_id / enquiry_id, value, model (last touch within N days, or a direct reply), at.
- `marketing_events`: execution log (campaign_id, kind, message, data, at).
- Settings: integration `instagram` (account id, encrypted token, graph version); `marketing` settings (brand kit, frequency cap, quiet hours, attribution days, opt-out words, festival calendar, approval policy, per-message cost).

## 6. Integrations

- **Instagram**: Graph API (`graph.facebook.com/{v}/{ig-user-id}`).
  - Endpoints: `/media` (image_url, caption), `/media_publish`, `/content_publishing_limit`, `/{media}/insights`, `/{media}/comments`, `/{comment}/replies`, `/{comment}?hide=`.
  - The client is a small class with a fake for tests. Expired or invalid tokens (error 190) mark the connection broken and show it on the dashboard; publishing then pauses rather than failing silently.
- **WhatsApp**: existing `send_template` plus `GET/POST /{waba}/message_templates`.
  - Webhook statuses (sent/delivered/read/failed) update `marketing_sends` by wamid.
  - Inbound "STOP / UNSUBSCRIBE / बंद" records an opt-out. A reply to a campaign marks it replied and opens an engagement thread for TAI.
  - Throttle: N sends per tick within the messaging tier. Error 131049 (per-user marketing limit) is recorded as "not delivered by WhatsApp" and never retried.
- **Attribution**:
  - The portal link carries `?c=<campaign code>`.
  - Replies to a campaign are linked to it.
  - An order or enquiry from a recipient within N days of delivery is attributed to that campaign (last touch). Each conversion is shown with why it was counted.

## 7. API (all under `/api/marketing`)

- `dashboard`, `opportunities` (+ accept / dismiss / scan)
- `campaigns` CRUD, plus:
  - `/{id}/audience/preview`, `/{id}/generate` (content), `/{id}/submit`, `/{id}/approve`, `/{id}/schedule`, `/{id}/pause`, `/{id}/cancel`
  - `/{id}/sends`, `/{id}/results`, `/{id}/events`
- `contents/{id}` (edit, regenerate, image)
- `media` (upload, generate card / AI image), `/api/public/media/{token}.jpg`
- `audiences` CRUD + `preview`
- `calendar?from&to`
- `instagram/status | posts | sync | comments | comments/{id}/reply | hide`
- `whatsapp/templates` (sync, create) and `consents` (list, set, import)
- `rules` CRUD + `run`
- `analytics?from&to&channel`
- `settings` (brand kit, policies)

## 8. Background jobs (added to `background.py` JOBS)

- `marketing.tick` (every minute):
  - publish due Instagram posts;
  - send due WhatsApp batches (throttled);
  - finish completed campaigns;
  - run due rules.
- `marketing.scan` (hourly with a daily cap): the Strategist finds opportunities, deduplicated by key.
- `marketing.sync` (every 2 hours): Instagram insights + comments, template statuses, attribution recompute.

**Idempotency**:
- unique sends per (campaign, customer);
- posts move to `publishing` with a row lock before calling Meta;
- the container id is stored so a retry publishes the same container;
- opportunity dedupe keys.

## 9. Permissions and safety

- **Approval policy** (Settings → Marketing):
  - Instagram posts and WhatsApp broadcasts need approval by default.
  - Optional auto-approve for audiences ≤ N customers, or for rules marked "auto".
  - AI-created items always start as drafts.
- **Never send to**: anyone without opt-in consent for that channel; anyone opted out; anyone over the frequency cap; anyone during quiet hours (the send is deferred, not dropped).
- **Logging**: every external action is logged as a `marketing_events` entry plus the audit log. Tokens are encrypted and never returned to the browser.

## 10. Roadmap

| Slice | Contents | Kind |
|---|---|---|
| **M1 Foundation** | consent + customer fields, audiences, campaigns, contents, media + public URL, sends, events, settings/brand kit, campaign API | essential |
| **M2 WhatsApp marketing** | templates sync/create, broadcast executor with consent, frequency cap, quiet hours, throttle, statuses webhook, opt-out keywords, replies → engagement | essential |
| **M3 Instagram** | connect, publish (scheduled), quota, insights + comments sync, reply / hide | essential |
| **M4 AI agents** | Creative (copy + designed product cards + Gemini images), Strategist opportunities, Engagement replies, Analyst summary | essential / advanced |
| **M5 Automations + analytics** | marketing rules (all triggers), attribution, funnel and ROI analytics, calendar | advanced |
| **M6 UI** | Marketing section: Home, Campaigns, Calendar, Studio, Audiences, Instagram, WhatsApp, Automations, Analytics; Settings → Marketing | essential |
| Later | email channel campaigns, A/B tests, Facebook page, paid ads (Meta Ads API), landing pages, send-time optimisation per customer, festival creative packs | future |
