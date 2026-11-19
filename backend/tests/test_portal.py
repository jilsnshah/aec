"""A customer's own enquiry link."""
from __future__ import annotations

from app.api.auth import require_user
from app.main import app


def test_customer_link_shows_their_prices_and_takes_enquiries(client, make_product, make_customer):
    cement = make_product("Cement", opening_stock=10, mrp="400")
    make_product("Sand", opening_stock=0, mrp="100")
    buyer = make_customer("Builder")
    client.put("/api/customers/{}/pricing".format(buyer.id), json={"discount_percent": "5"})
    link = client.post("/api/customers/{}/enquiry-link".format(buyer.id), json={"enabled": True}).json()
    assert link["enabled"] and link["path"].startswith("/e/")
    token = link["path"][3:]

    # No sign-in needed for the public page.
    app.dependency_overrides.pop(require_user, None)
    page = client.get("/api/public/e/{}".format(token))
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["customer"] == "Builder"
    cement_row = next(p for p in body["products"] if p["name"] == "Cement")
    sand_row = next(p for p in body["products"] if p["name"] == "Sand")
    assert cement_row["price"] == 380.0 and cement_row["in_stock"] is True and sand_row["in_stock"] is False
    assert "physical_stock" not in cement_row

    sent = client.post("/api/public/e/{}".format(token), json={"items": [{"product_id": str(cement.id), "quantity": 20}], "notes": "for tower B", "name": "Ravi (site)"})
    assert sent.status_code == 201, sent.text
    assert sent.json()["total"] == 7600.0
    assert client.get("/api/public/e/not-a-token").status_code == 404
    assert client.post("/api/public/e/{}".format(token), json={"items": []}).status_code == 422


def test_replaced_link_stops_working(client, make_customer):
    buyer = make_customer("Shop")
    old = client.post("/api/customers/{}/enquiry-link".format(buyer.id), json={}).json()["path"][3:]
    new = client.post("/api/customers/{}/enquiry-link".format(buyer.id), json={}).json()["path"][3:]
    assert old != new
    assert client.get("/api/public/e/{}".format(old)).status_code == 404
    assert client.get("/api/public/e/{}".format(new)).status_code == 200
    client.post("/api/customers/{}/enquiry-link".format(buyer.id), json={"enabled": False})
    assert client.get("/api/public/e/{}".format(new)).status_code == 404


def test_order_confirmation_on_whatsapp_when_switched_on(client, db, session_factory, make_product, make_customer, monkeypatch):
    from app.services import inbound, notifications

    monkeypatch.setattr(inbound, "session_factory", session_factory)

    sent = []
    monkeypatch.setattr(notifications.whatsapp, "send_template", lambda config, token, to, template, params: sent.append((to, template, params)) or "wamid.9")
    p = make_product("Cement", opening_stock=10, mrp="100")
    c = make_customer("Builder", phone="98250 12345")
    body = {"customer_id": str(c.id), "items": [{"product_id": str(p.id), "quantity_ordered": "2"}]}

    # Off by default: nothing is sent.
    client.post("/api/orders", json=body)
    assert sent == []
    client.put("/api/integrations/whatsapp", json={"enabled": True, "config": {"phone_number_id": "PN", "verify_token": "v", "send_order_confirmations": True, "order_template": "order_confirmed"},
                                                    "credentials": {"access_token": "tok"}})
    order = client.post("/api/orders", json=body).json()
    assert sent and sent[-1][0] == "919825012345" and sent[-1][1] == "order_confirmed"
    assert sent[-1][2][1] == order["order_number"] and "Cement" in sent[-1][2][3]
    manual = client.post("/api/orders/{}/send-confirmation".format(order["id"]))
    assert manual.status_code == 200 and manual.json()["sent"] is True
    events = client.get("/api/records/timeline", params={"order_id": order["id"]}).json()["events"]
    assert any("WhatsApp confirmation sent" in e["title"] for e in events)
