"""Credit and pricing controls at order entry, admin override, audit log."""
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


def body(customer, product, qty, discount="0"):
    return {"customer_id": str(customer.id), "items": [{"product_id": str(product.id), "quantity_ordered": str(qty), "discount_percent": discount}]}


def test_credit_block_and_admin_override(client, db, owner, make_product, make_customer, order_for):
    cement = make_product("Cement", opening_stock=100, mrp="100")
    buyer = make_customer("Builder")
    client.patch("/api/customers/{}".format(buyer.id), json={"credit_limit": 1000})
    # Warn mode (default): goes through, check reports it.
    assert client.post("/api/orders", json=body(buyer, cement, 15)).status_code == 201
    client.put("/api/integrations/controls", json={"config": {"credit_check": "block"}})
    held = client.post("/api/orders", json=body(buyer, cement, 1))
    assert held.status_code == 409 and held.json()["code"] == "on_hold"
    assert held.json()["details"]["holds"][0]["kind"] == "credit_limit" and held.json()["details"]["can_override"] is True
    assert client.post("/api/orders?override=true", json=body(buyer, cement, 1)).status_code == 409  # reason needed
    ok = client.post("/api/orders?override=true&override_reason=Paid+by+cheque+today", json=body(buyer, cement, 1))
    assert ok.status_code == 201, ok.text
    events = client.get("/api/audit").json()["events"]
    assert events[0]["action"] == "control_override" and "cheque" in events[0]["summary"]


def test_non_admin_cannot_override_and_discount_cap(client, db, make_product, make_customer):
    clerk = User(username="clerk", password_hash="x", is_admin=False, session_version=1)
    db.add(clerk)
    db.commit()
    app.dependency_overrides[require_user] = lambda: clerk
    p = make_product("Tile", opening_stock=10, mrp="50")
    c = make_customer("Shop")
    client.put("/api/integrations/controls", json={"config": {"max_discount_percent": 10}})
    assert client.post("/api/orders", json=body(c, p, 1, "5")).status_code == 201
    r = client.post("/api/orders?override=true&override_reason=x", json=body(c, p, 1, "20"))
    assert r.status_code == 409 and r.json()["details"]["can_override"] is False
    check = client.post("/api/controls/check", json=body(c, p, 1, "20")).json()
    assert check["holds"][0]["kind"] == "discount"
