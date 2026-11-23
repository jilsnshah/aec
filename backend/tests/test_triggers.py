"""The trigger engine: purchase need -> purchase enquiry -> offers -> PO; chasing;
customer outreach; after-sales follow-up."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.models import AutomationEvent, CustomerFeedback, PurchaseOrder, SupplierQuoteRequest, Task
from app.services import outbox, triggers

ALL_DAY = {"window_start": "00:00", "window_end": "23:59", "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}


@pytest.fixture()
def sent(monkeypatch):
    messages = []
    monkeypatch.setattr(outbox, "_send_whatsapp", lambda session, to, body: messages.append((to, body)) or "wamid.1")
    return messages


def set_step(client, flow, key, config=None, **data):
    current = client.get("/api/automation/flows/{}".format(flow)).json()
    lib = {s["key"]: s for s in client.get("/api/automation/library").json()["steps"]}
    nodes = current["nodes"]
    node = next((n for n in nodes if n["data"]["step"] == key), None)
    if node is None:
        node = {"id": key, "type": "step", "position": {"x": 0, "y": 0}, "data": {
            "step": key, "title": lib[key]["label"], "actors": [lib[key]["default_actor"]], "mode": lib[key]["modes"][0], "limits": [],
            "ai": {"model": "", "instructions": ""} if lib[key]["ai"] else None, "channels": lib[key]["channels"], "timing": lib[key]["timing"],
            "config": None, "notes": ""}}
        nodes.append(node)
    node["data"].update(data)
    if config is not None:
        merged = node["data"].get("config") or {}
        for k, v in config.items():
            merged[k] = {**merged.get(k, {}), **v} if isinstance(v, dict) and isinstance(merged.get(k), dict) else v
        node["data"]["config"] = merged
    saved = client.put("/api/automation/flows/{}".format(flow), json={"nodes": nodes, "edges": current["edges"]})
    assert saved.status_code == 200, saved.text


def test_need_to_quotes_to_purchase_order(client, db, sent, make_product, make_supplier, make_customer, order_for):
    mill = make_supplier("Mill A", phone="9000000011")
    other = make_supplier("Mill B", phone="9000000012")
    cement = make_product("Cement", opening_stock=10, opening_unit_cost="330", mrp="400")
    client.patch("/api/products/{}".format(cement.id), json={"reorder_level": "50", "preferred_supplier_id": str(mill.id), "lead_time_days": 2})
    # Mill B sold us cement before, so it is asked too.
    po = client.post("/api/purchase-orders", json={"supplier_id": str(other.id), "confirm": True, "items": [{"product_id": str(cement.id), "quantity_ordered": "1", "unit_cost": "335"}]}).json()
    client.post("/api/goods-receipts", json={"purchase_order_id": po["id"], "lines": [{"purchase_order_item_id": po["items"][0]["id"], "quantity": "1"}]})
    db.expire_all()
    order_for(make_customer("Builder"), cement, 30)  # 11 in stock: 19 short
    set_step(client, "purchase", "purchase.need_detected", {"schedule": ALL_DAY})
    set_step(client, "purchase", "purchase.choose_supplier", {"quantity": {"method": "up_to_reorder", "round_to_purchase_unit": False}})
    set_step(client, "purchase", "purchase.ask_supplier", {**{k: v for k, v in ALL_DAY.items() if k != "days"}, "wait_hours": 6}, actors=["tai"], mode="auto")
    preview = client.get("/api/automation/preview/purchase").json()["items"]
    assert preview and preview[0]["product"] == "Cement" and "customers short" in preview[0]["why"]
    result = client.post("/api/automation/run/purchase").json()
    assert result["rfq"].startswith("PE") and result["asked"] == 2
    db.expire_all()
    assert db.execute(select(PurchaseOrder).where(PurchaseOrder.enquiry_id.isnot(None))).first() is None  # no PO before the offers
    assert {to for to, _ in sent} == {"9000000011", "9000000012"} and "Cement" in sent[0][1]
    db.expire_all()
    from app.models import Supplier

    triggers.on_supplier_message(db, db.get(Supplier, mill.id), "Rs 340 per bag, 3 days")
    triggers.on_supplier_message(db, db.get(Supplier, other.id), "338/-  2 din me")
    db.expire_all()
    rfq = db.execute(select(SupplierQuoteRequest)).scalars().one()
    assert rfq.status == "ordered"
    created = db.get(PurchaseOrder, rfq.purchase_order_id)
    # Within the default limits (value and price rise): the best offer is ordered and sent at once.
    assert created.status.value == "ORDERED" and created.supplier_id == other.id and created.items[0].unit_cost == Decimal("338")
    assert created.enquiry_id == rfq.id and sent[-1][0] == "9000000012" and created.po_number in sent[-1][1]


def _enquiry_setup(client, db, make_product, make_supplier, make_customer, order_for):
    mill = make_supplier("Mill A", phone="9000000061")
    other = make_supplier("Mill B", phone="9000000062")
    cement = make_product("Cement", opening_stock=0, mrp="400")
    client.patch("/api/products/{}".format(cement.id), json={"reorder_level": "0", "preferred_supplier_id": str(mill.id)})
    order_for(make_customer("Builder"), cement, 20)
    set_step(client, "purchase", "purchase.need_detected", {"schedule": ALL_DAY})
    set_step(client, "purchase", "purchase.choose_supplier", {"quantity": {"method": "shortage_only", "round_to_purchase_unit": False}})
    set_step(client, "purchase", "purchase.ask_supplier", {"window_start": "00:00", "window_end": "23:59"}, actors=["tai"], mode="auto")
    return mill, other, cement


def test_person_picks_the_offer(client, db, sent, make_product, make_supplier, make_customer, order_for):
    mill, other, cement = _enquiry_setup(client, db, make_product, make_supplier, make_customer, order_for)
    set_step(client, "purchase", "purchase.compare_quotes", mode="approval", limits=[])
    pe = client.post("/api/automation/run/purchase").json()["rfq"]
    enquiry = client.get("/api/purchase-enquiries").json()["items"][0]
    assert enquiry["number"] == pe and enquiry["status"] == "open" and [q["supplier"] for q in enquiry["quotes"]] == ["Mill A"]
    # The buyer asks Mill B as well, then records Mill B's phoned-in offer by hand.
    enquiry = client.post("/api/purchase-enquiries/{}/suppliers".format(enquiry["id"]), json={"supplier_id": str(other.id)}).json()
    assert {q["supplier"]: q["status"] for q in enquiry["quotes"]} == {"Mill A": "asked", "Mill B": "asked"}
    from app.models import Supplier

    triggers.on_supplier_message(db, db.get(Supplier, mill.id), "Rs 340 per bag, 3 days")
    enquiry = client.post("/api/purchase-enquiries/{}/offers".format(enquiry["id"]),
                          json={"supplier_id": str(other.id), "prices": {str(cement.id): 350}, "delivery_days": 1}).json()
    assert enquiry["status"] == "to_choose" and enquiry["orders"] == []
    assert db.execute(select(PurchaseOrder)).first() is None  # still no PO: a person picks
    # The buyer prefers the faster supplier.
    enquiry = client.post("/api/purchase-enquiries/{}/order".format(enquiry["id"]), json={"supplier_id": str(other.id)}).json()
    assert enquiry["status"] == "ordered" and enquiry["orders"][0]["supplier"] == "Mill B" and enquiry["orders"][0]["total"] == 7000
    db.expire_all()
    po = db.execute(select(PurchaseOrder)).scalars().one()
    assert po.status.value == "ORDERED" and po.expected_delivery_date is not None and any(po.po_number in body for _, body in sent)


def test_draft_enquiry_waits_for_a_person(client, db, sent, make_product, make_supplier, make_customer, order_for):
    mill, other, cement = _enquiry_setup(client, db, make_product, make_supplier, make_customer, order_for)
    set_step(client, "purchase", "purchase.choose_supplier", mode="approval")
    result = client.post("/api/automation/run/purchase").json()
    assert result["draft"] and sent == []
    enquiry = client.get("/api/purchase-enquiries", params={"status": "draft"}).json()["items"][0]
    enquiry = client.delete("/api/purchase-enquiries/{}/suppliers/{}".format(enquiry["id"], mill.id)).json()
    enquiry = client.post("/api/purchase-enquiries/{}/suppliers".format(enquiry["id"]), json={"supplier_id": str(other.id)}).json()
    assert [q["supplier"] for q in enquiry["quotes"]] == ["Mill B"] and sent == []
    enquiry = client.post("/api/purchase-enquiries/{}/send".format(enquiry["id"])).json()
    assert enquiry["status"] == "open" and [to for to, _ in sent] == ["9000000062"]


def test_enquiry_by_hand(client, db, sent, make_product, make_supplier):
    mill = make_supplier("Mill A", phone="9000000071")
    cement = make_product("Cement", opening_stock=0, mrp="400")
    set_step(client, "purchase", "purchase.ask_supplier", {"window_start": "00:00", "window_end": "23:59"}, actors=["tai"], mode="auto")
    made = client.post("/api/purchase-enquiries", json={"lines": [{"product_id": str(cement.id), "quantity": "5"}], "supplier_ids": [str(mill.id)]})
    assert made.status_code == 201, made.text
    assert made.json()["status"] == "open" and [to for to, _ in sent] == ["9000000071"]


def test_contract_skips_asking_and_send_po(client, db, sent, make_product, make_supplier):
    mill = make_supplier("Mill A", phone="9000000021")
    sand = make_product("Sand", opening_stock=0, mrp="60")
    client.patch("/api/products/{}".format(sand.id), json={"reorder_level": "100", "preferred_supplier_id": str(mill.id)})
    client.post("/api/rate-contracts", json={"supplier_id": str(mill.id), "items": [{"product_id": str(sand.id), "rate": "45"}]})
    set_step(client, "purchase", "purchase.need_detected", {"schedule": ALL_DAY})
    set_step(client, "purchase", "purchase.compare_quotes", mode="auto", limits=[])
    set_step(client, "purchase", "purchase.send_po", mode="auto")
    result = client.post("/api/automation/run/purchase").json()
    assert result["contract_lines"] == 1 and result["asked"] == 0
    db.expire_all()
    po = db.execute(select(PurchaseOrder)).scalars().one()
    assert po.status.value == "ORDERED" and po.items[0].unit_cost == Decimal("45")
    assert any(po.po_number in body for _, body in sent)


def test_chase_late_delivery_and_new_date(client, db, sent, make_product, make_supplier):
    mill = make_supplier("Mill A", phone="9000000031")
    cement = make_product("Cement", opening_stock=0, mrp="400")
    po = client.post("/api/purchase-orders", json={"supplier_id": str(mill.id), "confirm": True,
                                                   "expected_delivery_date": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                                                   "items": [{"product_id": str(cement.id), "quantity_ordered": "100", "unit_cost": "330"}]}).json()
    set_step(client, "purchase", "purchase.chase_delivery", {"window_start": "00:00", "window_end": "23:59"}, mode="auto", actors=["tai"])
    sent.clear()
    assert triggers.tick_chase(db) == 1 and po["po_number"] in sent[0][1]
    assert triggers.tick_chase(db) == 0  # not twice a day
    from app.models import Supplier

    assert triggers.on_supplier_message(db, db.get(Supplier, mill.id), "kal pahuch jayega") == "chase_reply"
    db.expire_all()
    updated = db.get(PurchaseOrder, po["id"])
    assert updated.expected_delivery_date.date() >= datetime.now(timezone.utc).date()


def test_outreach_to_dormant_customers_with_caps(client, db, sent, make_product, make_customer, order_for):
    cement = make_product("Cement", opening_stock=100, mrp="400")
    old = make_customer("Old Builder", phone="9000000041")
    for _ in range(2):
        order_for(old, cement, 1)
    db.execute(text("UPDATE sales_orders SET created_at = now() - interval '80 days'"))
    db.commit()
    make_customer("No Phone Builder")
    set_step(client, "sales", "sales.trigger_outreach", {"schedule": {**ALL_DAY, "every": "1h"}}, mode="auto", actors=["tai"])
    preview = client.get("/api/automation/preview/outreach").json()["items"]
    assert [p["customer"] for p in preview] == ["Old Builder"] and "dormant" in preview[0]["why"]
    result = client.post("/api/automation/run/outreach").json()
    assert result["contacted"] == 1 and sent[-1][0] == "9000000041" and "Cement" in sent[-1][1]
    again = client.post("/api/automation/run/outreach").json()
    assert again["contacted"] == 0  # once every 14 days


def test_after_sales_rating_and_complaint(client, db, sent, make_product, make_customer, order_for):
    cement = make_product("Cement", opening_stock=100, mrp="400")
    buyer = make_customer("Builder", phone="9000000051")
    order = order_for(buyer, cement, 10)
    client.post("/api/orders/{}/deliveries".format(order.id), json={"lines": [{"order_item_id": str(order.items[0].id), "quantity": "10"}]})
    db.execute(text("UPDATE customer_deliveries SET created_at = now() - interval '30 hours'"))
    db.commit()
    set_step(client, "sales", "sales.after_sales", {"window_start": "00:00", "window_end": "23:59"}, mode="auto", actors=["tai"])
    assert client.post("/api/automation/run/after_sales").json()["asked"] == 1
    assert "rate" in sent[-1][1]
    from app.models import Customer

    db.expire_all()
    assert triggers.on_customer_message(db, db.get(Customer, buyer.id), "2 - 3 bags were torn") == "feedback"
    db.expire_all()
    fb = db.execute(select(CustomerFeedback)).scalars().one()
    assert fb.rating == 2 and fb.complaint and fb.task_id
    assert db.get(Task, fb.task_id).priority.value == "HIGH"
    assert client.get("/api/automation/feedback").json()["complaints"] == 1
    # An unrelated message is left for TAI.
    assert triggers.on_customer_message(db, db.get(Customer, buyer.id), "need 50 bags cement") is None


def test_pai_follow_up_call_at_its_time(client, db, monkeypatch, make_customer):
    from app.voice import outbound

    calls = []
    monkeypatch.setattr(outbound, "place_call", lambda to, mode, params=None: calls.append((to, mode, params)) or "CA1")
    buyer = make_customer("Builder", phone="9000000061")
    no_phone = make_customer("No Phone")
    bad = client.post("/api/tasks", json={"title": "Call about payment", "kind": "call", "doer": "pai", "customer_id": str(no_phone.id)})
    assert bad.status_code == 422 and "number" in bad.text
    soon = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    task = client.post("/api/tasks", json={"title": "Remind about cheque", "kind": "call", "doer": "pai", "customer_id": str(buyer.id), "due_at": soon,
                                           "instructions": "Ask when the cheque for SO-12 will be ready; be polite."}).json()
    assert task["ai_status"] == "scheduled" and task["kind"] == "call"
    assert triggers.run_ai_calls(db)["placed"] == 0  # not yet time
    client.patch("/api/tasks/{}".format(task["id"]), json={"due_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()})
    db.expire_all()
    assert triggers.run_ai_calls(db)["placed"] == 1 and calls == [("9000000061", "task", {"task": task["id"]})]
    assert "cheque" in triggers.call_brief(db, uuid_of(task))
    # Nobody picked up: tried again later.
    db.execute(text("UPDATE tasks SET last_call_at = now() - interval '20 minutes'"))
    db.commit()
    db.expire_all()
    triggers.run_ai_calls(db)
    row = client.get("/api/tasks/{}".format(task["id"])).json()
    assert row["ai_status"] == "scheduled" and "No answer" in row["ai_result"]
    # Picked up the second time and done.
    triggers.finish_call(db, uuid_of(task), "done", "Cheque will be ready Friday; customer will send a photo.")
    row = client.get("/api/tasks/{}".format(task["id"])).json()
    assert row["status"] == "DONE" and row["ai_status"] == "done" and "Friday" in row["ai_result"]


def uuid_of(row):
    import uuid

    return uuid.UUID(row["id"])
