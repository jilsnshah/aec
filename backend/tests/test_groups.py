"""Smart groups, a customer's own pricing, and best-price resolution."""
from __future__ import annotations

from sqlalchemy import text

from app.services import deliveries as delivery_service


def test_groups_fill_by_rules_and_hand(client, db, make_product, make_customer, order_for):
    cement = make_product("Cement", opening_stock=500, mrp="100")
    big = make_customer("Big Builder")
    small = make_customer("Small Shop")
    for _ in range(3):
        order_for(big, cement, 50)
    order_for(small, cement, 1)
    fields = client.get("/api/customer-groups/fields").json()["fields"]
    assert {"spend_12m", "years_with_us", "overdue"} <= {f["key"] for f in fields}
    rules = [{"field": "orders_12m", "op": ">=", "value": 3}, {"field": "spend_12m", "op": ">=", "value": 10000}]
    preview = client.post("/api/customer-groups/preview", json={"rules": rules}).json()
    assert [c["name"] for c in preview["customers"]] == ["Big Builder"]
    group = client.post("/api/customer-groups", json={"name": "Regular builders", "rules": rules})
    assert group.status_code == 201, group.text
    gid = group.json()["id"]
    assert group.json()["member_count"] == 1
    # By hand: add the small shop, then keep the builder out.
    client.put("/api/customer-groups/{}/members/{}".format(gid, small.id), json={"source": "manual"})
    after = client.put("/api/customer-groups/{}/members/{}".format(gid, big.id), json={"source": "excluded"}).json()
    assert after["member_count"] == 1 and {m["source"] for m in after["members"]} == {"manual", "excluded"}
    assert client.post("/api/customer-groups/recalculate").json()["groups"] == 1
    assert client.get("/api/customer-groups/{}".format(gid)).json()["member_count"] == 1
    bad = client.post("/api/customer-groups/preview", json={"rules": [{"field": "magic", "op": ">=", "value": 1}]})
    assert bad.status_code == 422


def test_best_price_wins_across_own_list_and_groups(client, db, make_product, make_customer, order_for):
    cement = make_product("Cement", opening_stock=500, mrp="400")
    sand = make_product("Sand", opening_stock=500, mrp="100")
    buyer = make_customer("Builder")
    order_for(buyer, cement, 1)
    dealers = client.post("/api/price-lists", json={"name": "Dealers", "items": [{"product_id": str(cement.id), "discount_percent": "4"}]}).json()
    gold = client.post("/api/price-lists", json={"name": "Gold", "discount_percent": "6"}).json()
    client.patch("/api/customers/{}".format(buyer.id), json={"price_list_id": dealers["id"]})
    client.post("/api/customer-groups", json={"name": "Anyone who ordered", "rules": [{"field": "orders_total", "op": ">=", "value": 1}], "price_list_id": gold["id"]})
    client.put("/api/customers/{}/pricing".format(buyer.id), json={"discount_percent": "2", "items": [{"product_id": str(sand.id), "price": "80"}]})
    pricing = client.get("/api/customers/{}/pricing".format(buyer.id)).json()
    assert pricing["discount_percent"] == 2.0 and pricing["own_items"][0]["price"] == 80.0 and pricing["groups"][0]["name"] == "Anyone who ordered"
    lines = client.post("/api/price-lists/resolve", json={"customer_id": str(buyer.id), "lines": [
        {"product_id": str(cement.id), "quantity": "10"}, {"product_id": str(sand.id), "quantity": "1"}]}).json()["lines"]
    # Cement: own discount 2, Dealers 4, Gold group 6 -> 6. Sand: own fixed 80 (20% off) beats 6.
    assert lines[0]["discount_percent"] == 6.0 and "Gold" in lines[0]["rule"] or "Anyone" in lines[0]["rule"]
    assert lines[1]["discount_percent"] == 20.0 and lines[1]["rule"].startswith("Own prices")
    assert len(lines[0]["options"]) == 3
    # Own price lists do not show among shared lists.
    assert [l["name"] for l in client.get("/api/price-lists?include_inactive=true").json()["items"]] == ["Dealers", "Gold"]

    enquiry = client.post("/api/enquiries", json={"customer_id": str(buyer.id), "items": [
        {"product_id": str(cement.id), "quantity": "10", "discount_percent": "0"}]}).json()
    applied = client.post("/api/enquiries/{}/apply-prices".format(enquiry["id"])).json()
    assert applied["changed"][0]["to"] == 6.0 and float(applied["enquiry"]["items"][0]["discount_percent"]) == 6.0


def test_overdue_rule(client, db, make_product, make_customer, order_for):
    p = make_product("P", opening_stock=100, mrp="10")
    late = make_customer("Late Payer")
    order = order_for(late, p, 5)
    d = delivery_service.create_delivery(db, order.id, [{"order_item_id": order.items[0].id, "quantity": "5"}])
    db.execute(text("UPDATE customer_deliveries SET created_at = now() - interval '40 days' WHERE id = :id"), {"id": d["delivery_id"]})
    db.commit()
    hits = client.post("/api/customer-groups/preview", json={"rules": [{"field": "oldest_overdue_days", "op": ">", "value": 30}]}).json()
    assert [c["name"] for c in hits["customers"]] == ["Late Payer"]
