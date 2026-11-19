"""Customers and suppliers as full parties: contacts, numbers, sites,
duplicates, merging; product aliases and units."""
from __future__ import annotations

import pytest

from app.api.auth import require_user
from app.main import app
from app.models import User


@pytest.fixture()
def owner(client, db):
    user = User(username="boss", password_hash="x", is_admin=True, session_version=1)
    db.add(user)
    db.commit()
    app.dependency_overrides[require_user] = lambda: user
    return user


def test_numbers_belong_to_one_party_and_find_the_customer(client, owner):
    a = client.post("/api/customers", json={"name": "Sharma Traders", "phone": "+91 98250 12345", "gstin": "24ABCDE1234F1Z5"}).json()
    # Same number in another format: blocked, with the existing record named.
    dup = client.post("/api/customers", json={"name": "Sharma Trading Co", "phone": "098250-12345"})
    assert dup.status_code == 409 and dup.json()["details"]["duplicate"]["id"] == a["id"]
    assert client.post("/api/customers", json={"name": "Other", "gstin": "24ABCDE1234F1Z5"}).status_code == 409
    assert client.post("/api/customers", json={"name": "Bad", "gstin": "123"}).status_code == 422
    # Second number for the same customer; a supplier cannot take it.
    second = client.post("/api/parties/customer/{}/points".format(a["id"]), json={"kind": "phone", "value": "9909911111", "label": "site manager"})
    assert second.status_code == 201
    s = client.post("/api/suppliers", json={"name": "Mill"}).json()
    assert client.post("/api/parties/supplier/{}/points".format(s["id"]), json={"kind": "phone", "value": "+919909911111"}).status_code == 409
    # Either number finds the customer, in lists and in lookup.
    assert client.get("/api/parties/lookup", params={"phone": "+91 99099 11111"}).json()["id"] == a["id"]
    assert [c["id"] for c in client.get("/api/customers", params={"search": "99099"}).json()["items"]] == [a["id"]]
    similar = client.get("/api/parties/customer/duplicates", params={"name": "Sharma Trading"}).json()
    assert similar["similar"][0]["id"] == a["id"]


def test_contacts_sites_on_orders_and_profile(client, owner, make_product):
    c = client.post("/api/customers", json={"name": "Builder", "phone": "9000000001", "address": "Main road"}).json()
    contact = client.post("/api/parties/customer/{}/contacts".format(c["id"]), json={"name": "Ravi", "role": "Site engineer"}).json()
    site = client.post("/api/parties/customer/{}/addresses".format(c["id"]), json={"kind": "site", "label": "Tower A", "line": "Plot 7, Sector 21", "city": "Gandhinagar"}).json()
    profile = client.get("/api/parties/customer/{}/profile".format(c["id"])).json()
    assert {a["kind"] for a in profile["addresses"]} == {"billing", "site"} and profile["contacts"][0]["name"] == "Ravi"
    p = make_product("Cement", opening_stock=10, mrp="100")
    order = client.post("/api/orders", json={"customer_id": c["id"], "contact_id": contact["id"], "delivery_address_id": site["id"],
                                             "items": [{"product_id": str(p.id), "quantity_ordered": "1"}]})
    assert order.status_code == 201, order.text
    assert order.json()["delivery_address_id"] == site["id"]
    other = client.post("/api/customers", json={"name": "Someone else"}).json()
    bad = client.post("/api/orders", json={"customer_id": other["id"], "delivery_address_id": site["id"], "items": [{"product_id": str(p.id), "quantity_ordered": "1"}]})
    assert bad.status_code == 422
    # Removing the primary phone clears the customer's single phone field.
    point = profile["points"][0]
    client.patch("/api/parties/customer/{}/points/{}".format(c["id"], point["id"]), json={"is_active": False})
    assert client.get("/api/customers/{}".format(c["id"])).json()["phone"] is None


def test_merge_moves_everything(client, db, owner, make_product):
    keep = client.post("/api/customers", json={"name": "Patel Hardware", "phone": "9111111111"}).json()
    drop = client.post("/api/customers", json={"name": "Patel Hardwares", "phone": "9222222222"}).json()
    p = make_product("Nails", opening_stock=10, mrp="5")
    client.post("/api/orders", json={"customer_id": drop["id"], "items": [{"product_id": str(p.id), "quantity_ordered": "2"}]})
    r = client.post("/api/parties/customer/{}/merge".format(keep["id"]), json={"merge_id": drop["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["moved"]["sales_orders"] == 1
    assert client.get("/api/parties/lookup", params={"phone": "9222222222"}).json()["id"] == keep["id"]
    assert client.get("/api/customers/{}".format(drop["id"])).json()["is_active"] is False
    assert client.get("/api/audit").json()["events"][0]["action"] == "merge_customer"


def test_product_aliases_units_and_matching(client, owner, make_product, make_supplier):
    rod = make_product("TMT bar 8mm", opening_stock=0, mrp="60")
    mill = make_supplier("Mill")
    assert client.post("/api/products/{}/aliases".format(rod.id), json={"value": "8mm sariya"}).status_code == 201
    client.post("/api/products/{}/aliases".format(rod.id), json={"kind": "barcode", "value": "8901234567890"})
    client.post("/api/products/{}/aliases".format(rod.id), json={"kind": "supplier_code", "value": "TMT-08", "supplier_id": str(mill.id)})
    other = make_product("Wire", opening_stock=0)
    assert client.post("/api/products/{}/aliases".format(other.id), json={"value": "8MM Sariya"}).status_code == 409
    assert client.post("/api/products/{}/units".format(rod.id), json={"name": "bundle", "factor": "10"}).status_code == 201
    hits = client.get("/api/products/match", params={"q": "8mm sariya"}).json()["items"]
    assert hits[0]["name"] == "TMT bar 8mm" and hits[0]["other_units"] == [{"name": "bundle", "factor": 10.0, "for_sales": True}]
    assert client.get("/api/products/match", params={"q": "8901234567890"}).json()["items"][0]["matched_by"].startswith("barcode")
    names = client.get("/api/products/{}/names".format(rod.id)).json()
    assert {a["kind"] for a in names["aliases"]} == {"alias", "barcode", "supplier_code"}
