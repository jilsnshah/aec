"""Stock counts and adjustments keep ledger, physical stock, cost layers and
reservations in step."""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.api.auth import require_user
from app.main import app
from app.models import Product, StockCostLayer, User


@pytest.fixture()
def owner(client, db):
    user = User(username="boss", password_hash="x", is_admin=True, session_version=1)
    db.add(user)
    db.commit()
    app.dependency_overrides[require_user] = lambda: user
    return user


def layers(db, product_id):
    return float(db.execute(select(func.coalesce(func.sum(StockCostLayer.quantity_remaining), 0)).where(StockCostLayer.product_id == product_id)).scalar_one())


def test_count_posts_differences_valued_at_cost(client, db, owner, make_product):
    cement = make_product("Cement", opening_stock=0, mrp="100")
    client.post("/api/stock-receipts", json={"product_id": str(cement.id), "quantity": 10, "unit_cost": 80})
    sand = make_product("Sand", opening_stock=0, mrp="50")
    client.post("/api/stock-receipts", json={"product_id": str(sand.id), "quantity": 5, "unit_cost": 40})
    r = client.post("/api/stock-adjustments", json={"as_count": True, "lines": [
        {"product_id": str(cement.id), "counted_quantity": "7"},
        {"product_id": str(sand.id), "counted_quantity": "5"},
    ]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["count_number"].startswith("CNT-") and body["adjusted"] == 1 and body["matched"] == 1
    assert body["value_change"] == -240.0
    db.expire_all()
    assert float(db.get(Product, cement.id).physical_stock) == 7.0 and layers(db, cement.id) == 7.0
    listed = client.get("/api/stock-adjustments").json()
    assert listed["total"] == 1 and listed["by_reason"][0]["reason"] == "count"
    sheet = client.get("/api/stock-adjustments/count-sheet").json()["products"]
    assert next(p for p in sheet if p["name"] == "Cement")["last_counted"]


def test_loss_below_reserved_makes_newest_order_short(client, db, owner, make_product, make_customer, order_for):
    rod = make_product("Rod", opening_stock=0, mrp="10")
    client.post("/api/stock-receipts", json={"product_id": str(rod.id), "quantity": 10, "unit_cost": 6})
    first = order_for(make_customer("Early"), rod, 6)
    second = order_for(make_customer("Late"), rod, 4)
    r = client.post("/api/stock-adjustments", json={"lines": [{"product_id": str(rod.id), "quantity_change": "-3", "reason": "damaged", "note": "rusted"}]})
    assert r.status_code == 201, r.text
    assert r.json()["released_to_short"] == 3.0
    early = client.get("/api/orders/{}".format(first.id)).json()["items"][0]
    late = client.get("/api/orders/{}".format(second.id)).json()["items"][0]
    assert float(early["quantity_reserved"]) == 6 and float(late["quantity_reserved"]) == 1 and float(late["quantity_unallocated"]) == 3
    # Found stock goes to the customer who is waiting.
    found = client.post("/api/stock-adjustments", json={"lines": [{"product_id": str(rod.id), "quantity_change": "2", "reason": "found"}]})
    assert found.status_code == 201, found.text
    late = client.get("/api/orders/{}".format(second.id)).json()["items"][0]
    assert float(late["quantity_reserved"]) == 3
    db.expire_all()
    assert float(db.get(Product, rod.id).physical_stock) == layers(db, rod.id) == 9.0


def test_adjustments_are_validated(client, owner, make_product):
    p = make_product("P", opening_stock=2)
    bad = [
        {"lines": []},
        {"lines": [{"product_id": str(p.id), "quantity_change": "-5", "reason": "lost"}]},
        {"lines": [{"product_id": str(p.id), "quantity_change": "1", "reason": "magic"}]},
        {"lines": [{"product_id": str(p.id), "counted_quantity": "-1"}]},
    ]
    for body in bad:
        assert client.post("/api/stock-adjustments", json=body).status_code in (400, 409, 422), body
    assert client.get("/api/stock-adjustments").json()["total"] == 0


def test_quotation_pdf(client, owner, make_product, make_customer):
    cement = make_product("Cement", opening_stock=5, mrp="100")
    buyer = make_customer("Builder")
    enquiry = client.post("/api/enquiries", json={"customer_id": str(buyer.id), "items": [{"product_id": str(cement.id), "quantity": "3", "discount_percent": "10"}]})
    assert enquiry.status_code == 201, enquiry.text
    pdf = client.get("/api/enquiries/{}/quotation.pdf".format(enquiry.json()["id"]))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
