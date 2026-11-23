"""The agents' text side with AI (purchasing replies, collections, customer
care, outreach) and the collections and care calls."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import CustomerFeedback, PurchaseOrder, SupplierQuote, SupplierQuoteRequest, Task
from app.services import agent_text, customer_agents, outbox, supplier_calls
from app.voice.tools import CallTools

from .test_supplier_calls import WINDOW, _rfq
from .test_triggers import ALL_DAY, set_step


@pytest.fixture()
def sent(monkeypatch, session_factory):
    from app.services import inbound

    monkeypatch.setattr(inbound, "session_factory", session_factory)
    messages = []
    monkeypatch.setattr(outbox, "_send_whatsapp", lambda session, to, body: messages.append((to, body)) or "wamid.1")
    monkeypatch.setattr(supplier_calls, "_place", lambda to, mode, params: None)
    return messages


class FakeAI:
    """Stands in for Gemini: answers by what the system prompt asks for."""

    def __init__(self):
        self.reply = None
        self.prompts = []

    def __call__(self, session, system, prompt):
        self.prompts.append((system, json.loads(prompt)))
        if "Write ONE WhatsApp message" in system:
            facts = json.loads(prompt)["facts"]
            return {"message": "AI: " + json.dumps(facts, ensure_ascii=False)}
        return self.reply


@pytest.fixture()
def ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(agent_text, "llm_json", fake)
    return fake


def _asked(client, db, make_product, make_supplier, make_customer, order_for, **cfg):
    mill, cement = _rfq(client, db, make_product, make_supplier, make_customer, order_for)
    set_step(client, "purchase", "purchase.ask_supplier", {**WINDOW, "wait_hours": 6, "how": "text", **cfg}, actors=["tai"], mode="auto")
    client.post("/api/automation/run/purchase")
    return mill, cement


def test_request_is_written_by_the_purchasing_agent(client, db, ai, sent, make_product, make_supplier, make_customer, order_for):
    _asked(client, db, make_product, make_supplier, make_customer, order_for)
    rfq = db.execute(select(SupplierQuoteRequest)).scalars().one()
    assert sent and sent[-1][1].startswith("AI:") and rfq.number in sent[-1][1]
    assert "purchasing agent" in ai.prompts[0][0]


def test_ai_reads_a_hinglish_quote_and_asks_for_what_is_missing(client, db, ai, sent, make_product, make_supplier, make_customer, order_for):
    from app.services import triggers

    mill, cement = _asked(client, db, make_product, make_supplier, make_customer, order_for)
    ai.reply = {"kind": "quote", "lines": [{"item": 1, "price": 345}], "delivery_days": 2, "freight": None, "gst_included": None,
                "missing": ["GST"], "ask_back": "Thank you! Is 345 with GST or GST extra?"}
    assert triggers.on_supplier_message(db, mill, "rate 345 hai, parso delivery") == "rfq_reply"
    quote = db.execute(select(SupplierQuote)).scalars().one()
    db.refresh(quote)
    assert quote.status == "replied" and quote.channel == "whatsapp" and quote.lines[0].price == Decimal("345") and quote.delivery_days == 2
    assert sent[-1] == (mill.phone, "Thank you! Is 345 with GST or GST extra?")
    # The answer updates the quote without losing the price.
    ai.reply = {"kind": "other", "lines": [], "gst_included": False, "missing": [], "ask_back": ""}
    triggers.on_supplier_message(db, mill, "GST alag")
    db.refresh(quote)
    assert quote.gst_included is False and quote.lines[0].price == Decimal("345")


def test_ai_reply_becomes_an_offer_and_the_pick_step_orders(client, db, ai, sent, make_product, make_supplier, make_customer, order_for):
    from app.services import triggers

    mill, cement = _asked(client, db, make_product, make_supplier, make_customer, order_for)
    set_step(client, "purchase", "purchase.compare_quotes", mode="auto", limits=[])
    ai.reply = {"kind": "quote", "lines": [{"item": 1, "price": 335}], "delivery_days": 2, "missing": [], "ask_back": ""}
    triggers.on_supplier_message(db, mill, "335, 2 days")
    db.expire_all()
    rfq = db.execute(select(SupplierQuoteRequest)).scalars().one()
    po = db.get(PurchaseOrder, rfq.purchase_order_id)
    assert rfq.status == "ordered" and po.enquiry_id == rfq.id and rfq.number in po.notes and po.items[0].unit_cost == Decimal("335")


def test_ai_reads_a_decline(client, db, ai, sent, make_product, make_supplier, make_customer, order_for):
    from app.services import triggers

    mill, _ = _asked(client, db, make_product, make_supplier, make_customer, order_for)
    ai.reply = {"kind": "decline", "lines": [], "missing": [], "ask_back": ""}
    triggers.on_supplier_message(db, mill, "maal nahi hai bhai")
    assert db.execute(select(SupplierQuote)).scalars().one().status == "declined"


def test_without_ai_the_word_reader_still_works(client, db, sent, make_product, make_supplier, make_customer, order_for):
    from app.services import triggers

    mill, _ = _asked(client, db, make_product, make_supplier, make_customer, order_for)
    assert not sent[-1][1].startswith("AI:")  # fixed wording
    triggers.on_supplier_message(db, mill, "340, 2 days")
    quote = db.execute(select(SupplierQuote)).scalars().one()
    assert quote.status == "replied" and quote.lines[0].price == Decimal("340")


@pytest.fixture()
def overdue(monkeypatch):
    """One customer 40 days late on Rs 4,000."""
    from app.services import reminders

    def fake_due(session):
        from app.models import Customer

        c = session.execute(select(Customer).where(Customer.name == "Late Payer")).scalar_one()
        docs = [{"number": "INV-1", "order_id": None, "order_number": "SO-1", "open": 4000.0, "days_overdue": 40}]
        return {"customers": [{"customer_id": c.id, "name": c.name, "phone": c.phone, "overdue": 4000.0, "invoices": 1, "oldest_days": 40,
                               "level": 2, "level_name": "Firm reminder", "last_reminded": None, "reminders_sent": 1, "documents": docs,
                               "message": "Hello Late Payer, Rs 4,000.00 overdue on INV-1."}], "total_overdue": 4000.0, "levels": []}

    monkeypatch.setattr(reminders, "due", fake_due)
    monkeypatch.setattr(reminders, "mark_sent", lambda session, cid, user, channel="whatsapp": {"logged": True})


def test_collections_texts_with_ai_then_calls(client, db, ai, sent, overdue, make_customer):
    buyer = make_customer("Late Payer", phone="9811111111")
    set_step(client, "sales", "sales.payment_reminders", {**WINDOW, "how": "text", "min_overdue": 100}, actors=["tai", "pai"], mode="auto")
    out = client.post("/api/automation/run/collections").json()
    assert out["texted"] == 1 and sent[-1][1].startswith("AI:") and "4,000.00" in sent[-1][1]
    set_step(client, "sales", "sales.payment_reminders", {**WINDOW, "how": "text_then_call", "call_from_level": "2", "min_overdue": 100},
             actors=["tai", "pai"], mode="auto")
    out = client.post("/api/automation/run/collections").json()
    assert out["called"] == 1
    task = db.execute(select(Task).where(Task.agent == "collections")).scalars().one()
    assert task.doer == "pai" and task.ai_status == "scheduled" and "4,000.00" in task.instructions
    # On the call: a promise to pay books a check on that date.
    tools = CallTools(lambda: db.__class__(bind=db.get_bind()), "+919811111111")
    tools.task_id = task.id
    assert tools.task_brief() and tools.task_agent == "collections"
    when = (datetime.now(timezone.utc) + timedelta(days=5)).date().isoformat()
    assert tools.run("record_payment_promise", {"date": when, "amount": 4000})["ok"]
    db.expire_all()
    check = db.execute(select(Task).where(Task.title.like("Check payment promised%"))).scalars().one()
    from zoneinfo import ZoneInfo

    due = check.due_date.astimezone(ZoneInfo("Asia/Kolkata")) if hasattr(check.due_date, "astimezone") and getattr(check.due_date, "tzinfo", None) else check.due_date
    assert due.isoformat()[:10] == when


def test_care_call_records_feedback_and_complaint(client, db, ai, sent, make_customer, make_product, order_for):
    buyer = make_customer("Happy Builder", phone="9822222222")
    tools = CallTools(lambda: db.__class__(bind=db.get_bind()), "+919822222222")
    from app.services import tasks

    task = tasks.create_task(db, "Delivery check-in", kind="call", doer="pai", agent="care", customer_id=buyer.id, instructions="Ask")
    tools.task_id = task.id
    tools.task_brief()
    out = tools.run("record_feedback", {"rating": 2, "comment": "Two bags were torn", "complaint": False})
    assert out["complaint"] is True  # rating 2 counts as a complaint
    db.expire_all()
    fb = db.execute(select(CustomerFeedback)).scalars().one()
    assert fb.rating == 2 and fb.complaint and fb.task_id
    assert db.execute(select(Task).where(Task.title.like("Complaint from%"))).scalars().one().priority.value == "HIGH"


def test_ai_reads_whatsapp_feedback(client, db, ai, sent, make_customer):
    from app.models import AutomationEvent
    from app.services import triggers

    buyer = make_customer("Happy Builder", phone="9822222222")
    db.add(AutomationEvent(step="sales.after_sales", kind="asked", status="awaiting_reply", party_type="customer", party_id=buyer.id, summary="asked"))
    db.commit()
    ai.reply = {"answer": True, "rating": 5, "complaint": False, "summary": "All good"}
    assert triggers.on_customer_message(db, buyer, "sab badhiya, bahut accha") == "feedback"
    assert db.execute(select(CustomerFeedback)).scalars().one().rating == 5
    ai.reply = {"answer": False}
    db.add(AutomationEvent(step="sales.after_sales", kind="asked", status="awaiting_reply", party_type="customer", party_id=buyer.id, summary="asked"))
    db.commit()
    assert triggers.on_customer_message(db, buyer, "do you have TMT 12mm?") is None  # goes to the Sales agent


def test_ai_message_that_drops_a_number_is_not_used(db, monkeypatch):
    monkeypatch.setattr(agent_text, "llm_json", lambda s, sys, p: {"message": "Please pay soon."})
    assert agent_text.write(db, "collections", "reminder", {"amount": "4,000.00"}, "fixed 4,000.00", must_keep=["4,000.00"]) == "fixed 4,000.00"
