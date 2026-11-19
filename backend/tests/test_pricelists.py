"""Price lists: quantity breaks, fixed prices, list discount, validity."""
from __future__ import annotations


def test_price_list_resolves_best_break(client, make_product, make_customer):
    cement = make_product("Cement", opening_stock=0, mrp="400")
    sand = make_product("Sand", opening_stock=0, mrp="100")
    created = client.post("/api/price-lists", json={"name": "Contractors", "discount_percent": "5", "items": [
        {"product_id": str(cement.id), "min_quantity": "0", "discount_percent": "4"},
        {"product_id": str(cement.id), "min_quantity": "100", "price": "360"},
    ]})
    assert created.status_code == 201, created.text
    list_id = created.json()["id"]
    buyer = make_customer("Mason")
    assert client.patch("/api/customers/{}".format(buyer.id), json={"price_list_id": list_id}).status_code == 200
    r = client.post("/api/price-lists/resolve", json={"customer_id": str(buyer.id), "lines": [
        {"product_id": str(cement.id), "quantity": "10"}, {"product_id": str(cement.id), "quantity": "150"}, {"product_id": str(sand.id), "quantity": "1"}]}).json()
    assert [l["discount_percent"] for l in r["lines"]] == [4.0, 10.0, 5.0]
    assert r["lines"][1]["net_price"] == 360.0 and "fixed price" in r["lines"][1]["rule"]
    assert client.get("/api/price-lists").json()["items"][0]["customers"] == 1
    # A customer without a list pays MRP.
    other = make_customer("Walk-in")
    assert client.post("/api/price-lists/resolve", json={"customer_id": str(other.id), "lines": [{"product_id": str(sand.id)}]}).json()["lines"][0]["discount_percent"] == 0
    # Switched off: MRP again.
    client.put("/api/price-lists/{}".format(list_id), json={"name": "Contractors", "is_active": False})
    assert client.post("/api/price-lists/resolve", json={"customer_id": str(buyer.id), "lines": [{"product_id": str(sand.id)}]}).json()["lines"][0]["discount_percent"] == 0


def test_price_list_validation(client, make_product):
    p = make_product("P", mrp="10")
    bad = [
        {"name": ""},
        {"name": "X", "items": [{"product_id": str(p.id), "price": "5", "discount_percent": "3"}]},
        {"name": "X", "items": [{"product_id": str(p.id), "discount_percent": "120"}]},
    ]
    for body in bad:
        assert client.post("/api/price-lists", json=body).status_code in (409, 422), body
    assert client.post("/api/price-lists", json={"name": "Dealers"}).status_code == 201
    assert client.post("/api/price-lists", json={"name": "dealers"}).status_code == 409
