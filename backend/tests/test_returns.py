"""Sales returns credit the customer, restock at delivered cost, and net out of revenue."""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.api.auth import require_user
from app.main import app
from app.models import Product, StockCostLayer, User
from app.services import deliveries as delivery_service


@pytest.fixture()
def owner(client, db):
    user = User(username="boss", password_hash="x", is_admin=True, session_version=1)
    db.add(user)
    db.commit()
    app.dependency_overrides[require_user] = lambda: user
    return user


def test_return_credits_restocks_and_reverses_profit(client, db, owner, make_product, make_customer, order_for):
    cement = make_product("Cement", opening_stock=0, mrp="100")
    client.post("/api/stock-receipts", json={"product_id": str(cement.id), "quantity": 10, "unit_cost": 60})
    buyer = make_customer("Builder")
    db.expire_all()  # the receipt went through the API; drop this session's stale copy
    order = order_for(buyer, cement, 10)
    delivery_service.create_delivery(db, order.id, [{"order_item_id": order.items[0].id, "quantity": "10"}])
    before = client.get("/api/insights/overview?period=month").json()["current"]
    line = client.get("/api/orders/{}/returnable".format(order.id)).json()["lines"][0]
    assert line["returnable"] == 10
    r = client.post("/api/orders/{}/returns".format(order.id), json={"reason": "excess", "lines": [
        {"order_item_id": line["order_item_id"], "quantity": "3", "restock": True}]})
    assert r.status_code == 201, r.text
    assert r.json()["number"].startswith("CRN-") and r.json()["amount"] == 300.0
    damaged = client.post("/api/orders/{}/returns".format(order.id), json={"reason": "damaged", "lines": [
        {"order_item_id": line["order_item_id"], "quantity": "1", "restock": False}]})
    assert damaged.status_code == 201
    assert client.post("/api/orders/{}/returns".format(order.id), json={"reason": "excess", "lines": [
        {"order_item_id": line["order_item_id"], "quantity": "7"}]}).status_code in (400, 422)

    db.expire_all()
    assert float(db.get(Product, cement.id).physical_stock) == 3.0
    layers = db.execute(select(func.sum(StockCostLayer.quantity_remaining)).where(StockCostLayer.product_id == cement.id)).scalar_one()
    assert float(layers) == 3.0
    statement = client.get("/api/finance/customers/{}/statement".format(buyer.id)).json()
    assert statement["summary"]["open"] == 600.0
    assert [e["kind"] for e in statement["entries"]].count("credit_note") == 2
    after = client.get("/api/insights/overview?period=month").json()["current"]
    assert after["revenue"] == before["revenue"] - 400.0
    assert after["cost_of_goods"] == before["cost_of_goods"] - 180.0  # damaged unit stays as cost
    assert after["returns"] == 2
