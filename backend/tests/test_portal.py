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


def _link(client, customer):
    return client.post("/api/customers/{}/enquiry-link".format(customer.id), json={"enabled": True}).json()["path"][3:]


def test_customer_sees_own_orders_deliveries_and_account(client, db, make_product, make_customer, order_for):
    cement = make_product("Cement", opening_stock=50, mrp="400")
    buyer = make_customer("Builder", payment_terms_days=15)
    other = make_customer("Rival")
    order = order_for(buyer, cement, 10, unit_price="400")
    order_for(other, cement, 3, unit_price="400")
    item_id = order.items[0].id
    sent = client.post("/api/orders/{}/deliveries".format(order.id), json={
        "lines": [{"order_item_id": str(item_id), "quantity": "4"}], "vehicle_number": "GJ01AB1234", "lr_number": "LR-77"})
    assert sent.status_code == 201, sent.text
    token = _link(client, buyer)
    app.dependency_overrides.pop(require_user, None)

    body = client.get("/api/public/e/{}/orders".format(token)).json()
    assert len(body["orders"]) == 1
    row = body["orders"][0]
    assert row["number"] == order.order_number and row["total"] == 4000.0
    line = row["lines"][0]
    assert line["product"] == "Cement" and line["ordered"] == 10 and line["delivered"] == 4 and line["pending"] == 6
    assert "cost" not in str(row).lower()
    assert row["deliveries"][0]["vehicle_number"] == "GJ01AB1234" and row["deliveries"][0]["lr_number"] == "LR-77"
    assert row["deliveries"][0]["lines"][0]["quantity"] == 4

    statement = client.get("/api/public/e/{}/statement".format(token))
    assert statement.status_code == 200, statement.text
    st = statement.json()
    assert st["summary"]["invoiced"] == 1600.0 and st["summary"]["payment_terms_days"] == 15
    assert st["entries"][0]["kind"] == "invoice" and st["entries"][-1]["balance"] == 1600.0

    page = client.get("/api/public/e/{}".format(token)).json()
    assert page["customer_summary"]["open_orders"] == 1 and page["customer_summary"]["amount_open"] == 1600.0
    assert page["customer_summary"]["last_order_date"]

    assert client.get("/api/public/e/bad-token/orders").status_code == 404
    assert client.get("/api/public/e/bad-token/statement").status_code == 404


def test_order_again_creates_an_enquiry(client, make_product, make_customer, order_for):
    cement = make_product("Cement", opening_stock=50, mrp="400")
    buyer = make_customer("Builder")
    other = make_customer("Rival")
    client.put("/api/customers/{}/pricing".format(buyer.id), json={"discount_percent": "5"})
    order = order_for(buyer, cement, 10, unit_price="400")
    rival_order = order_for(other, cement, 2)
    token = _link(client, buyer)
    app.dependency_overrides.pop(require_user, None)

    again = client.post("/api/public/e/{}/reorder/{}".format(token, order.id))
    assert again.status_code == 201, again.text
    assert again.json()["enquiry_number"] and again.json()["total"] == 3800.0
    assert client.post("/api/public/e/{}/reorder/{}".format(token, rival_order.id)).status_code == 404


def test_invoices_only_for_own_orders(client, db, make_product, make_customer, order_for):
    from datetime import datetime, timezone

    from app.models import TallySync

    cement = make_product("Cement", opening_stock=50, mrp="400")
    buyer = make_customer("Builder")
    other = make_customer("Rival")
    mine = order_for(buyer, cement, 2, unit_price="400")
    theirs = order_for(other, cement, 2, unit_price="400")
    now = datetime.now(timezone.utc)
    own_row = TallySync(kind="sales_invoice", entity_id=mine.id, reference=mine.order_number, status="synced", tally_number="INV-1", synced_at=now)
    rival_row = TallySync(kind="sales_invoice", entity_id=theirs.id, reference=theirs.order_number, status="synced", tally_number="INV-2", synced_at=now)
    db.add_all([own_row, rival_row])
    db.commit()
    token = _link(client, buyer)
    app.dependency_overrides.pop(require_user, None)

    rows = client.get("/api/public/e/{}/invoices".format(token)).json()["invoices"]
    assert [r["number"] for r in rows] == ["INV-1"] and rows[0]["amount"] == 800.0
    pdf = client.get(rows[0]["download"])
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert client.get("/api/public/e/{}/invoices/{}.pdf".format(token, rival_row.id)).status_code == 404
