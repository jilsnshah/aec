"""Transporters, landed costs, purchase returns, rate contracts and bookings."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.models import Product, StockCostLayer


def _po(client, supplier, product, qty, cost="300", unit=None):
    item = {"product_id": str(product.id), "quantity_ordered": qty}
    if cost is not None:
        item["unit_cost"] = cost
    if unit:
        item["unit"] = unit
    response = client.post("/api/purchase-orders", json={"supplier_id": str(supplier.id), "confirm": True, "items": [item]})
    assert response.status_code == 201, response.text
    return response.json()


def _receive(client, po, qty, **extra):
    response = client.post("/api/goods-receipts", json={"purchase_order_id": po["id"],
                                                          "lines": [{"purchase_order_item_id": po["items"][0]["id"], "quantity": qty}], **extra})
    assert response.status_code == 201, response.text
    return response.json()


def _layers_ok(db, product_id):
    db.expire_all()
    total = db.execute(select(func.coalesce(func.sum(StockCostLayer.quantity_remaining), 0)).where(StockCostLayer.product_id == product_id)).scalar_one()
    return Decimal(total) == db.get(Product, product_id).physical_stock


def test_transporter_record_vehicles_rates_and_estimate(client, make_customer):
    t = client.post("/api/transporters", json={
        "name": "Shree Ganesh Roadlines", "kind": "fleet_owner", "phone": "98250 22222", "gstin": "24AAACS1234F1Z5",
        "tally_ledger_name": "Shree Ganesh Roadlines (Freight)", "service_areas": "Ahmedabad, Gandhinagar", "payment_terms_days": 15,
        "vehicles": [{"number": "gj 01 ab 1234", "vehicle_type": "10_wheeler", "capacity_kg": "16000", "driver_name": "Ramesh", "driver_phone": "9000011111"}],
        "rates": [{"from_place": "Ahmedabad", "to_place": "Gandhinagar", "vehicle_type": "10_wheeler", "basis": "trip", "rate": "4500"},
                  {"basis": "tonne", "rate": "350", "min_charge": "2000"}],
    })
    assert t.status_code == 201, t.text
    t = t.json()
    assert t["code"].startswith("TRN") and t["vehicles"][0]["number"] == "GJ01AB1234" and len(t["rates"]) == 2
    assert t["profile"]["points"][0]["value"] == "98250 22222"
    # The same number cannot belong to a customer too.
    clash = client.post("/api/customers", json={"name": "Someone", "phone": "9825022222"})
    assert clash.status_code == 409
    # Contacts work like any party.
    contact = client.post("/api/parties/transporter/{}/contacts".format(t["id"]), json={"name": "Mukesh", "role": "Booking"})
    assert contact.status_code == 201, contact.text
    found = client.get("/api/parties/lookup", params={"phone": "9825022222"}).json()
    assert found["kind"] == "transporter"
    est = client.get("/api/transporters/estimate", params={"from_place": "Ahmedabad", "to_place": "Gandhinagar", "vehicle_type": "10_wheeler", "weight_kg": 4000}).json()["items"]
    assert est[0]["amount"] == 4500 and est[0]["match"] == 4
    est = client.get("/api/transporters/estimate", params={"from_place": "Surat", "to_place": "Vapi", "weight_kg": 4000}).json()["items"]
    assert est[0]["amount"] == 2000 and est[0]["note"] == "minimum charge"
    listed = client.get("/api/transporters", params={"search": "GJ01AB"}).json()["items"]
    assert [x["name"] for x in listed] == ["Shree Ganesh Roadlines"]


def test_freight_on_delivery_and_payment_to_transporter(client, make_product, make_customer, order_for, db):
    t = client.post("/api/transporters", json={"name": "City Tempo"}).json()
    cement = make_product("Cement", opening_stock=50, mrp="400")
    buyer = make_customer("Builder")
    order = order_for(buyer, cement, 10)
    d = client.post("/api/orders/{}/deliveries".format(order.id), json={
        "lines": [{"order_item_id": str(order.items[0].id), "quantity": "10"}],
        "transporter_id": t["id"], "vehicle_number": "gj01 cd 5555", "lr_number": "LR-77", "freight_amount": "1200"})
    assert d.status_code == 201, d.text
    stmt = client.get("/api/transporters/{}/statement".format(t["id"])).json()
    assert stmt["summary"]["billed"] == 1200 and stmt["entries"][0]["detail"].endswith("LR LR-77")
    paid = client.post("/api/payments", json={"direction": "out", "amount": "1000", "transporter_id": t["id"], "method": "upi"})
    assert paid.status_code in (200, 201), paid.text
    assert client.get("/api/transporters/{}".format(t["id"])).json()["statement"]["balance"] == 200


def test_landed_cost_goes_into_stock_cost(client, db, make_product, make_supplier, make_customer, order_for):
    t = client.post("/api/transporters", json={"name": "Mill Carrier"}).json()
    cement = make_product("Cement", opening_stock=0, mrp="400")
    steel = make_product("Steel", opening_stock=0, mrp="100")
    client.patch("/api/products/{}".format(cement.id), json={"weight_kg": "50"})
    client.patch("/api/products/{}".format(steel.id), json={"weight_kg": "10"})
    mill = make_supplier("Mill")
    po = client.post("/api/purchase-orders", json={"supplier_id": str(mill.id), "confirm": True, "items": [
        {"product_id": str(cement.id), "quantity_ordered": "100", "unit_cost": "300"},
        {"product_id": str(steel.id), "quantity_ordered": "100", "unit_cost": "60"}]}).json()
    lines = [{"purchase_order_item_id": i["id"], "quantity": "100"} for i in po["items"]]
    grn = client.post("/api/goods-receipts", json={"purchase_order_id": po["id"], "lines": lines, "transporter_id": t["id"],
                                                    "vehicle_number": "GJ05XY9999", "lr_number": "B-101",
                                                    "costs": [{"kind": "freight", "amount": "3000"}, {"kind": "unloading", "amount": "600", "paid_to": "Labour"}],
                                                    "cost_method": "weight"})
    assert grn.status_code == 201, grn.text
    landed = grn.json()["landed_cost"]
    lines = {l["product"]: l for l in landed["lines"]}
    # By weight: cement 5000 kg, steel 1000 kg -> 3000 / 600 of the 3600.
    assert lines["Cement"]["amount"] == 3000 and lines["Steel"]["amount"] == 600 and landed["on_stock"] == 3600
    product = client.get("/api/products/{}".format(cement.id)).json()
    assert float(product["average_cost"]) == 330
    # The transporter is owed the freight (not the labour).
    assert client.get("/api/transporters/{}/statement".format(t["id"])).json()["summary"]["billed"] == 3000
    # Half the cement is sold; a later bill is split between stock left and goods sold.
    buyer = make_customer("Builder")
    db.expire_all()
    order = order_for(buyer, cement, 50)
    client.post("/api/orders/{}/deliveries".format(order.id), json={"lines": [{"order_item_id": str(order.items[0].id), "quantity": "50"}]})
    later = client.post("/api/goods-receipts/{}/landed-costs".format(grn.json()["receipt_id"]), json={
        "charges": [{"kind": "insurance", "amount": "120"}], "method": "quantity"}).json()
    cement_line = next(l for l in later["lines"] if l["product"] == "Cement")
    assert cement_line["amount"] == 60 and cement_line["on_stock"] == 30 and cement_line["on_sold"] == 30
    assert _layers_ok(db, cement.id)


def test_purchase_return_debit_note_and_replacement(client, db, make_product, make_supplier):
    cement = make_product("Cement", opening_stock=0, mrp="400")
    mill = make_supplier("Mill")
    po = _po(client, mill, cement, "100")
    grn = _receive(client, po, "100")
    payable = client.get("/api/finance/suppliers/{}/statement".format(mill.id))
    assert payable.status_code == 200, payable.text
    assert payable.json()["summary"]["open"] == 30000
    can = client.get("/api/goods-receipts/{}/returnable".format(grn["receipt_id"])).json()
    line = can["lines"][0]
    back = client.post("/api/purchase-returns", json={"goods_receipt_id": grn["receipt_id"], "reason": "damaged", "note": "torn bags", "replace": True,
                                                      "lines": [{"goods_receipt_item_id": line["goods_receipt_item_id"], "quantity": "8"}]})
    assert back.status_code == 201, back.text
    back = back.json()
    assert back["amount"] == 2400 and back["number"].startswith("PRN")
    assert float(client.get("/api/products/{}".format(cement.id)).json()["physical_stock"]) == 92
    statement = client.get("/api/finance/suppliers/{}/statement".format(mill.id)).json()
    assert statement["summary"]["open"] == 27600 and any(e["kind"] == "debit_note" for e in statement["entries"])
    po_after = client.get("/api/purchase-orders/{}".format(po["id"])).json()
    assert float(po_after["items"][0]["quantity_received"]) == 92 and po_after["status"] == "PARTIALLY_RECEIVED"
    too_many = client.post("/api/purchase-returns", json={"goods_receipt_id": grn["receipt_id"], "reason": "excess",
                                                          "lines": [{"goods_receipt_item_id": line["goods_receipt_item_id"], "quantity": "93"}]})
    assert too_many.status_code == 422
    assert _layers_ok(db, cement.id)


def test_rate_contracts_for_supplier_and_customer(client, db, make_product, make_supplier, make_customer):
    cement = make_product("Cement", opening_stock=100, opening_unit_cost="300", mrp="400")
    client.post("/api/products/{}/units".format(cement.id), json={"name": "tonne", "factor": "20"})
    mill = make_supplier("Mill")
    today = date.today()
    rc = client.post("/api/rate-contracts", json={"supplier_id": str(mill.id), "title": "Annual rate", "valid_from": str(today - timedelta(days=1)),
                                                   "valid_until": str(today + timedelta(days=200)),
                                                   "items": [{"product_id": str(cement.id), "rate": "6400", "unit": "tonne", "committed_quantity": "100"}]})
    assert rc.status_code == 201, rc.text
    rc = rc.json()
    assert rc["status"] == "active" and rc["items"][0]["rate"] == 320 and rc["items"][0]["committed_quantity"] == 2000
    po = _po(client, mill, cement, "200", cost=None)
    assert float(po["items"][0]["unit_cost"]) == 320
    used = client.get("/api/rate-contracts/{}".format(rc["id"])).json()["items"][0]
    assert used["used_quantity"] == 200 and used["used_percent"] == 10
    rates = client.get("/api/rate-contracts/supplier-rates", params={"supplier_id": str(mill.id)}).json()["rates"]
    assert rates[str(cement.id)]["rate"] == 320
    # A customer's project rate competes with their other prices.
    builder = make_customer("Builder")
    client.post("/api/rate-contracts", json={"customer_id": str(builder.id), "title": "Tower A", "items": [{"product_id": str(cement.id), "rate": "360"}]})
    lines = client.post("/api/price-lists/resolve", json={"customer_id": str(builder.id), "lines": [{"product_id": str(cement.id), "quantity": "10"}]}).json()["lines"]
    assert lines[0]["net_price"] == 360 and lines[0]["rule"].startswith("Contract RC")
    # Expired contracts stop applying.
    client.patch("/api/rate-contracts/{}".format(rc["id"]), json={"valid_from": str(today - timedelta(days=30)), "valid_until": str(today - timedelta(days=2))})
    po2 = _po(client, mill, cement, "10", cost=None)
    assert float(po2["items"][0]["unit_cost"]) == 0


def test_booking_from_order_with_estimate(client, make_product, make_customer, order_for):
    t = client.post("/api/transporters", json={"name": "Quick Tempo", "rates": [{"basis": "trip", "rate": "900", "vehicle_type": "tempo"}]}).json()
    cement = make_product("Cement", opening_stock=50, mrp="400")
    client.patch("/api/products/{}".format(cement.id), json={"weight_kg": "50"})
    order = order_for(make_customer("Builder", address="Site 4, Gota"), cement, 20)
    b = client.post("/api/transport-bookings", json={"reference_type": "sales_order", "reference_id": str(order.id), "transporter_id": t["id"], "vehicle_type": "tempo"})
    assert b.status_code == 201, b.text
    b = b.json()
    assert b["purpose"] == "delivery" and b["weight_kg"] == 1000 and b["estimate"] == 900 and "Gota" in b["to_place"]
    done = client.patch("/api/transport-bookings/{}".format(b["id"]), json={"status": "confirmed", "agreed_amount": "850", "vehicle_number": "GJ01TT1111"}).json()
    assert done["status"] == "confirmed" and done["confirmed_at"]


def _add_book_step(client, flow, **data):
    current = client.get("/api/automation/flows/{}".format(flow)).json()
    lib = {s["key"]: s for s in client.get("/api/automation/library").json()["steps"]}
    step = lib["{}.book_transport".format(flow)]
    node = {"id": "bt", "type": "step", "position": {"x": 0, "y": 900}, "data": {
        "step": step["key"], "title": step["label"], "actors": data.get("actors", ["tai"]), "mode": data.get("mode", "auto"),
        "limits": data.get("limits", []), "ai": {"model": "", "instructions": ""}, "channels": data.get("channels", ["whatsapp"]),
        "timing": {**step["timing"], **data.get("timing", {})}, "notes": ""}}
    saved = client.put("/api/automation/flows/{}".format(flow), json={"nodes": current["nodes"] + [node], "edges": current["edges"]})
    assert saved.status_code == 200, saved.text


def test_tai_books_transport_when_order_placed(client, db, session_factory, monkeypatch, make_product, make_customer):
    from app.services import automation as _automation

    monkeypatch.setattr(_automation, "PARKED", set())  # the automatic booking is parked in the app; still keep it working
    from app.models import OutboundMessage, TransportBooking
    from app.services import inbound, transport_automation

    monkeypatch.setattr(inbound, "session_factory", session_factory)
    cheap = client.post("/api/transporters", json={"name": "Cheap Lines", "phone": "9000000001", "rates": [{"basis": "trip", "rate": "800"}]}).json()
    dear = client.post("/api/transporters", json={"name": "Dear Lines", "phone": "9000000002", "rates": [{"basis": "trip", "rate": "1500"}]}).json()
    _add_book_step(client, "sales", mode="limits", limits=[{"field": "over_estimate_percent", "op": "<=", "value": 10}])
    cement = make_product("Cement", opening_stock=50, mrp="400")
    buyer = make_customer("Builder")
    order = client.post("/api/orders", json={"customer_id": str(buyer.id), "items": [{"product_id": str(cement.id), "quantity_ordered": "5"}]})
    assert order.status_code == 201, order.text
    db.expire_all()
    booking = db.execute(select(TransportBooking)).scalars().one()
    assert booking.status == "requested" and str(booking.transporter_id) == cheap["id"] and booking.requested_by == "tai"
    asked = db.execute(select(OutboundMessage).where(OutboundMessage.to == "9000000001")).scalars().one()
    assert booking.number in asked.body and "YES" in asked.body
    # Reply 15% above the card: over the 10% limit, so a person must confirm.
    from app.models import Transporter

    result = transport_automation.handle_reply(db, db.get(Transporter, booking.transporter_id), "haan bhai, GJ01 AB 4321 kal subah, 920 rupees")
    assert result["status"] == "requested" and result["vehicle_number"] == "GJ01AB4321" and result["agreed_amount"] == 920
    # A clear NO moves on to the next transporter automatically.
    result = transport_automation.handle_reply(db, db.get(Transporter, booking.transporter_id), "nahi, gaadi nahi hai")
    assert result["transporter"] == "Dear Lines" and result["status"] == "requested"
    result = transport_automation.handle_reply(db, db.get(Transporter, uuid_of(dear)), "Yes GJ05ZZ1111 1500")
    assert result["status"] == "confirmed" and result["agreed_amount"] == 1500


def uuid_of(row):
    import uuid

    return uuid.UUID(row["id"])


def test_pai_calls_transporter_for_pickup(client, db, session_factory, monkeypatch, make_product, make_supplier):
    from app.services import automation as _automation

    monkeypatch.setattr(_automation, "PARKED", set())  # the automatic booking is parked in the app; still keep it working
    from app.models import TransportBooking
    from app.services import inbound
    from app.voice import outbound

    monkeypatch.setattr(inbound, "session_factory", session_factory)
    calls = []
    monkeypatch.setattr(outbound, "place_call", lambda to, mode, params=None: calls.append((to, mode, params)) or "CA123")
    client.post("/api/transporters", json={"name": "Phone Only", "phone": "9000000003", "booking_channel": "call", "rates": [{"basis": "trip", "rate": "700"}]})
    _add_book_step(client, "purchase", actors=["pai"], channels=["call"])
    cement = make_product("Cement", opening_stock=0, mrp="400")
    _po(client, make_supplier("Mill"), cement, "100")
    db.expire_all()
    booking = db.execute(select(TransportBooking)).scalars().one()
    assert booking.status == "requested" and booking.requested_by == "pai" and booking.purpose == "purchase"
    assert calls == [("9000000003", "book", {"booking": str(booking.id)})]


def test_transport_booking_is_parked(client, db, session_factory, monkeypatch, make_product, make_customer):
    """Transport is booked by hand for now: no automatic request, no step in the editor."""
    from app.models import TransportBooking
    from app.services import inbound

    monkeypatch.setattr(inbound, "session_factory", session_factory)
    client.post("/api/transporters", json={"name": "Cheap Lines", "phone": "9000000001", "rates": [{"basis": "trip", "rate": "800"}]})
    cement = make_product("Cement", opening_stock=50, mrp="400")
    buyer = make_customer("Builder")
    assert client.post("/api/orders", json={"customer_id": str(buyer.id), "items": [{"product_id": str(cement.id), "quantity_ordered": "5"}]}).status_code == 201
    db.expire_all()
    assert db.execute(select(TransportBooking)).scalars().all() == []
    steps = {s["key"] for s in client.get("/api/automation/library").json()["steps"]}
    assert "sales.book_transport" not in steps and "purchase.book_transport" not in steps
