"""Stock is bought less sold, and a purchase settles whoever is waiting.

A confirmed purchase order adds to stock the moment it is placed; a sales order
takes from it the moment it is placed. Goods arriving or leaving the warehouse
change neither. Because a purchase counts at once, customers already waiting
are covered from it at once -- and a sale made while bought goods are on the
way is covered by them.
"""
from __future__ import annotations

from decimal import Decimal as D

import pytest


@pytest.fixture()
def widget(client):
    product = client.post(
        "/api/products",
        json={"sku": "STK-1", "name": "Stock widget", "mrp": "10.00", "opening_stock": "10"},
    ).json()
    customer = client.post("/api/customers", json={"name": "Stock Buyer"}).json()
    supplier = client.post("/api/suppliers", json={"name": "Stock Supplier"}).json()
    return product, customer, supplier


def stock(client, product_id):
    return D(client.get("/api/products/{}".format(product_id)).json()["stock"])


def purchase(client, supplier, product, qty, confirm=True):
    return client.post(
        "/api/purchase-orders",
        json={"supplier_id": supplier["id"], "confirm": confirm,
              "items": [{"product_id": product["id"], "quantity_ordered": qty, "unit_cost": "4.00"}]},
    ).json()


def sell(client, customer, product, qty):
    return client.post(
        "/api/orders",
        json={"customer_id": customer["id"],
              "items": [{"product_id": product["id"], "quantity_ordered": qty}]},
    ).json()


def line(client, order):
    return client.get("/api/orders/{}".format(order["id"])).json()["items"][0]


