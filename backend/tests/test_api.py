"""End-to-end API tests: status codes, payload shapes and error reporting."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest


def D(value) -> Decimal:
    return Decimal(str(value))


@pytest.fixture()
def seeded(client):
    """A product with 15 units and a customer, created through the API."""
    product = client.post(
        "/api/products",
        json={"sku": "WID-1", "name": "Widget", "unit_of_measure": "pcs", "mrp": "250.00",
              "opening_stock": "15"},
    ).json()
    customer = client.post("/api/customers", json={"name": "Customer A", "phone": "555-0100"}).json()
    return product, customer


def test_health_and_openapi(client):
    assert client.get("/api/health").json()["status"] == "ok"
    schema = client.get("/openapi.json").json()
    assert "/api/stock-receipts" in schema["paths"]
    assert "/api/products/{product_id}/pending-orders" in schema["paths"]


def test_product_crud_over_http(client):
    created = client.post(
        "/api/products",
        json={"sku": "abc-1", "name": "Widget", "mrp": "99.50", "opening_stock": "10"},
    )
    assert created.status_code == 201
    product = created.json()
    assert product["sku"] == "ABC-1"
    assert D(product["physical_stock"]) == D("10.000")
    assert D(product["net_stock_position"]) == D("10.000")

    duplicate = client.post("/api/products", json={"sku": "ABC-1", "name": "Clone"})
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "conflict"
    assert "already exists" in duplicate.json()["message"]

    assert client.post("/api/products", json={"sku": "X", "name": "Bad", "mrp": "-1"}).status_code == 422

    patched = client.patch("/api/products/{}".format(product["id"]), json={"name": "Widget Pro"})
    assert patched.status_code == 200
    assert patched.json()["name"] == "Widget Pro"
    # Stock is not editable through the product form.
    assert D(patched.json()["physical_stock"]) == D("10.000")

    archived = client.post("/api/products/{}/archive".format(product["id"]))
    assert archived.status_code == 200
    assert archived.json()["is_active"] is False
    assert client.get("/api/products").json()["items"] == []
    assert len(client.get("/api/products", params={"include_inactive": True}).json()["items"]) == 1

    assert client.get("/api/products/{}".format(uuid.uuid4())).status_code == 404


def test_customer_crud_over_http(client):
    created = client.post("/api/customers", json={"name": "Acme Ltd", "email": "ops@acme.test"})
    assert created.status_code == 201
    customer = created.json()

    assert client.post("/api/customers", json={"name": ""}).status_code == 422

    listed = client.get("/api/customers", params={"search": "acme"}).json()["items"]
    assert [row["id"] for row in listed] == [customer["id"]]

    detail = client.get("/api/customers/{}".format(customer["id"])).json()
    assert detail["orders"] == []
    assert detail["outstanding"] == []

    assert client.patch(
        "/api/customers/{}".format(customer["id"]), json={"phone": "555-1234"}
    ).json()["phone"] == "555-1234"
    assert client.post("/api/customers/{}/archive".format(customer["id"])).json()["is_active"] is False


def test_full_order_and_settlement_flow_over_http(client, seeded):
    product, customer = seeded

    created = client.post(
        "/api/orders",
        json={
            "customer_id": customer["id"],
            "notes": "Rush",
            "items": [{"product_id": product["id"], "quantity_ordered": "20"}],
        },
    )
    assert created.status_code == 201
    order = created.json()
    assert order["order_number"].startswith("SO-")
    # The 15 on hand are reserved, not delivered, so nothing is fulfilled yet.
    assert order["status"] == "PENDING"
    assert order["customer"]["name"] == "Customer A"
    item = order["items"][0]
    assert D(item["quantity_ordered"]) == D("20.000")
    assert D(item["quantity_fulfilled"]) == D("0.000")
    assert D(item["quantity_reserved"]) == D("15.000")
    assert D(item["quantity_unallocated"]) == D("5.000")
    assert D(item["quantity_pending"]) == D("20.000")
    assert item["product"]["sku"] == "WID-1"

    inventory = client.get("/api/products/{}/inventory".format(product["id"])).json()
    assert D(inventory["physical_stock"]) == D("15.000")
    assert D(inventory["reserved_stock"]) == D("15.000")
    assert D(inventory["available_stock"]) == D("0.000")
    assert D(inventory["pending_quantity"]) == D("20.000")
    assert D(inventory["net_stock_position"]) == D("-5.000")
    assert D(inventory["ledger_balance"]) == D("15.000")
    # Reserving moves no stock, so the only movement is the opening stock.
    assert [movement["movement_type"] for movement in inventory["movements"]] == [
        "OPENING_STOCK"
    ]

    preview = client.get(
        "/api/products/{}/pending-orders".format(product["id"]),
        params={"receipt_quantity": "10"},
    ).json()
    assert D(preview["required_allocation"]) == D("5.000")
    assert D(preview["free_stock_after"]) == D("5.000")
    assert len(preview["items"]) == 1
    assert preview["items"][0]["customer_name"] == "Customer A"
    assert D(preview["items"][0]["proposed_allocation"]) == D("5.000")

    receipt = client.post(
        "/api/stock-receipts",
        json={"product_id": product["id"], "quantity": "10", "note": "Lorry 42"},
    )
    assert receipt.status_code == 201
    body = receipt.json()
    assert D(body["allocated_total"]) == D("5.000")
    assert D(body["surplus_quantity"]) == D("5.000")
    assert D(body["physical_stock_after"]) == D("25.000")
    assert D(body["reserved_stock_after"]) == D("20.000")
    assert D(body["available_stock_after"]) == D("5.000")
    assert body["allocations"][0]["order_number"] == order["order_number"]

    refreshed = client.get("/api/orders/{}".format(order["id"])).json()
    # Fully covered by stock, but still owed until it is delivered.
    assert refreshed["status"] == "PENDING"
    assert D(refreshed["items"][0]["quantity_reserved"]) == D("20.000")

    # Deliver it, and only then does the obligation clear.
    delivered = client.post(
        "/api/orders/{}/deliveries".format(order["id"]),
        json={"lines": [{"order_item_id": item["id"], "quantity": "20"}]},
    )
    assert delivered.status_code == 201
    assert D(delivered.json()["order_outstanding_after"]) == D("0.000")

    trail = client.get("/api/stock-receipts/{}/allocations".format(body["receipt_id"])).json()
    assert trail[0]["customer_name"] == "Customer A"

    refreshed = client.get("/api/orders/{}".format(order["id"])).json()
    assert refreshed["status"] == "FULFILLED"
    assert [row["source"] for row in refreshed["allocations"]] == [
        "ORDER_CREATION",
        "STOCK_RECEIPT",
    ]

    summary = client.get("/api/inventory/summary").json()
    assert summary["active_products"] == 1
    assert summary["active_customers"] == 1
    assert D(summary["total_physical_stock"]) == D("5.000")
    assert D(summary["total_pending_quantity"]) == D("0.000")
    assert summary["products_with_negative_position"] == []
    assert summary["recent_orders"][0]["order_number"] == order["order_number"]
    assert summary["recent_receipts"][0]["receipt_number"] == body["receipt_number"]


def test_invalid_allocation_is_rejected_with_a_readable_message(client, seeded):
    product, customer = seeded
    order = client.post(
        "/api/orders",
        json={
            "customer_id": customer["id"],
            "items": [{"product_id": product["id"], "quantity_ordered": "20"}],
        },
    ).json()
    item_id = order["items"][0]["id"]

    response = client.post(
        "/api/stock-receipts",
        json={
            "product_id": product["id"],
            "quantity": "10",
            "allocations": [{"order_item_id": item_id, "quantity": "2"}],
        },
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "allocation_error"
    assert "exactly 5.000" in payload["message"]
    assert payload["details"]["required_allocation"] == "5.000"

    # Nothing changed.
    inventory = client.get("/api/products/{}/inventory".format(product["id"])).json()
    assert D(inventory["physical_stock"]) == D("15.000")
    assert D(inventory["reserved_stock"]) == D("15.000")
    assert D(inventory["pending_quantity"]) == D("20.000")


def test_order_filters_and_cancellation_over_http(client, seeded):
    product, customer = seeded
    other = client.post("/api/customers", json={"name": "Customer B"}).json()

    first = client.post(
        "/api/orders",
        json={"customer_id": customer["id"],
              "items": [{"product_id": product["id"], "quantity_ordered": "20"}]},
    ).json()
    second = client.post(
        "/api/orders",
        json={"customer_id": other["id"],
              "items": [{"product_id": product["id"], "quantity_ordered": "4"}]},
    ).json()

    assert len(client.get("/api/orders").json()["items"]) == 2
    assert [row["id"] for row in client.get("/api/orders", params={"search": "Customer B"}).json()["items"]] == [
        second["id"]
    ]
    # Nothing is delivered on either order yet, so both are pending.
    assert len(client.get("/api/orders", params={"status": "PENDING"}).json()["items"]) == 2
    assert len(client.get("/api/orders", params={"customer_id": customer["id"]}).json()["items"]) == 1

    # Deliver the 15 reserved on the first order so it is partly fulfilled.
    first_item = first["items"][0]
    client.post(
        "/api/orders/{}/deliveries".format(first["id"]),
        json={"lines": [{"order_item_id": first_item["id"], "quantity": "15"}]},
    )

    # A partly delivered order cannot be cancelled outright.
    refused = client.post("/api/orders/{}/cancel".format(first["id"]))
    assert refused.status_code == 409
    assert "cancelled outright" in refused.json()["message"]

    trimmed = client.post(
        "/api/orders/{}/cancel-remaining".format(first["id"]), json={"reason": "Short close"}
    )
    assert trimmed.status_code == 200
    assert D(trimmed.json()["items"][0]["quantity_fulfilled"]) == D("15.000")
    assert D(trimmed.json()["items"][0]["quantity_pending"]) == D("0.000")
    assert trimmed.json()["cancellations"][0]["reason"] == "Short close"

    cancelled = client.post("/api/orders/{}/cancel".format(second["id"]))
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"


def test_order_validation_errors_over_http(client, seeded):
    product, customer = seeded

    assert client.post(
        "/api/orders", json={"customer_id": customer["id"], "items": []}
    ).status_code == 422
    assert client.post(
        "/api/orders",
        json={"customer_id": customer["id"],
              "items": [{"product_id": product["id"], "quantity_ordered": "0"}]},
    ).status_code == 422

    missing_customer = client.post(
        "/api/orders",
        json={"customer_id": str(uuid.uuid4()),
              "items": [{"product_id": product["id"], "quantity_ordered": "1"}]},
    )
    assert missing_customer.status_code == 404
    assert missing_customer.json()["code"] == "not_found"


def test_dashboard_reports_negative_positions(client, seeded):
    product, customer = seeded
    client.post(
        "/api/orders",
        json={"customer_id": customer["id"],
              "items": [{"product_id": product["id"], "quantity_ordered": "20"}]},
    )
    summary = client.get("/api/inventory/summary").json()
    negative = summary["products_with_negative_position"]
    assert len(negative) == 1
    assert negative[0]["sku"] == "WID-1"
    assert D(negative[0]["net_stock_position"]) == D("-5.000")
    assert D(summary["total_pending_quantity"]) == D("20.000")
    assert D(summary["total_reserved_stock"]) == D("15.000")
    assert D(summary["total_available_stock"]) == D("0.000")
    assert D(summary["total_unallocated_quantity"]) == D("5.000")
    assert summary["open_orders"] == 1


def test_money_flows_end_to_end_over_http(client):
    """Buy at a price, sell at a discount, settle later, read the profit back."""
    product = client.post(
        "/api/products",
        json={
            "sku": "MON-1",
            "name": "Widget",
            "mrp": "100.00",
            "opening_stock": "15",
            "opening_unit_cost": "40.00",
        },
    ).json()
    assert D(product["stock_value"]) == D("600.00")
    assert D(product["average_cost"]) == D("40.0000")
    assert D(product["last_purchase_price"]) == D("40.0000")

    customer = client.post("/api/customers", json={"name": "Customer A"}).json()

    created = client.post(
        "/api/orders",
        json={
            "customer_id": customer["id"],
            "items": [
                {
                    "product_id": product["id"],
                    "quantity_ordered": "20",
                    "unit_price": "100.00",
                    "discount_percent": "10",
                }
            ],
        },
    )
    assert created.status_code == 201
    order = created.json()
    assert D(order["subtotal_amount"]) == D("2000.00")
    assert D(order["discount_amount"]) == D("200.00")
    assert D(order["total_amount"]) == D("1800.00")
    assert D(order["items"][0]["unit_price_net"]) == D("90.0000")

    # Nothing is delivered yet, so nothing is earned yet.
    totals = order["financials"]["totals"]
    assert D(totals["delivered_amount"]) == D("0.00")
    assert D(totals["cost_of_goods_sold"]) == D("0.00")
    assert D(totals["pending_amount"]) == D("1800.00")

    # Deliver the 15 that are reserved.
    client.post(
        "/api/orders/{}/deliveries".format(order["id"]),
        json={"lines": [{"order_item_id": order["items"][0]["id"], "quantity": "15"}]},
    )
    totals = client.get("/api/orders/{}".format(order["id"])).json()["financials"]["totals"]
    assert D(totals["delivered_amount"]) == D("1350.00")
    assert D(totals["cost_of_goods_sold"]) == D("600.00")
    assert D(totals["gross_profit"]) == D("750.00")
    assert D(totals["pending_amount"]) == D("450.00")

    receipt = client.post(
        "/api/stock-receipts",
        json={
            "product_id": product["id"],
            "quantity": "10",
            "unit_cost": "50.00",
            "supplier_reference": "INV-9912",
        },
    )
    assert receipt.status_code == 201
    body = receipt.json()
    assert D(body["total_cost"]) == D("500.00")
    assert body["supplier_reference"] == "INV-9912"
    assert D(body["allocated_total"]) == D("5.000")

    # Deliver the newly reserved five, which books their cost.
    client.post(
        "/api/orders/{}/deliveries".format(order["id"]),
        json={"lines": [{"order_item_id": order["items"][0]["id"], "quantity": "5"}]},
    )

    refreshed = client.get("/api/orders/{}".format(order["id"])).json()
    totals = refreshed["financials"]["totals"]
    assert D(totals["delivered_amount"]) == D("1800.00")
    assert D(totals["cost_of_goods_sold"]) == D("850.00")
    assert D(totals["gross_profit"]) == D("950.00")
    assert D(totals["margin_percent"]) == D("52.78")

    inventory = client.get("/api/products/{}/inventory".format(product["id"])).json()
    assert D(inventory["stock_value"]) == D("250.00")
    assert D(inventory["physical_stock"]) == D("5.000")
    assert len(inventory["cost_layers"]) == 1
    assert D(inventory["cost_layers"][0]["unit_cost"]) == D("50.0000")

    summary = client.get("/api/inventory/summary").json()
    assert D(summary["total_stock_value"]) == D("250.00")
    assert D(summary["purchase_spend"]) == D("500.00")
    assert D(summary["revenue_delivered"]) == D("1800.00")
    assert D(summary["gross_profit"]) == D("950.00")
    assert D(summary["discounts_given"]) == D("200.00")


def test_discount_out_of_range_is_rejected_over_http(client):
    product = client.post(
        "/api/products", json={"sku": "MON-2", "name": "Widget", "opening_stock": "5"}
    ).json()
    customer = client.post("/api/customers", json={"name": "Customer A"}).json()
    response = client.post(
        "/api/orders",
        json={
            "customer_id": customer["id"],
            "items": [
                {"product_id": product["id"], "quantity_ordered": "1", "discount_percent": "120"}
            ],
        },
    )
    assert response.status_code == 422
