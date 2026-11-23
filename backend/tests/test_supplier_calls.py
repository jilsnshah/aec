"""The purchasing agent on the phone: sends the purchase enquiry by calling,
records each supplier's offer, and never orders -- the offer is picked after."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import PurchaseOrder, SupplierQuote, SupplierQuoteRequest
from app.services import outbox, supplier_calls
from app.voice.tools import CallTools

from .test_triggers import ALL_DAY, set_step

WINDOW = {k: v for k, v in ALL_DAY.items() if k != "days"}


@pytest.fixture()
def phone(monkeypatch, session_factory):
    from app.services import inbound

    monkeypatch.setattr(inbound, "session_factory", session_factory)
    calls = []
    monkeypatch.setattr(supplier_calls, "_place", lambda to, mode, params: calls.append((to, mode, params)))
    monkeypatch.setattr(outbox, "_send_whatsapp", lambda session, to, body: "wamid.1")
    return calls


def _rfq(client, db, make_product, make_supplier, make_customer, order_for, last_cost="330"):
    mill = make_supplier("Mill A", phone="9000000011")
    cement = make_product("Cement", opening_stock=10, opening_unit_cost=last_cost, mrp="400")
    client.patch("/api/products/{}".format(cement.id), json={"reorder_level": "50", "preferred_supplier_id": str(mill.id), "lead_time_days": 2})
    po = client.post("/api/purchase-orders", json={"supplier_id": str(mill.id), "confirm": True,
                                                   "items": [{"product_id": str(cement.id), "quantity_ordered": "1", "unit_cost": last_cost}]}).json()
    client.post("/api/goods-receipts", json={"purchase_order_id": po["id"], "lines": [{"purchase_order_item_id": po["items"][0]["id"], "quantity": "1"}]})
    db.expire_all()
    order_for(make_customer("Builder"), cement, 30)
    set_step(client, "purchase", "purchase.need_detected", {"schedule": ALL_DAY})
    set_step(client, "purchase", "purchase.choose_supplier", {"quantity": {"method": "up_to_reorder", "round_to_purchase_unit": False},
                                                              "suppliers": {"who": "preferred"}})
    return mill, cement


def _ask_by(client, how, **extra):
    set_step(client, "purchase", "purchase.ask_supplier", {**WINDOW, "wait_hours": 6, "how": how, **extra}, actors=["tai", "pai"], mode="auto")


def _tools(session_factory, quote_id):
    tools = CallTools(session_factory, "+919000000011")
    tools.quote_id = quote_id
    return tools


def test_agent_calls_instead_of_texting_and_records_the_quote(client, db, session_factory, phone, make_product, make_supplier, make_customer, order_for):
    mill, cement = _rfq(client, db, make_product, make_supplier, make_customer, order_for)
    _ask_by(client, "call")
    result = client.post("/api/automation/run/purchase").json()
    assert result["asked"] == 0  # nobody texted
    supplier_calls.run_quote_calls(db)
    assert phone and phone[0][1] == "supplier_quote"
    quote = db.execute(select(SupplierQuote)).scalars().one()
    db.refresh(quote)
    assert quote.status == "calling" and quote.call_attempts == 1
    brief = supplier_calls.quote_brief(db, quote.id)
    assert "1. Cement" in brief and "last price was Rs 330" in brief
    out = _tools(session_factory, quote.id).run("record_quote", {"lines": [{"item": 1, "price": 345}], "delivery_days": 2, "freight": 0, "gst_included": False})
    assert out["recorded"] and "can_order" not in out
    db.expire_all()
    quote = db.get(SupplierQuote, quote.id)
    assert quote.status == "replied" and quote.channel == "call" and quote.lines[0].price == Decimal("345") and quote.delivery_days == 2


def test_agent_never_orders_on_the_call(client, db, session_factory, phone, make_product, make_supplier, make_customer, order_for):
    _rfq(client, db, make_product, make_supplier, make_customer, order_for)
    _ask_by(client, "call")
    set_step(client, "purchase", "purchase.compare_quotes", mode="approval", limits=[])
    client.post("/api/automation/run/purchase")
    supplier_calls.run_quote_calls(db)
    quote = db.execute(select(SupplierQuote)).scalars().one()
    tools = _tools(session_factory, quote.id)
    tools.run("record_quote", {"lines": [{"item": 1, "price": 345}], "delivery_days": 3})  # higher than last time: still only an offer
    assert "order_now" not in {d.name for d in __import__("app.voice.tools", fromlist=["x"]).SUPPLIER_QUOTE_DECLARATIONS}
    db.expire_all()
    supplier_calls.quote_call_ended(db, quote.id, "")
    db.expire_all()
    rfq = db.execute(select(SupplierQuoteRequest)).scalars().one()
    assert rfq.status == "to_choose" and db.execute(select(PurchaseOrder).where(PurchaseOrder.enquiry_id == rfq.id)).first() is None
    assert db.get(SupplierQuote, quote.id).lines[0].price == Decimal("345")


def test_unanswered_calls_retry_then_stop(client, db, phone, make_product, make_supplier, make_customer, order_for):
    _rfq(client, db, make_product, make_supplier, make_customer, order_for)
    _ask_by(client, "call", call_tries=2)
    client.post("/api/automation/run/purchase")
    supplier_calls.run_quote_calls(db)
    quote = db.execute(select(SupplierQuote)).scalars().one()
    supplier_calls.quote_call_ended(db, quote.id, "No answer")
    db.refresh(quote)
    assert quote.status == "asked"
    supplier_calls.run_quote_calls(db)
    assert len(phone) == 1  # waits before trying again
    quote.last_call_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()
    supplier_calls.run_quote_calls(db)
    assert len(phone) == 2
    db.refresh(quote)
    quote.status, quote.last_call_at = "asked", datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()
    supplier_calls.run_quote_calls(db)
    assert len(phone) == 2  # two tries were allowed


def test_text_first_then_call(client, db, phone, make_product, make_supplier, make_customer, order_for):
    _rfq(client, db, make_product, make_supplier, make_customer, order_for)
    _ask_by(client, "text_then_call", call_after_hours=2)
    assert client.post("/api/automation/run/purchase").json()["asked"] == 1
    supplier_calls.run_quote_calls(db)
    assert phone == []  # the WhatsApp has not had time yet
    quote = db.execute(select(SupplierQuote)).scalars().one()
    quote.asked_at = datetime.now(timezone.utc) - timedelta(hours=3)
    db.commit()
    supplier_calls.run_quote_calls(db)
    assert len(phone) == 1


def test_agents_catalogue_and_steps(client):
    data = client.get("/api/automation/agents").json()
    keys = {a["key"]: a for a in data["agents"]}
    assert keys["purchasing"]["mediums"] == ["text", "phone"] and keys["logistics"]["parked"]
    assert any(s["key"] == "purchase.ask_supplier" for s in keys["purchasing"]["steps"])
    lib = {s["key"]: s for s in client.get("/api/automation/library").json()["steps"]}
    assert lib["purchase.ask_supplier"]["agent"] == "purchasing" and lib["sales.payment_reminders"]["agent_label"] == "Collections agent"
    saved = client.put("/api/automation/agents", json={"profiles": {"purchasing": {"name": "Ravi", "voice": "Puck", "instructions": "Always ask for the mill test certificate."}}}).json()
    p = next(a for a in saved["agents"] if a["key"] == "purchasing")
    assert p["name"] == "Ravi" and p["voice"] == "Puck"
    assert client.put("/api/automation/agents", json={"profiles": {"nobody": {}}}).status_code == 422
