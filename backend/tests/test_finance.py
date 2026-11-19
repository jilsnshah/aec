"""Payments, receivables, payables, statements, analytics and workspace."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.api.auth import require_user
from app.main import app
from app.models import User
from app.services import deliveries as delivery_service


@pytest.fixture()
def owner(client, db):
    user = User(username="boss", password_hash="x", is_admin=True, session_version=1)
    db.add(user)
    db.commit()
    app.dependency_overrides[require_user] = lambda: user
    return user


def deliver(db, order, quantity, days_ago=0):
    result = delivery_service.create_delivery(db, order.id, [{"order_item_id": order.items[0].id, "quantity": str(quantity)}])
    if days_ago:
        db.execute(text("UPDATE customer_deliveries SET created_at = now() - make_interval(days => :d) WHERE id = :id"),
                   {"d": days_ago, "id": result["delivery_id"]})
        db.commit()
    return result


def test_receivables_settle_oldest_first_and_age_by_terms(client, db, owner, make_product, make_customer, order_for):
    cement = make_product("Cement", opening_stock=100, mrp="100")
    buyer = make_customer("Builder")
    client.patch("/api/customers/{}".format(buyer.id), json={"payment_terms_days": 30, "credit_limit": 1000})
    order = order_for(buyer, cement, 20)
    deliver(db, order, 5, days_ago=70)   # 500, due 40 days ago
    deliver(db, order, 10, days_ago=10)  # 1000, not yet due
    paid = client.post("/api/payments", json={"direction": "in", "customer_id": str(buyer.id), "amount": 300, "method": "upi"})
    assert paid.status_code == 201, paid.text
    assert paid.json()["number"].startswith("RCV-")

    data = client.get("/api/finance/receivables").json()
    row = next(r for r in data["parties"] if r["name"] == "Builder")
    assert row["invoiced"] == 1500.0 and row["paid"] == 300.0 and row["open"] == 1200.0
    # The payment settled the oldest invoice first: 200 of it is left, 40 days overdue.
    assert row["buckets"]["31-60"] == 200.0 and row["buckets"]["not_due"] == 1000.0
    assert row["overdue"] == 200.0 and row["over_credit_limit"] is True
    assert data["overdue"][0]["open"] == 200.0 and data["overdue"][0]["days_overdue"] == 40

    statement = client.get("/api/finance/customers/{}/statement".format(buyer.id)).json()
    assert [e["kind"] for e in statement["entries"]] == ["invoice", "invoice", "payment"]
    assert statement["entries"][-1]["balance"] == 1200.0 and statement["summary"]["overdue"] == 200.0

    kinds = {a["kind"] for a in client.get("/api/insights/alerts").json()["alerts"]}
    assert {"overdue_receivable", "over_credit_limit"} <= kinds

    voided = client.post("/api/payments/{}/void".format(paid.json()["id"]), json={"reason": "bounced"})
    assert voided.json()["voided"] is True
    assert client.get("/api/finance/receivables").json()["totals"]["open"] == 1500.0
    assert client.post("/api/payments/{}/void".format(paid.json()["id"])).status_code == 409


def test_payments_are_validated(client, owner, make_customer, make_supplier):
    customer = make_customer("C")
    supplier = make_supplier("S")
    bad = [
        {"direction": "in", "supplier_id": str(supplier.id), "amount": 10},
        {"direction": "out", "customer_id": str(customer.id), "amount": 10},
        {"direction": "in", "customer_id": str(customer.id), "amount": 10, "method": "bitcoin"},
        {"direction": "in", "customer_id": str(customer.id), "amount": 10, "paid_on": (date.today() + timedelta(days=5)).isoformat()},
    ]
    for body in bad:
        assert client.post("/api/payments", json=body).status_code == 422, body
    assert client.post("/api/payments", json={"direction": "in", "customer_id": str(customer.id), "amount": 0}).status_code == 422
    ok = client.post("/api/payments", json={"direction": "out", "supplier_id": str(supplier.id), "amount": 50})
    assert ok.status_code == 201 and ok.json()["number"].startswith("PAY-")
    assert client.get("/api/payments?direction=out").json()["total"] == 1


def test_product_settings_drive_reorder_points(client, make_product, make_supplier, make_customer, order_for):
    supplier = make_supplier("Mill")
    client.patch("/api/suppliers/{}".format(supplier.id), json={"lead_time_days": 10})
    rods = make_product("Rods", opening_stock=5, mrp="50")
    response = client.patch("/api/products/{}".format(rods.id), json={
        "category": "Steel", "reorder_level": 20, "preferred_supplier_id": str(supplier.id)})
    assert response.status_code == 200 and response.json()["preferred_supplier_name"] == "Mill"
    row = next(p for p in client.get("/api/insights/inventory").json()["products"] if p["name"] == "Rods")
    assert "below_minimum" in row["flags"] and row["action"]["code"] == "buy"
    assert row["lead_time_days"] == 10 and row["lead_time_source"] == "supplier" and row["reorder_quantity"] >= 15
    assert client.get("/api/products?category=Steel").json()["total"] == 1
    assert client.get("/api/products?ids={}".format(rods.id)).json()["items"][0]["name"] == "Rods"
    assert {"name": "Steel", "products": 1} in client.get("/api/products/categories").json()


def test_explorer_groups_compares_and_filters(client, make_product, make_customer, order_for):
    cement = make_product("Cement", opening_stock=50, mrp="100")
    client.patch("/api/products/{}".format(cement.id), json={"category": "Cement"})
    sand = make_product("Sand", opening_stock=50, mrp="10")
    buyer = make_customer("Buyer")
    order_for(buyer, cement, 3)
    order_for(buyer, sand, 5)
    data = client.get("/api/insights/explore?measure=booked_value&group_by=category&period=last_30").json()
    by = {row["label"]: row["value"] for row in data["rows"]}
    assert by == {"Cement": 300.0, "(none)": 50.0} and data["total"] == 350.0
    assert data["rows"][0]["cumulative_percent"] == pytest.approx(85.7, 0.1)
    filtered = client.get("/api/insights/explore?group_by=product&categories=Cement").json()
    assert [row["label"] for row in filtered["rows"]] == ["Cement"]
    assert client.get("/api/insights/explore?measure=nonsense").status_code == 422
    heat = client.get("/api/insights/heatmap?measure=orders").json()
    assert sum(sum(week["values"]) for week in heat["weeks"]) == 2
    intel = client.get("/api/insights/products").json()
    assert intel["products"][0]["abc_class"] == "A" and intel["bought_together"] is None
    segments = client.get("/api/insights/segments").json()
    assert segments["customers"][0]["segment"] == "new"


def test_targets_preferences_and_saved_views(client, owner, make_product, make_customer, order_for):
    month = date.today().strftime("%Y-%m")
    assert client.put("/api/targets", json={"month": month, "metric": "booked", "amount": 1000}).status_code == 200
    product = make_product("P", opening_stock=10, mrp="100")
    order_for(make_customer("C"), product, 2)
    target = client.get("/api/insights/overview?period=month").json()["target"]["booked"]
    assert target["target"] == 1000.0 and target["actual"] == 200.0 and target["percent"] == 20.0

    assert client.get("/api/preferences/home.layout").json()["value"] is None
    client.put("/api/preferences/home.layout", json={"value": {"hidden": ["sales"]}})
    assert client.get("/api/preferences/home.layout").json()["value"] == {"hidden": ["sales"]}

    view = client.post("/api/views", json={"page": "products", "name": "Short steel", "state": {"flag": "short"}}).json()
    assert client.get("/api/views?page=products").json()[0]["name"] == "Short steel"
    assert client.delete("/api/views/{}".format(view["id"])).status_code == 204
    assert client.get("/api/views?page=products").json() == []
