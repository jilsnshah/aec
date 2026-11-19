"""Record intelligence: order checks, payment status, timelines, profiles, prices."""
from __future__ import annotations

import pytest

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


def test_order_check_warns_on_credit_cost_discount_and_stock(client, db, owner, make_product, make_customer, order_for):
    cement = make_product("Cement", opening_stock=10, mrp="100")  # opening stock carries no cost
    client.post("/api/stock-receipts", json={"product_id": str(cement.id), "quantity": 10, "unit_cost": 80})
    buyer = make_customer("Builder")
    client.patch("/api/customers/{}".format(buyer.id), json={"credit_limit": 500})
    order_for(buyer, cement, 2, discount_percent=5)
    body = {"customer_id": str(buyer.id), "items": [{"product_id": str(cement.id), "quantity_ordered": 30, "unit_price": 100, "discount_percent": 40}]}
    result = client.post("/api/records/order-check", json=body)
    assert result.status_code == 200, result.text
    kinds = [w["kind"] for w in result.json()["warnings"]]
    assert "credit_limit" in kinds and "high_discount" in kinds and "short" in kinds and "price_change" in kinds
    line = result.json()["lines"][0]
    assert line["net_price"] == 60.0 and line["last_price_to_customer"]["net_price"] == 95.0
    # A normal order at list price raises nothing about price.
    calm = client.post("/api/records/order-check", json={"items": [{"product_id": str(cement.id), "quantity_ordered": 1, "unit_price": 100}]}).json()
    assert not [w for w in calm["warnings"] if w["kind"] in ("below_cost", "thin_margin", "high_discount")]
    assert calm["credit"] is None


def test_payment_status_timeline_and_profile(client, db, owner, make_product, make_customer, order_for):
    cement = make_product("Cement", opening_stock=100, mrp="100")
    buyer = make_customer("Builder")
    order = order_for(buyer, cement, 10)
    delivery_service.create_delivery(db, order.id, [{"order_item_id": order.items[0].id, "quantity": "10"}])
    status = client.get("/api/records/order-payments").json()[str(order.id)]
    assert status["invoiced"] == 1000.0 and status["status"] in ("unpaid", "overdue")
    client.post("/api/payments", json={"direction": "in", "customer_id": str(buyer.id), "amount": 400})
    status = client.get("/api/records/order-payments").json()[str(order.id)]
    assert status["paid"] == 400.0 and status["open"] == 600.0

    events = client.get("/api/records/timeline", params={"customer_id": str(buyer.id)}).json()["events"]
    assert {"order", "delivery", "payment"} <= {e["kind"] for e in events}
    assert client.get("/api/records/timeline", params={"order_id": str(order.id)}).json()["events"]
    assert client.get("/api/records/timeline", params={"product_id": str(cement.id)}).json()["events"]

    profile = client.get("/api/records/customers/{}/profile".format(buyer.id)).json()
    assert profile["orders"] == 1 and profile["account"]["open"] == 600.0
    assert profile["top_products"][0]["name"] == "Cement" and profile["monthly"][0]["booked"] == 1000.0

    prices = client.get("/api/records/products/{}/prices".format(cement.id)).json()
    assert prices["sales"][0]["net_price"] == 100.0 and prices["top_customers"][0]["name"] == "Builder"
    assert client.get("/api/records/customers/00000000-0000-0000-0000-000000000000/profile").status_code == 404


def test_purchase_suggestions_and_scorecard(client, owner, make_product, make_supplier):
    supplier = make_supplier("Mill")
    flour = make_product("Flour", opening_stock=0, mrp="50")
    client.patch("/api/products/{}".format(flour.id), json={"reorder_level": 20, "preferred_supplier_id": str(supplier.id)})
    data = client.get("/api/records/purchase-suggestions").json()
    group = next(g for g in data["groups"] if g["supplier_name"] == "Mill")
    assert group["lines"][0]["name"] == "Flour" and group["lines"][0]["quantity"] > 0
    card = client.get("/api/records/suppliers/{}/scorecard".format(supplier.id)).json()
    assert card["products"] == [] and "score" in card
