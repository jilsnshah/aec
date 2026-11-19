"""Units of measure: lines entered in any of a product's units, stock in its base unit."""
from __future__ import annotations


def _setup(client, make_product):
    cement = make_product("Cement", opening_stock=1000, mrp="400")
    client.patch("/api/products/{}".format(cement.id), json={"whole_units": True, "brand": "UltraTech", "hsn_code": "2523", "gst_rate": "28",
                                                            "weight_kg": "50", "specs": [{"name": "Grade", "value": "OPC 53"}, {"name": "", "value": "x"}]})
    assert client.post("/api/products/{}/units".format(cement.id), json={"name": "tonne", "factor": "20"}).status_code == 201
    return cement


def test_product_details_and_units(client, make_product):
    cement = _setup(client, make_product)
    out = client.get("/api/products/{}".format(cement.id)).json()
    assert out["brand"] == "UltraTech" and out["hsn_code"] == "2523" and float(out["gst_rate"]) == 28
    assert out["specs"] == [{"name": "Grade", "value": "OPC 53"}]
    assert [u["name"] for u in out["units"]] == [cement.unit_of_measure, "tonne"]
    out = client.patch("/api/products/{}".format(cement.id), json={"sales_unit": "tons"}).json()
    assert out["sales_unit"] == "tonne"
    bad = client.patch("/api/products/{}".format(cement.id), json={"sales_unit": "brass"})
    assert bad.status_code == 422


def test_order_enquiry_and_po_in_other_units(client, make_product, make_customer, make_supplier):
    cement = _setup(client, make_product)
    buyer = make_customer("Builder")
    order = client.post("/api/orders", json={"customer_id": str(buyer.id), "items": [
        {"product_id": str(cement.id), "quantity_ordered": "2", "unit": "Tonnes", "unit_price": "7000", "discount_percent": "0"}]})
    assert order.status_code == 201, order.text
    line = order.json()["items"][0]
    assert float(line["quantity_ordered"]) == 40 and float(line["unit_price"]) == 350
    assert line["unit"] == "tonne" and float(line["unit_quantity"]) == 2 and float(line["unit_rate"]) == 7000 and line["unit_name"] == "tonne"
    # Whole bags only: 1.33 tonne is 26.6 bags.
    half = client.post("/api/orders", json={"customer_id": str(buyer.id), "items": [
        {"product_id": str(cement.id), "quantity_ordered": "1.33", "unit": "tonne"}]})
    assert half.status_code == 422 and "whole" in half.text
    unknown = client.post("/api/orders", json={"customer_id": str(buyer.id), "items": [
        {"product_id": str(cement.id), "quantity_ordered": "1", "unit": "brass"}]})
    assert unknown.status_code == 422 and "tonne" in unknown.text
    # Enquiry in tonnes converts into an order line in tonnes.
    enq = client.post("/api/enquiries", json={"customer_id": str(buyer.id), "items": [
        {"product_id": str(cement.id), "quantity": "3", "unit": "tonne", "discount_percent": "5"}]}).json()
    item = enq["items"][0]
    assert float(item["quantity"]) == 60 and item["unit"] == "tonne" and float(item["unit_quantity"]) == 3 and float(item["unit_rate"]) == 7600
    conv = client.post("/api/enquiries/{}/convert".format(enq["id"]), json={})
    assert conv.status_code == 201, conv.text
    oid = conv.json().get("order", {}).get("id") or conv.json().get("sales_order_id")
    oline = client.get("/api/orders/{}".format(oid)).json()["items"][0]
    assert oline["unit"] == "tonne" and float(oline["quantity_ordered"]) == 60
    # Purchase in tonnes at a per-tonne cost.
    supplier = make_supplier("Mill")
    po = client.post("/api/purchase-orders", json={"supplier_id": str(supplier.id), "items": [
        {"product_id": str(cement.id), "quantity_ordered": "5", "unit": "tonne", "unit_cost": "6000"}]})
    assert po.status_code == 201, po.text
    pline = po.json()["items"][0]
    assert float(pline["quantity_ordered"]) == 100 and float(pline["unit_cost"]) == 300 and float(pline["unit_rate"]) == 6000


def test_units_for_sales_or_purchase_only(client, make_product, make_customer):
    sand = make_product("Sand", opening_stock=500, mrp="50")
    names = client.post("/api/products/{}/units".format(sand.id), json={"name": "truck", "factor": "400", "for_sales": False}).json()
    assert names["units"][0]["for_sales"] is False
    buyer = make_customer("Mason")
    bad = client.post("/api/orders", json={"customer_id": str(buyer.id), "items": [
        {"product_id": str(sand.id), "quantity_ordered": "1", "unit": "truck"}]})
    assert bad.status_code == 422 and "not sold" in bad.text


def test_agents_see_every_detail_and_order_in_units(client, db, session_factory, make_product, make_customer, monkeypatch):
    from app.services import units as unit_service
    from app.voice.tools import CallTools

    cement = _setup(client, make_product)
    client.patch("/api/products/{}".format(cement.id), json={"description": "Ordinary Portland cement for RCC work."})
    buyer = make_customer("Builder", phone="+91 98250 11111")
    db.expire_all()
    card = unit_service.product_card(db, db.get(type(cement), cement.id), buyer.id)
    assert card["description"].startswith("Ordinary") and card["details"] == [{"name": "Grade", "value": "OPC 53"}]
    assert card["brand"] == "UltraTech" and {"unit": "tonne", "holds": "20 {}".format(cement.unit_of_measure)} in card["sold_in"]
    # The phone agent orders in tonnes; the order line keeps the tonne.
    flow = client.get("/api/automation/flows/sales").json()
    for node in flow["nodes"]:
        if node["data"]["step"] == "sales.confirm_order":
            node["data"].update({"actors": ["person", "pai"], "mode": "auto", "limits": []})
    assert client.put("/api/automation/flows/sales", json={"nodes": flow["nodes"], "edges": flow["edges"]}).status_code == 200
    call = CallTools(session_factory, "+919825011111")
    call.identify()
    details = call.run("product_details", {"product_id": str(cement.id)})
    assert details["description"].startswith("Ordinary")
    ready = call.run("prepare_order", {"items": [{"product_id": str(cement.id), "quantity": 2, "unit": "tonne"}]})
    assert "error" not in ready, ready
    assert "2 tonne" in ready["read_back"][0] and "per tonne" in ready["read_back"][0]
    placed = call.run("place_order", {})
    assert "placed" in placed, placed
    order = client.get("/api/orders?limit=5").json()["items"][0]
    line = client.get("/api/orders/{}".format(order["id"])).json()["items"][0]
    assert line["unit"] == "tonne" and float(line["quantity_ordered"]) == 40