def receive(client, po, qty):
    response = client.post(
        "/api/goods-receipts",
        json={"purchase_order_id": po["id"],
              "lines": [{"purchase_order_item_id": po["items"][0]["id"], "quantity": qty}]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_a_sale_takes_stock_when_placed_and_delivery_moves_nothing(client, widget):
    product, customer, _ = widget
    order = sell(client, customer, product, "4")
    assert stock(client, product["id"]) == D(6)

    response = client.post(
        "/api/orders/{}/deliveries".format(order["id"]),
        json={"lines": [{"order_item_id": order["items"][0]["id"], "quantity": "4"}]},
    )
    assert response.status_code == 201, response.text
    assert stock(client, product["id"]) == D(6)


def test_a_purchase_adds_stock_when_confirmed_and_receiving_moves_nothing(client, widget):
    product, _, supplier = widget
    draft = purchase(client, supplier, product, "20", confirm=False)
    assert stock(client, product["id"]) == D(10)  # a draft is not a purchase yet

    client.post("/api/purchase-orders/{}/confirm".format(draft["id"]))
    view = client.get("/api/products/{}".format(product["id"])).json()
    assert D(view["on_order_quantity"]) == D(20)
    assert D(view["stock"]) == D(30)

    result = receive(client, draft, "12")
    assert D(result["lines"][0]["stock_after"]) == D(30)
    assert stock(client, product["id"]) == D(30)


def test_a_purchase_settles_customers_already_waiting(client, widget):
    product, customer, supplier = widget
    first = sell(client, customer, product, "14")  # 10 from the shelf, 4 short
    second = sell(client, customer, product, "3")  # all 3 short
    assert D(line(client, first)["quantity_unallocated"]) == D(4)
    assert stock(client, product["id"]) == D(-7)

    po = purchase(client, supplier, product, "5")
    # Oldest first: the first order's 4, then 1 of the second order's 3.
    assert D(line(client, first)["quantity_incoming"]) == D(4)
    assert D(line(client, first)["quantity_unallocated"]) == D(0)
    assert D(line(client, second)["quantity_incoming"]) == D(1)
    assert D(line(client, second)["quantity_unallocated"]) == D(2)
    assert D(client.get("/api/purchase-orders/{}".format(po["id"])).json()["items"][0]
             ["quantity_assigned"]) == D(5)
    assert stock(client, product["id"]) == D(-2)


def test_a_sale_is_covered_by_goods_already_bought(client, widget):
    product, customer, supplier = widget
    sell(client, customer, product, "10")  # takes the shelf
    purchase(client, supplier, product, "8")
    order = sell(client, customer, product, "6")
    item = line(client, order)
    assert D(item["quantity_incoming"]) == D(6)
    assert D(item["quantity_unallocated"]) == D(0)
    assert stock(client, product["id"]) == D(2)
    summary = client.get("/api/inventory/summary").json()
    assert [row for row in summary["products_short"] if row["sku"] == "STK-1"] == []


def test_arriving_goods_go_to_the_customers_the_purchase_covered(client, widget):
    product, customer, supplier = widget
    sell(client, customer, product, "10")
    po = purchase(client, supplier, product, "8")
    order = sell(client, customer, product, "6")

    receive(client, po, "6")
    item = line(client, order)
    assert D(item["quantity_reserved"]) == D(6)
    assert D(item["quantity_incoming"]) == D(0)
    assert stock(client, product["id"]) == D(2)


def test_cancelling_a_purchase_takes_its_stock_and_its_cover_back(client, widget):
    product, customer, supplier = widget
    order = sell(client, customer, product, "13")
    po = purchase(client, supplier, product, "5")
    assert D(line(client, order)["quantity_incoming"]) == D(3)
    assert stock(client, product["id"]) == D(2)

    client.post("/api/purchase-orders/{}/cancel".format(po["id"]), json={"reason": "Supplier failed"})
    assert stock(client, product["id"]) == D(-3)
    assert D(line(client, order)["quantity_incoming"]) == D(0)
    assert D(line(client, order)["quantity_unallocated"]) == D(3)


def test_the_user_chooses_who_a_purchase_settles(client, widget):
    product, customer, supplier = widget
    sell(client, customer, product, "10")  # takes the shelf
    older = sell(client, customer, product, "4")
    newer = sell(client, customer, product, "4")

    # Not oldest first: the user gives 3 to the newer order and 2 to the older.
    response = client.post(
        "/api/purchase-orders",
        json={"supplier_id": supplier["id"], "confirm": True,
              "items": [{"product_id": product["id"], "quantity_ordered": "5", "unit_cost": "4"}],
              "settlements": [{"product_id": product["id"], "allocations": [
                  {"order_item_id": newer["items"][0]["id"], "quantity": "3"},
                  {"order_item_id": older["items"][0]["id"], "quantity": "2"},
              ]}]},
    )
    assert response.status_code == 201, response.text
    assert D(line(client, newer)["quantity_incoming"]) == D(3)
    assert D(line(client, older)["quantity_incoming"]) == D(2)


@pytest.mark.parametrize("quantities", [("3", "1"), ("4", "2")])
def test_a_purchase_must_settle_exactly_what_it_can(client, widget, quantities):
    product, customer, supplier = widget
    sell(client, customer, product, "10")
    older = sell(client, customer, product, "4")
    newer = sell(client, customer, product, "4")
    response = client.post(
        "/api/purchase-orders",
        json={"supplier_id": supplier["id"], "confirm": True,
              "items": [{"product_id": product["id"], "quantity_ordered": "5", "unit_cost": "4"}],
              "settlements": [{"product_id": product["id"], "allocations": [
                  {"order_item_id": older["items"][0]["id"], "quantity": quantities[0]},
                  {"order_item_id": newer["items"][0]["id"], "quantity": quantities[1]},
              ]}]},
    )
    assert response.status_code == 422, response.text  # 4 or 6, not the required 5
    assert stock(client, product["id"]) == D(-8)  # nothing was placed


def test_freed_cover_waits_for_the_user_to_settle_it(client, widget):
    product, customer, supplier = widget
    sell(client, customer, product, "10")
    early = sell(client, customer, product, "4")
    late = sell(client, customer, product, "4")
    po = purchase(client, supplier, product, "4")  # no choice sent: oldest first
    assert D(line(client, early)["quantity_incoming"]) == D(4)

    client.post("/api/orders/{}/cancel".format(early["id"]), json={"reason": "Changed mind"})
    # The freed 4 is not handed to anybody automatically.
    assert D(line(client, late)["quantity_unallocated"]) == D(4)
    view = client.get("/api/purchase-orders/{}".format(po["id"])).json()["items"][0]
    assert D(view["quantity_free"]) == D(4)
    assert D(view["settle_required"]) == D(4)

    response = client.post(
        "/api/purchase-orders/{}/settle".format(po["id"]),
        json={"settlements": [{"product_id": product["id"], "allocations": [
            {"order_item_id": late["items"][0]["id"], "quantity": "4"}]}]},
    )
    assert response.status_code == 200, response.text
    assert D(line(client, late)["quantity_incoming"]) == D(4)
    assert D(response.json()["items"][0]["settle_required"]) == D(0)


def test_selling_beyond_what_was_bought_shows_as_short(client, widget):
    product, customer, supplier = widget
    purchase(client, supplier, product, "5")
    sell(client, customer, product, "18")
    summary = client.get("/api/inventory/summary").json()
    short = [row for row in summary["products_short"] if row["sku"] == "STK-1"]
    assert len(short) == 1 and D(short[0]["stock"]) == D(-3)
    rows = client.get("/api/products", params={"sort_by": "stock", "sort_dir": "asc"}).json()["items"]
    assert rows[0]["sku"] == "STK-1"


def test_arriving_goods_default_to_the_customer_the_purchase_was_settled_for(client, widget):
    product, customer, supplier = widget
    sell(client, customer, product, "10")  # takes the shelf
    older = sell(client, customer, product, "4")
    newer = sell(client, customer, product, "4")
    po = client.post(
        "/api/purchase-orders",
        json={"supplier_id": supplier["id"], "confirm": True,
              "items": [{"product_id": product["id"], "quantity_ordered": "4", "unit_cost": "4"}],
              "settlements": [{"product_id": product["id"], "allocations": [
                  {"order_item_id": newer["items"][0]["id"], "quantity": "4"}]}]},
    ).json()

    # No choice sent with the receipt: the older, uncovered order must not jump in.
    receive(client, po, "4")
    assert D(line(client, newer)["quantity_reserved"]) == D(4)
    assert D(line(client, older)["quantity_reserved"]) == D(0)
    assert D(line(client, older)["quantity_unallocated"]) == D(4)

    row = [r for r in client.get("/api/inventory/pending-commitments").json()["rows"]
           if r["order_item_id"] == older["items"][0]["id"]][0]
    assert row["incoming_sources"] == []
    assert row["last_supplier_id"] == supplier["id"]
