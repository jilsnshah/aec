"""Enquiry endpoints over HTTP, through to the created sales order."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest


def D(value) -> Decimal:
    return Decimal(str(value))


@pytest.fixture()
def world(client):
    """Two products and a customer, the brief's worked example."""
    product_a = client.post(
        "/api/products",
        json={"sku": "ENQ-A", "name": "Product A", "mrp": "1000.00", "opening_stock": "100",
              "opening_unit_cost": "600.00"},
    ).json()
    product_b = client.post(
        "/api/products",
        json={"sku": "ENQ-B", "name": "Product B", "mrp": "500.00", "opening_stock": "0"},
    ).json()
    customer = client.post("/api/customers", json={"name": "ABC Traders"}).json()
    return product_a, product_b, customer


def test_create_list_and_read_an_enquiry(client, world):
    product_a, product_b, customer = world

    created = client.post(
        "/api/enquiries",
        json={
            "customer_id": customer["id"],
            "notes": "Customer requires delivery in two batches. Call before dispatch.",
            "items": [
                {"product_id": product_a["id"], "quantity": "10", "discount_percent": "15"},
                {"product_id": product_b["id"], "quantity": "20", "discount_percent": "10"},
            ],
        },
    )
    assert created.status_code == 201
    enquiry = created.json()

    assert enquiry["enquiry_number"].startswith("ENQ-")
    assert enquiry["status"] == "OPEN"
    assert enquiry["is_editable"] is True
    assert enquiry["customer"]["name"] == "ABC Traders"
    assert enquiry["item_count"] == 2
    assert D(enquiry["mrp_total"]) == D("20000.00")
    assert D(enquiry["discount_total"]) == D("2500.00")
    assert D(enquiry["total_amount"]) == D("17500.00")

    by_sku = {item["product"]["sku"]: item for item in enquiry["items"]}
    assert D(by_sku["ENQ-A"]["mrp_snapshot"]) == D("1000.0000")
    assert D(by_sku["ENQ-A"]["quoted_unit_price"]) == D("850.0000")
    assert D(by_sku["ENQ-A"]["line_total"]) == D("8500.00")
    assert D(by_sku["ENQ-B"]["line_total"]) == D("9000.00")

    listed = client.get("/api/enquiries").json()["items"]
    assert [row["id"] for row in listed] == [enquiry["id"]]
    assert D(listed[0]["total_amount"]) == D("17500.00")

    assert client.get("/api/enquiries/{}".format(enquiry["id"])).json()["id"] == enquiry["id"]
    assert client.get("/api/enquiries/{}".format(uuid.uuid4())).status_code == 404


def test_client_supplied_prices_are_ignored(client, world):
    product_a, _product_b, customer = world
    enquiry = client.post(
        "/api/enquiries",
        json={
            "customer_id": customer["id"],
            "items": [
                {
                    "product_id": product_a["id"],
                    "quantity": "2",
                    "discount_percent": "0",
                    "mrp_snapshot": "1",
                    "quoted_unit_price": "1",
                    "line_total": "2",
                }
            ],
        },
    ).json()
    assert D(enquiry["items"][0]["mrp_snapshot"]) == D("1000.0000")
    assert D(enquiry["total_amount"]) == D("2000.00")


