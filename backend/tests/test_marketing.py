"""Marketing: consent, audiences, campaigns, WhatsApp broadcasts, Instagram
publishing, agents, automations and attribution."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
import pytest
from sqlalchemy import select

from app.models import (
    InstagramComment, MarketingCampaign, MarketingContent, MarketingConversion, MarketingOpportunity, MarketingSend, WhatsappTemplate,
)
from app.services import (
    inbound, instagram, marketing, marketing_agents, marketing_audiences, marketing_channels, marketing_media, marketing_policy,
    marketing_rules, whatsapp,
)


class FakeMeta:
    """WhatsApp Cloud API and Instagram Graph API, enough for marketing."""

    def __init__(self) -> None:
        self.sent: List[dict] = []
        self.ig_calls: List[str] = []
        self.containers = 0
        self.published = 0
        self.fail_send: Optional[dict] = None
        self.ig_error: Optional[dict] = None
        self.quota_used = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/messages"):
            if self.fail_send:
                return httpx.Response(400, json={"error": self.fail_send})
            body = json.loads(request.content)
            self.sent.append(body)
            return httpx.Response(200, json={"messages": [{"id": "wamid.{}".format(len(self.sent))}]})
        if path.endswith("/message_templates") and request.method == "GET":
            return httpx.Response(200, json={"data": [
                {"id": "t1", "name": "offer_update", "language": "en", "status": "APPROVED", "category": "MARKETING",
                 "components": [{"type": "BODY", "text": "Hi {{1}}, {{2}} Reply STOP to stop offers."}, {"type": "FOOTER", "text": "Labdhi"}]},
                {"id": "t2", "name": "order_confirmation", "language": "en", "status": "APPROVED", "category": "UTILITY",
                 "components": [{"type": "BODY", "text": "Order {{1}} confirmed."}]},
                {"id": "t3", "name": "diwali_photo", "language": "en", "status": "PENDING", "category": "MARKETING",
                 "components": [{"type": "HEADER", "format": "IMAGE"}, {"type": "BODY", "text": "Happy Diwali {{1}}!"}]},
            ]})
        if path.endswith("/message_templates") and request.method == "POST":
            return httpx.Response(200, json={"id": "t9", "status": "PENDING", "category": "MARKETING"})
        # Instagram
        self.ig_calls.append("{} {}".format(request.method, path))
        if self.ig_error:
            return httpx.Response(400, json={"error": self.ig_error})
        if path.endswith("/content_publishing_limit"):
            return httpx.Response(200, json={"data": [{"config": {"quota_total": 50}, "quota_usage": self.quota_used}]})
        if path.endswith("/media") and request.method == "POST":
            self.containers += 1
            assert request.url.params["image_url"].startswith("https://erp.example.com/api/public/media/")
            return httpx.Response(200, json={"id": "container-{}".format(self.containers)})
        if path.endswith("/media_publish"):
            self.published += 1
            return httpx.Response(200, json={"id": "ig-media-{}".format(self.published)})
        if path.endswith("/insights"):
            return httpx.Response(200, json={"data": [{"name": "reach", "values": [{"value": 420}]}, {"name": "saved", "values": [{"value": 7}]}]})
        if path.endswith("/comments"):
            return httpx.Response(200, json={"data": [
                {"id": "c1", "text": "What is the price per bag?", "username": "builder_raj", "timestamp": "2026-11-20T08:00:00+0000"},
                {"id": "c2", "text": "Nice 🔥", "username": "anita", "timestamp": "2026-11-20T09:00:00+0000"},
            ]})
        if path.endswith("/replies"):
            return httpx.Response(200, json={"id": "reply-1"})
        if "container-" in path:
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if "ig-media-" in path:
            return httpx.Response(200, json={"like_count": 31, "comments_count": 2, "permalink": "https://instagram.com/p/abc"})
        return httpx.Response(200, json={"username": "labdhi_exim", "name": "Labdhi Exim", "followers_count": 1200, "media_count": 40})


@pytest.fixture()
def meta(session_factory, monkeypatch):
    fake = FakeMeta()
    monkeypatch.setattr(inbound, "session_factory", session_factory)
    monkeypatch.setattr(whatsapp, "http_factory", lambda: httpx.Client(transport=httpx.MockTransport(fake)))
    monkeypatch.setattr(instagram, "http_factory", lambda: httpx.Client(transport=httpx.MockTransport(fake)))
    monkeypatch.setattr(marketing_policy, "quiet_now", lambda cfg, now=None: False)
    monkeypatch.setattr(marketing_agents, "llm_json", None)
    return fake


def connect(client, instagram_too: bool = False, **marketing_cfg):
    r = client.put("/api/integrations/whatsapp", json={
        "enabled": True, "config": {"phone_number_id": "1098765432", "verify_token": "v", "business_account_id": "WABA"},
        "credentials": {"access_token": "meta-token"}})
    assert r.status_code == 200, r.text
    r = client.put("/api/integrations/marketing", json={"config": {"public_url": "https://erp.example.com", "brand_name": "Labdhi Exim", **marketing_cfg}})
    assert r.status_code == 200, r.text
    if instagram_too:
        r = client.put("/api/integrations/instagram", json={"enabled": True, "config": {"ig_user_id": "17841400000000"},
                                                            "credentials": {"access_token": "ig-token"}})
        assert r.status_code == 200, r.text
    r = client.post("/api/marketing/whatsapp/templates/sync")
    assert r.status_code == 200, r.text


def opt_in(client, *customers, evidence="Agreed at the counter"):
    r = client.post("/api/marketing/consents", json={"customer_ids": [str(c.id) for c in customers], "status": "opted_in", "evidence": evidence})
    assert r.status_code == 200, r.text


def whatsapp_campaign(client, customers, **extra) -> Dict[str, Any]:
    r = client.post("/api/marketing/campaigns", json={"name": "Cement week", "objective": "sales", "channels": ["whatsapp"],
                                                     "audience": {"only": [str(c.id) for c in customers]}, "offer": "Free delivery above 100 bags", **extra})
    assert r.status_code == 201, r.text
    campaign = r.json()
    r = client.post("/api/marketing/campaigns/{}/contents".format(campaign["id"]), json={
        "channel": "whatsapp", "template_name": "offer_update", "template_language": "en", "variables": ["{first_name}", "{offer}"]})
    assert r.status_code == 201, r.text
    return client.get("/api/marketing/campaigns/{}".format(campaign["id"])).json()


# ---------------------------------------------------------------------------
# Consent and audiences
# ---------------------------------------------------------------------------


def test_consent_needs_evidence_and_controls_who_can_be_messaged(client, db, meta, make_customer):
    connect(client)
    a = make_customer("Asha Builders", phone="9800000001")
    b = make_customer("Bharat Infra", phone="9800000002")
    c = make_customer("No Phone Traders")
    r = client.post("/api/marketing/consents", json={"customer_ids": [str(a.id)], "status": "opted_in"})
    assert r.status_code == 422 and "how the customer agreed" in r.text
    opt_in(client, a, c)
    reasons = marketing_policy.eligibility(db, "whatsapp", [a.id, b.id, c.id])
    assert reasons[a.id] is None
    assert reasons[b.id] == "No marketing consent"
    assert reasons[c.id] == "No phone number"
    listing = client.get("/api/marketing/consents").json()
    assert listing["totals"]["opted_in"] == 2


def test_audience_rules_products_and_preview(client, db, meta, make_customer, make_product, order_for):
    connect(client)
    cement = make_product("Cement OPC 53", opening_stock=100, category="Cement")
    sand = make_product("River sand", opening_stock=50, category="Aggregates")
    a = make_customer("Cement Buyer", phone="9811111111")
    b = make_customer("Sand Buyer", phone="9822222222")
    make_customer("Never Bought", phone="9833333333")
    db.expire_all()
    order_for(a, cement, 5)
    order_for(b, sand, 2)
    ids = marketing_audiences.resolve(db, {"products": {"ids": [str(cement.id)], "mode": "bought"}})
    assert ids == [a.id]
    ids = marketing_audiences.resolve(db, {"categories": {"names": ["Cement"], "mode": "not_bought"}})
    assert a.id not in ids and b.id in ids
    opt_in(client, a)
    r = client.post("/api/marketing/audiences/preview", json={"definition": {"rules": [{"field": "orders_total", "op": ">=", "value": 1}]},
                                                            "channels": ["whatsapp"]})
    body = r.json()
    assert body["count"] == 2 and body["reach"]["whatsapp"]["reachable"] == 1
    assert body["reach"]["whatsapp"]["blocked"] == {"No marketing consent": 1}
    saved = client.post("/api/marketing/audiences", json={"name": "Cement buyers", "definition": {"categories": {"names": ["Cement"]}}}).json()
    assert saved["last_count"] == 1 and "bought Cement" in saved["summary"]


def test_birthday_audience(db, make_customer):
    today = datetime.now(timezone.utc).date()
    soon = make_customer("Birthday Soon")
    soon.birthday = date(1980, (today + timedelta(days=2)).month, (today + timedelta(days=2)).day)
    db.commit()
    later = make_customer("Birthday Later")
    later.birthday = date(1980, (today + timedelta(days=40)).month, (today + timedelta(days=40)).day)
    db.commit()
    assert marketing_audiences.resolve(db, {"occasion": {"kind": "birthday", "within_days": 7}}) == [soon.id]


# ---------------------------------------------------------------------------
# WhatsApp broadcast
# ---------------------------------------------------------------------------


def test_whatsapp_campaign_needs_approval_then_sends_once_per_customer(client, db, meta, make_customer):
    connect(client)
    a = make_customer("Asha Builders", phone="9800000001")
    b = make_customer("Bharat Infra", phone="9800000002")
    c = make_customer("Chetan (no consent)", phone="9800000003")
    campaign = whatsapp_campaign(client, [a, b, c])
    preview = campaign["contents"][0]["preview"]
    assert preview["text"] == "Hi Customer, Free delivery above 100 bags Reply STOP to stop offers."
    # Nobody consented yet: approval is blocked.
    r = client.post("/api/marketing/campaigns/{}/submit".format(campaign["id"]))
    assert r.status_code == 422 and "agreed to WhatsApp marketing" in r.text
    opt_in(client, a, b)
    assert client.post("/api/marketing/campaigns/{}/submit".format(campaign["id"])).json()["status"] == "review"
    # Nothing goes out before approval.
    marketing.tick(db)
    assert meta.sent == []
    approved = client.post("/api/marketing/campaigns/{}/approve".format(campaign["id"])).json()
    assert approved["status"] == "approved" and approved["approved_by"] == "tester"
    result = marketing.tick(db)
    assert result["sent"] == 2
    to = sorted(m["to"] for m in meta.sent)
    assert to == ["919800000001", "919800000002"]
    params = [p["text"] for p in meta.sent[0]["template"]["components"][0]["parameters"]]
    assert params[0] in ("Asha", "Bharat") and params[1] == "Free delivery above 100 bags"
    # Running again sends nothing more.
    marketing.tick(db)
    assert len(meta.sent) == 2
    sends = client.get("/api/marketing/campaigns/{}/sends".format(campaign["id"])).json()["items"]
    skipped = [s for s in sends if s["status"] == "skipped"]
    assert len(skipped) == 1 and skipped[0]["skip_reason"] == "No marketing consent"
    view = client.get("/api/marketing/campaigns/{}".format(campaign["id"])).json()
    assert view["status"] == "completed" and view["funnel"]["sent"] == 2


def test_statuses_replies_opt_out_and_attribution(client, db, meta, make_customer, make_product, order_for):
    connect(client)
    product = make_product("Cement", opening_stock=100)
    a = make_customer("Asha Builders", phone="9800000001")
    b = make_customer("Bharat Infra", phone="9800000002")
    opt_in(client, a, b)
    campaign = whatsapp_campaign(client, [a, b])
    client.post("/api/marketing/campaigns/{}/submit".format(campaign["id"]))
    client.post("/api/marketing/campaigns/{}/approve".format(campaign["id"]))
    marketing.tick(db)
    sends = {s.customer_id: s for s in db.execute(select(MarketingSend)).scalars()}
    payload = {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "1098765432"}, "statuses": [
        {"id": sends[a.id].wamid, "status": "delivered", "timestamp": "1790000000"},
        {"id": sends[a.id].wamid, "status": "read", "timestamp": "1790000100", "pricing": {"billable": True}},
        {"id": sends[b.id].wamid, "status": "failed", "timestamp": "1790000000", "errors": [{"code": 131049, "title": "Per-user marketing limit"}]},
    ]}}]}]}
    marketing.on_statuses(db, whatsapp.parse_statuses(payload, "1098765432"))
    db.expire_all()
    assert db.get(MarketingSend, sends[a.id].id).status == "read"
    assert "131049" in db.get(MarketingSend, sends[b.id].id).error
    # A reply marks the message replied; STOP opts out.
    assert marketing.on_inbound(db, a, "Yes please send 200 bags") is None
    assert db.get(MarketingSend, sends[a.id].id).status == "replied"
    assert marketing.on_inbound(db, b, "STOP") == "opt_out"
    assert marketing_policy.consent_of(db, b.id)["whatsapp"]["status"] == "opted_out"
    # An order after the message counts for the campaign.
    db.expire_all()
    order_for(a, product, 10)
    assert marketing.attribute(db) == 1
    conv = db.execute(select(MarketingConversion)).scalar_one()
    assert conv.reason == "reply" and conv.customer_id == a.id
    assert marketing.attribute(db) == 0
    results = client.get("/api/marketing/campaigns/{}".format(campaign["id"])).json()
    assert results["conversions"]["orders"] == 1 and results["funnel"]["replied"] == 1


def test_frequency_cap_and_consent_rechecked_at_send_time(client, db, meta, make_customer):
    connect(client, frequency_max=1, frequency_days=7)
    a = make_customer("Asha Builders", phone="9800000001")
    opt_in(client, a)
    first = whatsapp_campaign(client, [a])
    client.post("/api/marketing/campaigns/{}/submit".format(first["id"]))
    client.post("/api/marketing/campaigns/{}/approve".format(first["id"]))
    marketing.tick(db)
    assert len(meta.sent) == 1
    second = whatsapp_campaign(client, [a], name="Second")
    r = client.post("/api/marketing/campaigns/{}/submit".format(second["id"]))
    assert r.status_code == 422  # nobody reachable: capped
    sends = marketing_policy.eligibility(db, "whatsapp", [a.id])
    assert sends[a.id].startswith("Already got 1 messages")


def test_meta_errors_retry_or_stop(client, db, meta, make_customer):
    connect(client)
    a = make_customer("Asha Builders", phone="9800000001")
    opt_in(client, a)
    campaign = whatsapp_campaign(client, [a])
    client.post("/api/marketing/campaigns/{}/submit".format(campaign["id"]))
    client.post("/api/marketing/campaigns/{}/approve".format(campaign["id"]))
    meta.fail_send = {"message": "Temporary", "code": 131000}
    marketing.tick(db)
    send = db.execute(select(MarketingSend)).scalar_one()
    assert send.status == "queued" and send.attempts == 1
    meta.fail_send = None
    marketing.tick(db)
    db.refresh(send)
    assert send.status == "sent" and len(meta.sent) == 1


def test_cancel_and_edit_rules(client, db, meta, make_customer):
    connect(client)
    a = make_customer("Asha Builders", phone="9800000001")
    opt_in(client, a)
    campaign = whatsapp_campaign(client, [a])
    client.post("/api/marketing/campaigns/{}/submit".format(campaign["id"]))
    # Editing while in review sends it back to draft.
    content_id = campaign["contents"][0]["id"]
    r = client.put("/api/marketing/contents/{}".format(content_id), json={"variables": ["{first_name}", "New offer"]})
    assert r.status_code == 200
    assert client.get("/api/marketing/campaigns/{}".format(campaign["id"])).json()["status"] == "draft"
    client.post("/api/marketing/campaigns/{}/submit".format(campaign["id"]))
    client.post("/api/marketing/campaigns/{}/approve".format(campaign["id"]))
    r = client.put("/api/marketing/contents/{}".format(content_id), json={"variables": ["x", "y"]})
    assert r.status_code == 409
    assert client.post("/api/marketing/campaigns/{}/cancel".format(campaign["id"])).json()["status"] == "cancelled"
    marketing.tick(db)
    assert meta.sent == []


# ---------------------------------------------------------------------------
# Instagram
# ---------------------------------------------------------------------------


def test_instagram_post_publishes_once_and_syncs(client, db, meta, make_product):
    connect(client, instagram_too=True)
    check = client.post("/api/marketing/instagram/check").json()
    assert check["username"] == "labdhi_exim" and check["quota"]["left"] == 50
    product = make_product("UltraTech OPC 53", opening_stock=500, brand="UltraTech")
    r = client.post("/api/marketing/campaigns", json={"name": "Launch", "objective": "launch", "channels": ["instagram"], "product_ids": [str(product.id)]})
    campaign = r.json()
    card = client.post("/api/marketing/media/product-card", json={"product_id": str(product.id), "offer": "Launch week price"}).json()
    assert card["public_url"].startswith("https://erp.example.com/api/public/media/")
    image = client.get(card["url"])
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
    r = client.post("/api/marketing/campaigns/{}/contents".format(campaign["id"]), json={
        "channel": "instagram", "caption": "Now in stock.", "hashtags": ["cement", "#Ahmedabad"], "media_id": card["id"]})
    assert r.json()["hashtags"] == ["#cement", "#Ahmedabad"]
    client.post("/api/marketing/campaigns/{}/submit".format(campaign["id"]))
    client.post("/api/marketing/campaigns/{}/approve".format(campaign["id"]))
    marketing.tick(db)
    content = db.execute(select(MarketingContent)).scalar_one()
    assert content.status == "published" and content.external_id == "ig-media-1" and content.permalink
    marketing.tick(db)
    assert meta.containers == 1 and meta.published == 1
    synced = marketing_channels.sync_instagram(db)
    assert synced == {"posts": 1, "comments": 2}
    db.refresh(content)
    assert content.metrics["reach"] == 420 and content.metrics["likes"] == 31
    comments = {c.username: c for c in db.execute(select(InstagramComment)).scalars()}
    assert comments["builder_raj"].intent == "buying" and comments["builder_raj"].reply_status == "draft"
    assert comments["anita"].intent == "praise"
    r = client.post("/api/marketing/instagram/comments/{}/reply".format(comments["builder_raj"].id), json={"text": "Please WhatsApp us!"})
    assert r.json()["reply_status"] == "sent"
    assert client.post("/api/marketing/instagram/comments/{}/reply".format(comments["builder_raj"].id), json={"text": "again"}).status_code == 409


def test_instagram_expired_token_pauses_without_failing(client, db, meta, make_product):
    connect(client, instagram_too=True)
    card = client.post("/api/marketing/media/card", json={"headline": "Diwali offer"}).json()
    campaign = client.post("/api/marketing/campaigns", json={"name": "Diwali", "channels": ["instagram"]}).json()
    client.post("/api/marketing/campaigns/{}/contents".format(campaign["id"]), json={"channel": "instagram", "caption": "Happy Diwali", "media_id": card["id"]})
    client.post("/api/marketing/campaigns/{}/submit".format(campaign["id"]))
    client.post("/api/marketing/campaigns/{}/approve".format(campaign["id"]))
    meta.ig_error = {"message": "Error validating access token", "code": 190}
    marketing.tick(db)
    content = db.execute(select(MarketingContent)).scalar_one()
    assert content.status == "scheduled" and "access token" in content.error
    problems = client.get("/api/marketing/events?level=error").json()["items"]
    assert any("reconnect Instagram" in p["message"] for p in problems)
    meta.ig_error = None
    marketing.tick(db)
    db.refresh(content)
    assert content.status == "published"


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def test_templates_sync_and_create(client, db, meta):
    connect(client)
    items = {t["name"]: t for t in client.get("/api/marketing/whatsapp/templates").json()["items"]}
    assert items["offer_update"]["variable_count"] == 2 and items["offer_update"]["footer"] == "Labdhi"
    assert items["diwali_photo"]["header"] == "IMAGE" and items["diwali_photo"]["status"] == "PENDING"
    r = client.post("/api/marketing/whatsapp/templates", json={"name": "New Stock", "body": "Hi {{1}}, {{2}} Thanks.", "examples": ["Ramesh"]})
    assert r.status_code == 422 and "example value" in r.text
    r = client.post("/api/marketing/whatsapp/templates", json={"name": "New Stock", "body": "Hi {{1}}, {{2}} Thanks.", "examples": ["Ramesh", "Fresh cement"]})
    assert r.status_code == 201 and r.json()["name"] == "new_stock" and r.json()["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Agents and automations
# ---------------------------------------------------------------------------


def test_strategist_finds_opportunities_and_accepting_drafts_a_campaign(client, db, meta, make_customer, make_product, order_for):
    connect(client)
    product = make_product("Paint 20L", opening_stock=40, category="Paint", track_batches=True)
    db.commit()
    from app.services import batches

    batch = batches.resolve(db, product, "P-77", None, datetime.now(timezone.utc).date() + timedelta(days=20), None)
    from app.models import StockCostLayer

    for layer in db.execute(select(StockCostLayer).where(StockCostLayer.product_id == product.id)).scalars():
        layer.batch_id = batch.id
    db.commit()
    a = make_customer("Asha Builders", phone="9800000001")
    db.expire_all()
    order_for(a, product, 2)
    found = client.post("/api/marketing/opportunities/scan").json()
    kinds = {o["kind"] for o in found["items"]}
    assert "near_expiry" in kinds
    again = client.post("/api/marketing/opportunities/scan").json()
    assert again["found"] == 0  # deduplicated
    opp = next(o for o in found["items"] if o["kind"] == "near_expiry")
    assert "expire within" in opp["why"] and opp["products"] == ["Paint 20L"]
    campaign = client.post("/api/marketing/opportunities/{}/accept".format(opp["id"]), json={"image": "card"}).json()
    assert campaign["status"] == "draft" and campaign["objective"] == "clearance"
    channels = {c["channel"]: c for c in campaign["contents"]}
    assert set(channels) == {"whatsapp", "instagram"}
    assert channels["whatsapp"]["template_name"] == "offer_update" and len(channels["whatsapp"]["variables"]) == 2
    assert channels["instagram"]["media"]["source"] == "card" and channels["instagram"]["caption"]
    assert db.get(MarketingOpportunity, __import__("uuid").UUID(opp["id"])).status == "accepted"
    # Accepting twice returns the same campaign.
    same = client.post("/api/marketing/opportunities/{}/accept".format(opp["id"]), json={}).json()
    assert same["id"] == campaign["id"]


def test_creative_uses_gemini_answer_when_connected(client, db, meta, make_product, monkeypatch):
    connect(client)
    product = make_product("Steel TMT 12mm", opening_stock=100, mrp="65")
    calls = []

    def fake_llm(session, system, prompt):
        calls.append(json.loads(prompt))
        return {"instagram": {"caption": "Strong bars for strong homes.", "hashtags": ["#TMT", "#Steel"],
                              "card": {"headline": "TMT 12mm", "subline": "Fe 500D", "badge": "New"}, "image_prompt": "steel bars"},
                "whatsapp": {"message": "Fresh TMT stock", "template": "offer_update", "values": ["{first_name}", "Fresh TMT 12mm at ₹65/kg"]}}

    monkeypatch.setattr(marketing_agents, "llm_json", fake_llm)
    campaign = client.post("/api/marketing/campaigns", json={"name": "TMT", "channels": ["instagram", "whatsapp"], "product_ids": [str(product.id)]}).json()
    out = client.post("/api/marketing/campaigns/{}/generate".format(campaign["id"]), json={"image": "card"}).json()
    by = {c["channel"]: c for c in out["contents"]}
    assert by["instagram"]["caption"] == "Strong bars for strong homes." and by["instagram"]["ai_generated"]
    assert by["whatsapp"]["variables"] == ["{first_name}", "Fresh TMT 12mm at ₹65/kg"]
    assert calls[0]["brief"]["products"][0]["name"] == "Steel TMT 12mm"


def test_ai_image_falls_back_to_card(client, db, meta, make_product, monkeypatch):
    connect(client)
    monkeypatch.setattr(marketing_media, "image_generator", None)
    monkeypatch.setattr(marketing_media.settings_service, "ai_credentials", lambda session=None: None)
    campaign = client.post("/api/marketing/campaigns", json={"name": "Festive", "objective": "festival", "channels": ["instagram"]}).json()
    out = client.post("/api/marketing/campaigns/{}/generate".format(campaign["id"]), json={"image": "ai"}).json()
    assert out["contents"][0]["media"]["source"] == "card"
    events = client.get("/api/marketing/events?campaign_id={}".format(campaign["id"])).json()["items"]
    assert any(e["kind"] == "image_fallback" for e in events)


def test_rules_inactive_customers_respect_cooldown_and_auto_policy(client, db, meta, make_customer, make_product, order_for):
    connect(client)
    product = make_product("Cement", opening_stock=100)
    a = make_customer("Quiet Customer", phone="9800000001")
    db.expire_all()
    for _ in range(2):
        order = order_for(a, product, 1)
    from app.models import SalesOrder

    for o in db.execute(select(SalesOrder)).scalars():
        o.created_at = datetime.now(timezone.utc) - timedelta(days=120)
    db.commit()
    opt_in(client, a)
    rules = client.get("/api/marketing/rules").json()
    assert len(rules["items"]) == len(marketing_rules.DEFAULT_RULES)
    rule = client.post("/api/marketing/rules", json={"name": "Win back now", "trigger": "inactive_customers", "conditions": {"days": 90, "min_orders": 2},
                                                     "action": "auto_campaign", "action_config": {"channels": ["whatsapp"]}, "cooldown_days": 30}).json()
    out = client.post("/api/marketing/rules/{}/run".format(rule["id"])).json()
    assert out["done"] and "needs approval: automatic approval is off" in out["done"][0]
    campaign = db.execute(select(MarketingCampaign).where(MarketingCampaign.created_by == "rule:{}".format(rule["id"]))).scalar_one()
    assert campaign.status == "review"
    # Switch automatic approval on: the next customer-group run goes out on its own...
    client.put("/api/integrations/marketing", json={"config": {"approval": "auto", "auto_max_audience": 10}})
    client.post("/api/marketing/campaigns/{}/approve".format(campaign.id))
    marketing.tick(db)
    assert len(meta.sent) == 1
    # ...but the same customer is not picked again within the cooldown.
    db.execute(MarketingOpportunity.__table__.delete())
    db.commit()
    out = client.post("/api/marketing/rules/{}/run".format(rule["id"])).json()
    assert out["done"] == []


def test_dashboard_analytics_calendar_and_ask(client, db, meta, make_customer):
    connect(client)
    a = make_customer("Asha Builders", phone="9800000001")
    opt_in(client, a)
    campaign = whatsapp_campaign(client, [a])
    client.post("/api/marketing/campaigns/{}/submit".format(campaign["id"]))
    client.post("/api/marketing/campaigns/{}/approve".format(campaign["id"]))
    marketing.tick(db)
    home = client.get("/api/marketing/dashboard").json()
    assert home["kpis"]["sent"] == 1 and home["consent"]["opted_in"] == 1
    assert home["connections"]["whatsapp"]["approved_templates"] == 1
    stats = client.get("/api/marketing/analytics?days=7").json()
    assert stats["funnel"]["sent"] == 1 and len(stats["series"]) == 7
    cal = client.get("/api/marketing/calendar").json()["items"]
    assert cal and cal[0]["channel"] == "whatsapp"
    answer = client.post("/api/marketing/ask", json={"question": "What should I promote this week?"}).json()
    assert "Gemini is not connected" in answer["answer"]
    review = client.post("/api/marketing/analyse").json()
    assert review["headline"].startswith("Last 30 days")


def test_public_media_needs_no_login_but_unknown_token_is_404(client, anonymous_client, db, meta):
    # (sign-in for /api/marketing is covered by the app-wide guard tests)
    connect(client)
    card = client.post("/api/marketing/media/card", json={"headline": "Hello"}).json()
    assert anonymous_client.get(card["url"]).status_code == 200
    assert anonymous_client.get("/api/public/media/not-a-token.jpg").status_code == 404


def test_automation_takes_over_the_strategists_opportunity(client, db, meta, make_product):
    connect(client)
    make_product("Fresh Cement", opening_stock=50, category="Cement")
    found = client.post("/api/marketing/opportunities/scan").json()
    assert any(o["kind"] == "new_product" for o in found["items"])
    rule = next(r for r in client.get("/api/marketing/rules").json()["items"] if r["trigger"] == "new_product")
    out = client.post("/api/marketing/rules/{}/run".format(rule["id"])).json()
    assert out["done"] and "drafted" in out["done"][0]
    opps = db.execute(select(MarketingOpportunity).where(MarketingOpportunity.kind == "new_product")).scalars().all()
    assert len(opps) == 1 and opps[0].status == "accepted" and opps[0].campaign_id
    # A later scan does not list it again.
    assert client.post("/api/marketing/opportunities/scan").json()["found"] == 0
    # Running the automation again does not make a second campaign.
    assert client.post("/api/marketing/rules/{}/run".format(rule["id"])).json()["done"] == []
    assert len(db.execute(select(MarketingCampaign)).scalars().all()) == 1
