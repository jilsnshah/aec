"""Business intelligence and follow-ups."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text

from app.services import deliveries as delivery_service
from app.services import enquiries as enquiry_service


def _deliver(db, order, quantity):
    item = order.items[0]
    return delivery_service.create_delivery(db, order.id, [{"order_item_id": item.id, "quantity": str(quantity)}])


def test_overview_counts_revenue_when_goods_leave_and_compares_periods(client, db, make_product, make_customer, order_for):
    cement = make_product("Cement", opening_stock=10, mrp="100")
    buyer = make_customer("Buyer")
    order = order_for(buyer, cement, 4)
    _deliver(db, order, 3)
    data = client.get("/api/insights/overview?period=month").json()
    current = data["current"]
    assert current["orders"] == 1 and current["booked_value"] == 400.0
    assert current["revenue"] == 300.0 and current["deliveries"] == 1
    assert current["gross_profit"] == current["revenue"] - current["cost_of_goods"]
    assert data["previous"]["orders"] == 0
    assert data["daily"][-1]["booked"] == 400.0


def test_inventory_health_flags_short_stock_and_recommends_a_reorder(client, make_product, make_customer, order_for):
    sand = make_product("Sand", opening_stock=2, mrp="50")
    order_for(make_customer("B"), sand, 9)
    data = client.get("/api/insights/inventory").json()
    row = next(p for p in data["products"] if p["name"] == "Sand")
    assert row["short"] == 7.0 and "short" in row["flags"] and "reorder" in row["flags"]
    # Enough to cover what is owed plus a month of sales at the current rate.
    assert row["reorder_quantity"] >= 7
    assert data["totals"]["short_quantity_products"] == 1


def test_old_unsold_stock_is_dead_and_counts_as_capital_at_risk(client, db, make_product):
    make_product("Old tiles", opening_stock=5, mrp="10")
    db.execute(text("UPDATE stock_cost_layers SET created_at = now() - interval '120 days'"))
    db.commit()
    data = client.get("/api/insights/inventory").json()
    row = next(p for p in data["products"] if p["name"] == "Old tiles")
    assert "dead" in row["flags"] and row["oldest_stock_days"] >= 119
    assert row["ages"]["90+"]["quantity"] == 5.0
    assert data["totals"]["dead_stock_value"] == row["stock_value"]


def test_sales_breakdown_by_customer(client, make_product, make_customer, order_for):
    cement = make_product("Cement", opening_stock=20, mrp="100")
    order_for(make_customer("Big"), cement, 8)
    order_for(make_customer("Small"), cement, 2)
    items = client.get("/api/insights/sales?group_by=customer&period=last_30").json()["items"]
    assert [item["name"] for item in items] == ["Big", "Small"]
    assert items[0]["share_of_booked_percent"] == 80.0


def test_stale_enquiries_need_a_follow_up_until_one_is_planned(client, db, make_product, make_customer):
    product = make_product("Rods", opening_stock=0, mrp="500")
    customer = make_customer("Prospect")
    enquiry = enquiry_service.create_enquiry(db, customer.id, [{"product_id": product.id, "quantity": "3"}])
    db.execute(text("UPDATE customer_enquiries SET updated_at = now() - interval '10 days'"))
    db.commit()
    funnel = client.get("/api/insights/enquiries").json()
    assert funnel["stale"][0]["enquiry_number"] == enquiry.enquiry_number and funnel["stale_without_follow_up"] == 1
    alerts = client.get("/api/insights/alerts").json()["alerts"]
    assert any(alert["kind"] == "stale_enquiry" for alert in alerts)

    response = client.post("/api/tasks", json={"title": "Call Prospect", "enquiry_id": str(enquiry.id),
                                               "due_date": (date.today() + timedelta(days=1)).isoformat()})
    assert response.status_code == 201, response.text
    assert client.get("/api/insights/enquiries").json()["stale_without_follow_up"] == 0
    assert not any(alert["kind"] == "stale_enquiry" for alert in client.get("/api/insights/alerts").json()["alerts"])


def test_follow_ups_can_be_planned_rescheduled_and_closed(client, make_customer):
    customer = make_customer("Acme")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    created = client.post("/api/tasks", json={"title": "Chase payment", "customer_id": str(customer.id),
                                              "due_date": yesterday, "priority": "HIGH"}).json()
    assert created["overdue"] is True and created["customer_name"] == "Acme" and created["source"] == "manual"
    assert client.get("/api/tasks/counts").json() == {"open": 1, "overdue": 1, "due_today": 0}
    assert client.get("/api/tasks?due=overdue").json()["total"] == 1
    assert any(alert["kind"] == "overdue_follow_up" for alert in client.get("/api/insights/alerts").json()["alerts"])
    moved = client.patch("/api/tasks/{}".format(created["id"]), json={"due_date": date.today().isoformat()}).json()
    assert moved["overdue"] is False
    done = client.patch("/api/tasks/{}".format(created["id"]), json={"status": "DONE"}).json()
    assert done["status"] == "DONE" and done["completed_at"]
    assert client.get("/api/tasks?status=OPEN").json()["total"] == 0
    assert client.post("/api/tasks", json={"title": " "}).status_code == 422
    assert client.post("/api/tasks", json={"title": "x", "customer_id": "00000000-0000-0000-0000-000000000000"}).status_code == 404


def test_briefing_brings_it_together(client, make_product, make_customer, order_for):
    sand = make_product("Sand", opening_stock=0, mrp="50")
    order_for(make_customer("B"), sand, 3)
    data = client.get("/api/insights/briefing").json()
    assert data["today"]["orders"] == 1
    assert data["alert_counts"].get("critical") == 1
    assert data["top_alerts"][0]["kind"] == "short_stock"
