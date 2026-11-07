"""Listings page on the server: totals, windows, stable order and bounds."""
from __future__ import annotations

import pytest


@pytest.fixture()
def catalogue(client):
    """Twelve products and one customer with seven orders."""
    products = [
        client.post(
            "/api/products",
            json={"sku": "P-{:02d}".format(n), "name": "Item {:02d}".format(n), "mrp": "10.00",
                  "opening_stock": "100"},
        ).json()
        for n in range(12)
    ]
    customer = client.post("/api/customers", json={"name": "Pager Ltd"}).json()
    for _ in range(7):
        client.post(
            "/api/orders",
            json={"customer_id": customer["id"],
                  "items": [{"product_id": products[0]["id"], "quantity_ordered": "1"}]},
        )
    return products, customer


def test_envelope_reports_total_and_window(client, catalogue):
    page = client.get("/api/products", params={"limit": 5, "offset": 0}).json()
    assert page["total"] == 12
    assert page["limit"] == 5 and page["offset"] == 0
    assert [row["sku"] for row in page["items"]] == ["P-00", "P-01", "P-02", "P-03", "P-04"]

    last = client.get("/api/products", params={"limit": 5, "offset": 10}).json()
    assert [row["sku"] for row in last["items"]] == ["P-10", "P-11"]
    assert last["total"] == 12


def test_pages_do_not_overlap_and_cover_everything(client, catalogue):
    seen = []
    for offset in (0, 3, 6):
        page = client.get("/api/orders", params={"limit": 3, "offset": offset}).json()
        assert page["total"] == 7
        seen.extend(row["id"] for row in page["items"])
    assert len(seen) == 7 and len(set(seen)) == 7


def test_total_respects_filters(client, catalogue):
    page = client.get("/api/products", params={"search": "item 1", "limit": 1}).json()
    assert page["total"] == 2  # Item 10 and Item 11
    assert len(page["items"]) == 1


def test_orders_sort_on_the_server(client, catalogue):
    ascending = client.get("/api/orders", params={"sort_by": "order_number", "sort_dir": "asc"}).json()
    numbers = [row["order_number"] for row in ascending["items"]]
    assert numbers == sorted(numbers)


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 501}, {"offset": -1}])
def test_window_bounds_are_validated(client, params):
    assert client.get("/api/customers", params=params).status_code == 422


def test_every_listing_is_paged(client, catalogue):
    for path in (
        "/api/products",
        "/api/customers",
        "/api/orders",
        "/api/enquiries",
        "/api/suppliers",
        "/api/purchase-orders",
        "/api/goods-receipts",
        "/api/deliveries",
    ):
        body = client.get(path, params={"limit": 2}).json()
        assert set(body) == {"items", "total", "limit", "offset"}, path
        assert len(body["items"]) <= 2


def test_purchase_orders_accept_several_statuses(client):
    response = client.get("/api/purchase-orders", params={"status": "DRAFT,PARTIALLY_RECEIVED"})
    assert response.status_code == 200
    assert client.get("/api/purchase-orders", params={"status": "DRAFT,NOPE"}).status_code in (400, 422)


def test_summary_carries_a_gapless_daily_series(client, catalogue):
    series = client.get("/api/inventory/summary").json()["daily_sales"]
    assert len(series) == 30
    dates = [row["date"] for row in series]
    assert dates == sorted(dates) and len(set(dates)) == 30
    # The seven orders placed by the fixture land on today's bar.
    assert series[-1]["orders"] == 7
    assert float(series[-1]["booked_value"]) == 70.0


def test_customer_listing_summarises_trading(client, catalogue):
    _, customer = catalogue
    row = next(
        item for item in client.get("/api/customers").json()["items"] if item["id"] == customer["id"]
    )
    assert row["order_count"] == 7
    assert row["open_order_count"] == 7  # placed, none delivered yet
    assert float(row["outstanding_quantity"]) == 7.0
    assert float(row["ordered_value"]) == 70.0
    assert row["last_order_at"] is not None


def test_supplier_listing_summarises_what_is_due(client, catalogue):
    products, _ = catalogue
    supplier = client.post("/api/suppliers", json={"name": "Due Co"}).json()
    client.post(
        "/api/purchase-orders",
        json={"supplier_id": supplier["id"], "confirm": True,
              "items": [{"product_id": products[1]["id"], "quantity_ordered": "4", "unit_cost": "2.50"}]},
    )
    row = client.get("/api/suppliers", params={"search": "due co"}).json()["items"][0]
    assert row["po_count"] == 1
    assert row["open_po_count"] == 1
    assert float(row["on_order_quantity"]) == 4.0
    assert float(row["on_order_value"]) == 10.0


def test_products_sort_by_stock_in_less_promised(client, catalogue):
    products, customer = catalogue
    # P-00 already has 7 promised; promise 150 of P-05 so it goes short.
    client.post(
        "/api/orders",
        json={"customer_id": customer["id"],
              "items": [{"product_id": products[5]["id"], "quantity_ordered": "150"}]},
    )
    rows = client.get("/api/products", params={"sort_by": "stock", "sort_dir": "asc"}).json()["items"]
    assert [row["sku"] for row in rows[:2]] == ["P-05", "P-00"]
    assert float(rows[0]["net_stock_position"]) == -50.0
    assert float(rows[1]["net_stock_position"]) == 93.0
