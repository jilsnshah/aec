"""Batches and expiry: recorded on receipt, picked earliest expiry first."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.models import Batch, StockCostLayer


def _receive(client, po, qty, **batch):
    return client.post("/api/goods-receipts", json={"purchase_order_id": po["id"], "lines": [
        {"purchase_order_item_id": po["items"][0]["id"], "quantity": qty, **batch}]})


def test_batches_fefo_and_expiry(client, db, make_product, make_supplier, make_customer, order_for):
    paint = make_product("Primer", opening_stock=0, mrp="500")
    client.patch("/api/products/{}".format(paint.id), json={"track_batches": True, "shelf_life_days": 180})
    mill = make_supplier("Paint Co")
    po = client.post("/api/purchase-orders", json={"supplier_id": str(mill.id), "confirm": True, "items": [
        {"product_id": str(paint.id), "quantity_ordered": "30", "unit_cost": "300"}]}).json()
    missing = _receive(client, po, "10")
    assert missing.status_code == 422 and "batch number" in missing.text
    today = date.today()
    # A later-expiring batch arrives first, a sooner-expiring one second.
    assert _receive(client, po, "10", batch_number="L-200", manufactured_on=str(today - timedelta(days=10))).status_code == 201
    assert _receive(client, po, "10", batch_number="L-100", expires_on=str(today + timedelta(days=20))).status_code == 201
    db.expire_all()
    late = db.execute(select(Batch).where(Batch.number == "L-200")).scalar_one()
    assert late.expires_on == today - timedelta(days=10) + timedelta(days=180)
    order = order_for(make_customer("Contractor"), paint, 12)
    d = client.post("/api/orders/{}/deliveries".format(order.id), json={"lines": [{"order_item_id": str(order.items[0].id), "quantity": "12"}]})
    assert d.status_code == 201, d.text
    db.expire_all()
    left = {db.get(Batch, l.batch_id).number: float(l.quantity_remaining) for l in db.execute(select(StockCostLayer).where(StockCostLayer.product_id == paint.id)).scalars()}
    assert left == {"L-100": 0.0, "L-200": 8.0}
    soon = client.get("/api/products/batches", params={"expiring_within_days": 30}).json()["items"]
    assert soon == []  # L-100 is used up
    rows = client.get("/api/products/batches", params={"product_id": str(paint.id)}).json()["items"]
    assert [r["number"] for r in rows] == ["L-200"] and rows[0]["quantity"] == 8
