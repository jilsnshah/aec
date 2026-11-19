"""Warehouses, stock per warehouse, and transfers with landed costs."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

from app.models import Product, StockCostLayer


def _layers_match_stock(db, product_id):
    db.expire_all()
    layers = db.execute(select(func.coalesce(func.sum(StockCostLayer.quantity_remaining), 0)).where(StockCostLayer.product_id == product_id)).scalar_one()
    return Decimal(layers) == db.get(Product, product_id).physical_stock


def _stock(client, product_id):
    return {r["warehouse"]: r for r in client.get("/api/warehouses/stock", params={"product_id": str(product_id)}).json()["items"]}


def test_warehouses_and_transfer_with_costs(client, db, make_product, make_customer, order_for):
    houses = client.get("/api/warehouses").json()["items"]
    main = next(h for h in houses if h["is_default"])
    assert main["name"] == "Main godown" and any(h["kind"] == "transit" for h in houses)
    yard = client.post("/api/warehouses", json={"name": "Yard 2", "kind": "yard", "address": "Changodar"})
    assert yard.status_code == 201, yard.text
    yard = yard.json()
    assert yard["code"] == "YARD2"
    cement = make_product("Cement", opening_stock=100, opening_unit_cost="300", mrp="400")
    steel = make_product("Steel", opening_stock=50, opening_unit_cost="100", mrp="150")
    assert _stock(client, cement.id)["Main godown"]["quantity"] == 100

    draft = client.post("/api/stock-transfers", json={
        "to_warehouse_id": yard["id"],
        "items": [{"product_id": str(cement.id), "quantity": "40"}, {"product_id": str(steel.id), "quantity": "10"}],
        "costs": [{"kind": "freight", "amount": "400", "paid_to": "Shree Transport"}, {"kind": "loading", "amount": "100"}],
        "vehicle": "GJ01AB1234",
    })
    assert draft.status_code == 201, draft.text
    tr = draft.json()
    assert tr["status"] == "draft" and tr["from_warehouse"] == "Main godown" and tr["costs_total"] == 500
    too_much = client.post("/api/stock-transfers", json={"to_warehouse_id": yard["id"], "items": [{"product_id": str(cement.id), "quantity": "500"}], "dispatch": True})
    assert too_much.status_code == 422 and "Only" in too_much.text

    sent = client.post("/api/stock-transfers/{}/dispatch".format(tr["id"])).json()
    assert sent["status"] == "in_transit" and sent["goods_value"] == 40 * 300 + 10 * 100
    stock = _stock(client, cement.id)
    assert stock["Main godown"]["quantity"] == 60 and stock["In transit"]["quantity"] == 40
    assert _layers_match_stock(db, cement.id)
    # On the road, goods cannot be sold from anywhere.
    buyer = make_customer("Builder")
    order_for(buyer, cement, 80)
    db.expire_all()

    lines = {i["product"]: i for i in sent["items"]}
    got = client.post("/api/stock-transfers/{}/receive".format(tr["id"]), json={
        "lines": [{"item_id": lines["Cement"]["id"], "quantity_received": "38"}, {"item_id": lines["Steel"]["id"], "quantity_received": "10"}],
        "note": "2 bags torn"})
    assert got.status_code == 200, got.text
    got = got.json()
    assert got["status"] == "received" and got["loss_value"] == 600
    items = {i["product"]: i for i in got["items"]}
    # Spread by quantity over what arrived: 500 x 38/48 to cement, 500 x 10/48 to steel.
    assert abs(items["Cement"]["extra_cost"] - 395.83) < 0.01 and abs(items["Steel"]["extra_cost"] - 104.17) < 0.01
    assert items["Cement"]["unit_cost_after"] == round(300 + 395.83 / 38, 2)
    stock = _stock(client, cement.id)
    assert stock["Yard 2"]["quantity"] == 38 and "In transit" not in stock and stock["Main godown"]["quantity"] == 60
    assert abs(stock["Yard 2"]["value"] - (38 * 300 + 395.83)) < 0.02
    assert _layers_match_stock(db, cement.id) and _layers_match_stock(db, steel.id)
    assert float(client.get("/api/products/{}".format(cement.id)).json()["physical_stock"]) == 98


def test_deliver_receive_adjust_per_warehouse(client, db, make_product, make_customer, order_for):
    yard = client.post("/api/warehouses", json={"name": "Site store", "kind": "site"}).json()
    sand = make_product("Sand", opening_stock=20, opening_unit_cost="50", mrp="80")
    # Stock in straight to the site store.
    receipt = client.post("/api/stock-receipts", json={"product_id": str(sand.id), "quantity": "30", "unit_cost": "55", "warehouse_id": yard["id"]})
    assert receipt.status_code in (200, 201), receipt.text
    assert _stock(client, sand.id)["Site store"]["quantity"] == 30
    buyer = make_customer("Mason")
    db.expire_all()
    order = order_for(buyer, sand, 25)
    item = order.items[0]
    bad = client.post("/api/orders/{}/deliveries".format(order.id), json={"lines": [{"order_item_id": str(item.id), "quantity": "25"}], "warehouse_id": next(
        h["id"] for h in client.get("/api/warehouses").json()["items"] if h["is_default"])})
    assert bad.status_code == 422 and "only 20" in bad.text
    ok = client.post("/api/orders/{}/deliveries".format(order.id), json={"lines": [{"order_item_id": str(item.id), "quantity": "25"}], "warehouse_id": yard["id"]})
    assert ok.status_code in (200, 201), ok.text
    assert _stock(client, sand.id)["Site store"]["quantity"] == 5
    # Count the site store: 3 on the shelf.
    counted = client.post("/api/stock-adjustments", json={"lines": [{"product_id": str(sand.id), "counted_quantity": "3", "warehouse_id": yard["id"]}], "as_count": True})
    assert counted.status_code == 201, counted.text
    stock = _stock(client, sand.id)
    assert stock["Site store"]["quantity"] == 3 and stock["Main godown"]["quantity"] == 20
    assert _layers_match_stock(db, sand.id)
    # A closed warehouse must be empty; the default cannot be closed.
    assert client.put("/api/warehouses/{}".format(yard["id"]), json={"is_active": False}).status_code == 422


def test_cancel_in_transit_and_weight_method(client, db, make_product):
    yard = client.post("/api/warehouses", json={"name": "Shop", "kind": "shop"}).json()
    tiles = make_product("Tiles", opening_stock=100, opening_unit_cost="20", mrp="30")
    client.patch("/api/products/{}".format(tiles.id), json={"weight_kg": "2"})
    tr = client.post("/api/stock-transfers", json={"to_warehouse_id": yard["id"], "items": [{"product_id": str(tiles.id), "quantity": "50"}],
                                                   "costs": [{"kind": "freight", "amount": "100"}], "cost_method": "weight", "dispatch": True}).json()
    assert tr["status"] == "in_transit"
    back = client.post("/api/stock-transfers/{}/cancel".format(tr["id"])).json()
    assert back["status"] == "cancelled"
    stock = _stock(client, tiles.id)
    assert stock["Main godown"]["quantity"] == 100 and stock["Main godown"]["value"] == 2000
    assert _layers_match_stock(db, tiles.id)
