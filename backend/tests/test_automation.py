"""Automation flows, and TAI as a full agent under them."""
from __future__ import annotations

from langchain_core.messages import AIMessage

from tests.test_integrations import call, enable_ai, enable_whatsapp, last_result, server_ai_credentials, wired, whatsapp_payload  # noqa: F401


def flow_with(client, key, changes):
    flow = client.get("/api/automation/flows/{}".format(key)).json()
    for node in flow["nodes"]:
        if node["data"]["step"] in changes:
            node["data"].update(changes[node["data"]["step"]])
    saved = client.put("/api/automation/flows/{}".format(key), json={"nodes": flow["nodes"], "edges": flow["edges"]})
    assert saved.status_code == 200, saved.text
    return saved.json()


def test_flows_default_validate_and_sync_settings(client):
    lib = client.get("/api/automation/library").json()
    assert len([s for s in lib["steps"] if s["flow"] == "sales"]) >= 14
    sales = client.get("/api/automation/flows/sales").json()
    keys = [n["data"]["step"] for n in sales["nodes"]]
    assert keys[0] == "sales.trigger_incoming" and len(sales["edges"]) == len(sales["nodes"]) - 1
    confirmation = next(n for n in sales["nodes"] if n["data"]["step"] == "sales.order_confirmation")
    assert confirmation["data"]["actors"] == ["system"]  # sending a template is the system's job
    # Not allowed: TAI on a system-only step, an unknown mode, a dangling edge.
    bad = dict(sales)
    bad["nodes"] = [dict(n, data=dict(n["data"], actors=["tai"])) if n["data"]["step"] == "sales.identify" else n for n in sales["nodes"]]
    assert client.put("/api/automation/flows/sales", json={"nodes": bad["nodes"], "edges": sales["edges"]}).status_code == 422
    assert client.put("/api/automation/flows/sales", json={"nodes": sales["nodes"], "edges": [{"source": "n1", "target": "zz"}]}).status_code == 422
    # Saving keeps existing settings in step.
    client.put("/api/integrations/whatsapp", json={"enabled": False, "config": {}})
    flow_with(client, "sales", {"sales.order_confirmation": {"mode": "auto"}, "sales.invoice": {"timing": {"invoice_on": "delivery"}}})
    assert client.get("/api/integrations").json()["whatsapp"]["config"]["send_order_confirmations"] is True
    assert client.get("/api/integrations").json()["tally"]["config"]["invoice_on"] == "delivery"
    assert client.post("/api/automation/flows/sales/reset").json()["customised"] is False


def test_tai_answers_quotes_and_takes_an_order(client, wired, make_product, make_customer, monkeypatch):
    from app.services import outbox

    sent = []
    monkeypatch.setattr(outbox, "_send_whatsapp", lambda session, to, body: sent.append((to, body)) or "wamid.x")
    cement = make_product("Cement, 50kg bag", sku="CEM-50", opening_stock=100, mrp="380.00")
    make_customer("Ravi Builders", phone="98765 43210")
    enable_ai(client)
    enable_whatsapp(client)
    client.put("/api/integrations/ai", json={"config": {"company_profile": "We sell cement and steel in Gandhinagar.", "company_hours": "9 to 7, Mon-Sat"}})
    # Let TAI send quotes and place orders up to 10,000 for known customers.
    flow_with(client, "sales", {"sales.send_quote": {"mode": "auto"},
                                "sales.confirm_order": {"actors": ["tai", "person"], "mode": "limits",
                                                        "limits": [{"field": "order_value", "op": "<=", "value": 10000}, {"field": "customer", "op": "=", "value": "known"}]}})

    # 1. "Rate for 20 bags?" -> quote reply and a ready order summary.
    wired.append([
        call("search_products", {"query": "cement"}, "c1"),
        call("prices_and_stock", lambda m: {"product_ids": [last_result(m)[0]["id"]]}, "c2"),
        call("prepare_order", lambda m: {"lines": [{"product_id": last_result(m)[0]["id"], "quantity": 20}]}, "c3"),
        call("reply", {"text": "20 bags Cement at Rs 380 = Rs 7,600 (before GST). Reply YES to confirm."}, "c4"),
        AIMessage(content="ANSWERED: quoted 20 bags."),
    ])
    client.post("/api/integrations/whatsapp/webhook", json=whatsapp_payload(message_id="w1", body="Rate for 20 bags cement? Want to order"))
    first = next(m for m in client.get("/api/integrations/messages").json()["items"] if m["body"].startswith("Rate"))
    assert first["status"] == "awaiting_confirmation", first
    assert sent and sent[-1][0] == "+919876543210" and "YES" in sent[-1][1]

    # 2. "YES" -> the agent sees the conversation and places the order.
    seen = {}

    def place(messages):
        seen["history"] = "Conversation so far" in messages[-1].content if isinstance(messages[-1].content, str) else True
        return {}

    wired.append([call("place_order", place, "c5"), call("reply", lambda m: {"text": "Order {} placed.".format(last_result(m)["placed"])}, "c6"),
                  AIMessage(content="ORDER: placed.")])
    client.post("/api/integrations/whatsapp/webhook", json=whatsapp_payload(message_id="w2", body="YES"))
    second = next(m for m in client.get("/api/integrations/messages").json()["items"] if m["body"] == "YES")
    assert second["status"] == "order_placed", second
    assert seen["history"] is True
    orders = client.get("/api/orders").json()["items"]
    assert len(orders) == 1 and float(orders[0]["total_amount"]) == 7600.0 and "SO-" in sent[-1][1]

    # 3. Over the limit -> held for a person, who can place it from approvals.
    wired.append([
        call("search_products", {"query": "cement"}, "c7"),
        call("prepare_order", lambda m: {"lines": [{"product_id": last_result(m)[0]["id"], "quantity": 50}]}, "c8"),
        AIMessage(content="ANSWERED: summary sent."),
    ])
    client.post("/api/integrations/whatsapp/webhook", json=whatsapp_payload(message_id="w3", body="50 bags please"))
    wired.append([call("place_order", {}, "c9"), AIMessage(content="ANSWERED: team will confirm.")])
    client.post("/api/integrations/whatsapp/webhook", json=whatsapp_payload(message_id="w4", body="yes"))
    approvals = client.get("/api/automation/approvals").json()
    assert approvals["orders"] and "Order value" in approvals["orders"][0]["note"]
    placed = client.post("/api/automation/drafts/{}/place".format(approvals["orders"][0]["id"]))
    assert placed.status_code == 200, placed.text
    assert len(client.get("/api/orders").json()["items"]) == 2


def test_replies_wait_for_approval_by_default(client, wired, make_product, monkeypatch):
    from app.services import outbox

    sent = []
    monkeypatch.setattr(outbox, "_send_whatsapp", lambda session, to, body: sent.append(body) or "wamid.y")
    make_product("Cement, 50kg bag", sku="CEM-50", mrp="380.00")
    enable_ai(client)
    enable_whatsapp(client)
    wired.append([call("reply", {"text": "We are open 9 to 7."}, "r1"), AIMessage(content="ANSWERED: hours.")])
    client.post("/api/integrations/whatsapp/webhook", json=whatsapp_payload(message_id="h1", body="What time do you open?"))
    pending = client.get("/api/automation/approvals").json()["messages"]
    assert sent == [] and pending[0]["body"] == "We are open 9 to 7."
    done = client.post("/api/automation/messages/{}/approve".format(pending[0]["id"]), json={"body": "We are open 9 am to 7 pm."})
    assert done.json()["status"] == "sent" and sent == ["We are open 9 am to 7 pm."]