def test_validation_errors_over_http(client, world):
    product_a, _product_b, customer = world

    assert client.post(
        "/api/enquiries", json={"customer_id": customer["id"], "items": []}
    ).status_code == 422
    assert client.post(
        "/api/enquiries",
        json={"customer_id": customer["id"],
              "items": [{"product_id": product_a["id"], "quantity": "0"}]},
    ).status_code == 422
    assert client.post(
        "/api/enquiries",
        json={"customer_id": customer["id"],
              "items": [{"product_id": product_a["id"], "quantity": "1",
                         "discount_percent": "120"}]},
    ).status_code == 422

    missing = client.post(
        "/api/enquiries",
        json={"customer_id": str(uuid.uuid4()),
              "items": [{"product_id": product_a["id"], "quantity": "1"}]},
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"


def test_edit_an_open_enquiry(client, world):
    product_a, product_b, customer = world
    enquiry = client.post(
        "/api/enquiries",
        json={"customer_id": customer["id"],
              "items": [{"product_id": product_a["id"], "quantity": "10"}]},
    ).json()
    assert D(enquiry["total_amount"]) == D("10000.00")

    patched = client.patch(
        "/api/enquiries/{}".format(enquiry["id"]),
        json={
            "notes": "Revised after a call",
            "items": [
                {"product_id": product_a["id"], "quantity": "10", "discount_percent": "15"},
                {"product_id": product_b["id"], "quantity": "20", "discount_percent": "10"},
            ],
        },
    )
    assert patched.status_code == 200
    assert D(patched.json()["total_amount"]) == D("17500.00")
    assert patched.json()["notes"] == "Revised after a call"

    # Notes alone, leaving the lines untouched.
    notes_only = client.patch(
        "/api/enquiries/{}".format(enquiry["id"]), json={"notes": "Ring first"}
    ).json()
    assert notes_only["notes"] == "Ring first"
    assert D(notes_only["total_amount"]) == D("17500.00")


def test_convert_an_enquiry_and_read_the_order(client, world):
    product_a, product_b, customer = world
    enquiry = client.post(
        "/api/enquiries",
        json={
            "customer_id": customer["id"],
            "notes": "Deliver in two batches.",
            "items": [
                {"product_id": product_a["id"], "quantity": "10", "discount_percent": "15"},
                {"product_id": product_b["id"], "quantity": "20", "discount_percent": "10"},
            ],
        },
    ).json()

    converted = client.post("/api/enquiries/{}/convert".format(enquiry["id"]))
    assert converted.status_code == 201
    payload = converted.json()
    order = payload["order"]

    assert payload["enquiry"]["status"] == "CONVERTED"
    assert payload["enquiry"]["is_editable"] is False
    assert payload["enquiry"]["sales_order_id"] == order["id"]
    assert payload["enquiry"]["sales_order_number"] == order["order_number"]

    assert order["enquiry_id"] == enquiry["id"]
    assert order["enquiry_number"] == enquiry["enquiry_number"]
    assert D(order["total_amount"]) == D("17500.00")
    assert enquiry["enquiry_number"] in order["notes"]

    by_sku = {item["product"]["sku"]: item for item in order["items"]}
    # Product A had stock, so it is reserved; Product B had none, so it waits.
    assert D(by_sku["ENQ-A"]["quantity_reserved"]) == D("10.000")
    assert D(by_sku["ENQ-A"]["quantity_unallocated"]) == D("0.000")
    assert D(by_sku["ENQ-A"]["unit_price_net"]) == D("850.0000")
    assert D(by_sku["ENQ-A"]["mrp_snapshot"]) == D("1000.0000")
    assert D(by_sku["ENQ-B"]["quantity_reserved"]) == D("0.000")
    assert D(by_sku["ENQ-B"]["quantity_unallocated"]) == D("20.000")
    assert D(by_sku["ENQ-B"]["quantity_pending"]) == D("20.000")
    assert order["status"] == "PENDING"

    # The order reads back the same way from its own endpoint.
    fetched = client.get("/api/orders/{}".format(order["id"])).json()
    assert fetched["enquiry_number"] == enquiry["enquiry_number"]
    assert D(fetched["financials"]["totals"]["total_amount"]) == D("17500.00")

    # Product B's shortfall shows up as a negative net position, as in Phase 1.
    inventory = client.get("/api/products/{}/inventory".format(product_b["id"])).json()
    assert D(inventory["net_stock_position"]) == D("-20.000")

    # A second conversion is refused and no second order appears.
    again = client.post("/api/enquiries/{}/convert".format(enquiry["id"]))
    assert again.status_code == 409
    assert again.json()["details"]["sales_order_id"] == order["id"]
    assert len(client.get("/api/orders").json()["items"]) == 1

    # And the closed enquiry is read-only.
    assert client.patch(
        "/api/enquiries/{}".format(enquiry["id"]), json={"notes": "too late"}
    ).status_code == 409


def test_mark_lost_over_http(client, world):
    product_a, _product_b, customer = world
    enquiry = client.post(
        "/api/enquiries",
        json={"customer_id": customer["id"],
              "items": [{"product_id": product_a["id"], "quantity": "5"}]},
    ).json()

    lost = client.post(
        "/api/enquiries/{}/mark-lost".format(enquiry["id"]), json={"reason": "Lost on price"}
    )
    assert lost.status_code == 200
    assert lost.json()["status"] == "LOST"
    assert lost.json()["lost_reason"] == "Lost on price"
    assert lost.json()["is_editable"] is False

    assert client.get("/api/orders").json()["items"] == []
    inventory = client.get("/api/products/{}/inventory".format(product_a["id"])).json()
    assert D(inventory["physical_stock"]) == D("100.000")

    assert client.post("/api/enquiries/{}/convert".format(enquiry["id"])).status_code == 409


def test_listing_filters_over_http(client, world):
    product_a, _product_b, customer = world
    other = client.post("/api/customers", json={"name": "Riverside Supplies"}).json()

    first = client.post(
        "/api/enquiries",
        json={"customer_id": customer["id"],
              "items": [{"product_id": product_a["id"], "quantity": "1"}]},
    ).json()
    second = client.post(
        "/api/enquiries",
        json={"customer_id": other["id"],
              "items": [{"product_id": product_a["id"], "quantity": "2"}]},
    ).json()
    client.post("/api/enquiries/{}/mark-lost".format(second["id"]))

    assert len(client.get("/api/enquiries").json()["items"]) == 2
    assert [row["id"] for row in client.get("/api/enquiries", params={"status": "OPEN"}).json()["items"]] == [
        first["id"]
    ]
    assert [
        row["id"] for row in client.get("/api/enquiries", params={"status": "LOST"}).json()["items"]
    ] == [second["id"]]
    assert [
        row["id"] for row in client.get("/api/enquiries", params={"search": "riverside"}).json()["items"]
    ] == [second["id"]]
    assert [
        row["id"]
        for row in client.get("/api/enquiries", params={"customer_id": customer["id"]}).json()["items"]
    ] == [first["id"]]
    assert len(client.get("/api/enquiries", params={"limit": 1}).json()["items"]) == 1


def test_openapi_documents_the_enquiry_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/enquiries" in paths
    assert "/api/enquiries/{enquiry_id}/convert" in paths
    assert "/api/enquiries/{enquiry_id}/mark-lost" in paths
