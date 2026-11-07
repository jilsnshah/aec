"""Purchase cost, line discounts and the profit that falls out of them."""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.errors import ValidationError
from app.models import MovementType, StockCostLayer, StockLayerConsumption
from app.services import costing
from app.services import inventory as inventory_service
from app.services import orders as order_service
from app.services import products as product_service
from tests.conftest import (
    D,
    M,
    assert_costing_invariant,
    cost_state,
    deliver_all,
    resync,
    state,
    stock_state,
)


# ---------------------------------------------------------------------------
# Line pricing and discounts
# ---------------------------------------------------------------------------

def test_line_price_defaults_to_mrp_and_discount_applies(db, make_product, make_customer, order_for):
    product = make_product("Widget", opening_stock=20, mrp="100.00")
    customer = make_customer("Customer A")

    order = order_for(customer, product, 10, discount_percent="10")
    item = order.items[0]

    assert item.unit_price == Decimal("100.0000")
    assert item.discount_percent == M(10)
    assert item.unit_price_net == Decimal("90.0000")

    assert order.subtotal_amount == M(1000)
    assert order.discount_amount == M(100)
    assert order.total_amount == M(900)


def test_explicit_price_overrides_mrp(db, make_product, make_customer, order_for):
    product = make_product("Widget", opening_stock=20, mrp="100.00")
    customer = make_customer("Customer A")

    order = order_for(customer, product, 4, unit_price="125.50", discount_percent="20")
    item = order.items[0]

    assert item.unit_price == Decimal("125.5000")
    assert item.unit_price_net == Decimal("100.4000")
    assert order.subtotal_amount == M("502.00")
    assert order.total_amount == M("401.60")
    assert order.discount_amount == M("100.40")


def test_order_totals_add_up_across_lines(db, make_product, make_customer, make_order):
    first = make_product("First", opening_stock=50, mrp="200.00", sku="P-1")
    second = make_product("Second", opening_stock=50, mrp="50.00", sku="P-2")
    customer = make_customer("Customer A")

    order = make_order(
        customer,
        [
            {"product_id": first.id, "quantity_ordered": 3, "discount_percent": "25"},
            {"product_id": second.id, "quantity_ordered": 10, "discount_percent": "0"},
        ],
    )

    # 3 x 200 = 600 less 25% = 450; 10 x 50 = 500 at no discount.
    assert order.subtotal_amount == M(1100)
    assert order.discount_amount == M(150)
    assert order.total_amount == M(950)


@pytest.mark.parametrize("bad_discount", ["-5", "101", "250"])
def test_discount_outside_zero_to_hundred_is_rejected(
    db, make_product, make_customer, bad_discount
):
    product = make_product("Widget", opening_stock=10)
    customer = make_customer("Customer A")
    with pytest.raises(ValidationError, match="between 0 and 100"):
        order_service.create_order(
            db,
            customer.id,
            [
                {
                    "product_id": product.id,
                    "quantity_ordered": 1,
                    "discount_percent": bad_discount,
                }
            ],
        )
    assert db.execute(select(func.count()).select_from(StockCostLayer)).scalar_one() == 1


def test_negative_price_is_rejected(db, make_product, make_customer):
    product = make_product("Widget", opening_stock=10)
    customer = make_customer("Customer A")
    with pytest.raises(ValidationError, match="cannot be negative"):
        order_service.create_order(
            db,
            customer.id,
            [{"product_id": product.id, "quantity_ordered": 1, "unit_price": "-10"}],
        )


# ---------------------------------------------------------------------------
# FIFO costing
# ---------------------------------------------------------------------------

def test_opening_stock_opens_a_cost_layer(db, make_product):
    product = make_product("Widget", opening_stock=15, opening_unit_cost="40.00")

    layers = db.execute(select(StockCostLayer)).scalars().all()
    assert len(layers) == 1
    assert layers[0].source == MovementType.OPENING_STOCK
    assert layers[0].unit_cost == Decimal("40.0000")
    assert layers[0].quantity_remaining == D(15)

    valuation = cost_state(db, product.id)
    assert valuation["stock_value"] == M(600)
    assert valuation["average_cost"] == Decimal("40.0000")
    assert product.last_purchase_price == Decimal("40.0000")
    assert_costing_invariant(db, product.id)


def test_cost_of_goods_sold_is_drawn_oldest_batch_first(db, make_product, make_customer, order_for):
    """Two batches at different prices; a sale consumes the cheaper one first."""
    product = make_product("Widget", opening_stock=0, mrp="100.00")
    inventory_service.receive_stock(db, product.id, 10, purchase_unit_cost="40.00")
    inventory_service.receive_stock(db, product.id, 10, purchase_unit_cost="50.00")

    customer = make_customer("Customer A")
    order = order_for(customer, product, 15)
    # Cost of goods is recognised when the goods go out, so deliver them.
    deliver_all(db, order)

    financials = order_service.order_financials(db, order_service.get_order(db, order.id))
    # 10 units at 40 plus 5 units at 50.
    assert financials["totals"]["cost_of_goods_sold"] == M(650)
    assert financials["totals"]["delivered_amount"] == M(1500)
    assert financials["totals"]["gross_profit"] == M(850)

    # The single allocation spans both batches, and says so.
    allocations = order_service.order_allocations(db, order.id)
    assert len(allocations) == 1
    assert allocations[0]["cost_amount"] == M(650)
    trail = costing.cost_trail(db, [allocations[0]["allocation_id"]])[allocations[0]["allocation_id"]]
    assert [(row["quantity"], row["unit_cost"]) for row in trail] == [
        (D(10), Decimal("40.0000")),
        (D(5), Decimal("50.0000")),
    ]

    valuation = cost_state(db, product.id)
    assert valuation["layer_quantity"] == D(5)
    assert valuation["stock_value"] == M(250)
    assert valuation["average_cost"] == Decimal("50.0000")
    assert_costing_invariant(db, product.id)


def test_profit_is_recognised_only_on_delivered_units(db, make_product, make_customer, order_for):
    """The full worked example: short order, then settlement by a dearer batch."""
    product = make_product("Widget", opening_stock=15, opening_unit_cost="40.00", mrp="100.00")
    customer = make_customer("Customer A")
    order = order_for(customer, product, 20, discount_percent="10")
    # The 15 on hand were reserved; delivering them is what earns the revenue.
    deliver_all(db, order)

    financials = order_service.order_financials(db, order_service.get_order(db, order.id))
    totals = financials["totals"]
    assert totals["subtotal_amount"] == M(2000)
    assert totals["discount_amount"] == M(200)
    assert totals["total_amount"] == M(1800)
    # Only the 15 delivered units have earned anything, and only they have a cost.
    assert totals["delivered_amount"] == M(1350)
    assert totals["cost_of_goods_sold"] == M(600)
    assert totals["gross_profit"] == M(750)
    assert totals["margin_percent"] == M("55.56")
    assert totals["pending_amount"] == M(450)

    # The settling batch cost more, so the margin on the whole order falls.
    receipt = inventory_service.receive_stock(db, product.id, 10, purchase_unit_cost="50.00")
    assert receipt["unit_cost"] == Decimal("50.0000")
    assert receipt["total_cost"] == M(500)
    assert receipt["allocated_total"] == D(5)
    assert receipt["allocations"][0]["revenue"] == M(450)

    # Those five are reserved, not sold: delivering them is what books the cost.
    resync(db)
    deliver_all(db, order_service.get_order(db, order.id))

    resync(db)
    totals = order_service.order_financials(db, order_service.get_order(db, order.id))["totals"]
    assert totals["delivered_amount"] == M(1800)
    assert totals["cost_of_goods_sold"] == M(850)
    assert totals["gross_profit"] == M(950)
    assert totals["margin_percent"] == M("52.78")
    assert totals["pending_amount"] == M(0)

    assert stock_state(db, product.id) == {
        "physical": D(5),
        "reserved": D(0),
        "available": D(5),
        "pending": D(0),
        "net": D(5),
    }
    assert_costing_invariant(db, product.id)


def test_per_line_profit_is_reported_separately(db, make_product, make_customer, make_order):
    cheap = make_product("Cheap", opening_stock=10, opening_unit_cost="10.00", mrp="25.00", sku="C-1")
    dear = make_product("Dear", opening_stock=10, opening_unit_cost="80.00", mrp="100.00", sku="D-1")
    customer = make_customer("Customer A")

    order = make_order(
        customer,
        [
            {"product_id": cheap.id, "quantity_ordered": 10},
            {"product_id": dear.id, "quantity_ordered": 10, "discount_percent": "10"},
        ],
    )
    deliver_all(db, order)
    financials = order_service.order_financials(db, order_service.get_order(db, order.id))
    by_product = {line["product_id"]: line for line in financials["lines"]}

    assert by_product[cheap.id]["gross_profit"] == M(150)
    assert by_product[cheap.id]["margin_percent"] == M("60.00")
    # 10 at 90 = 900 revenue against 800 of cost.
    assert by_product[dear.id]["gross_profit"] == M(100)
    assert by_product[dear.id]["margin_percent"] == M("11.11")
    assert financials["totals"]["gross_profit"] == M(250)


def test_stock_received_with_no_recorded_cost_is_valued_at_zero(db, make_product):
    """An unrecorded purchase price is honest about being unknown."""
    product = make_product("Widget", opening_stock=0)
    inventory_service.receive_stock(db, product.id, 10)
    valuation = cost_state(db, product.id)
    assert valuation["stock_value"] == M(0)
    assert valuation["average_cost"] == Decimal("0.0000")
    assert_costing_invariant(db, product.id)


def test_costing_invariant_holds_through_a_full_cycle(
    db, make_product, make_customer, order_for
):
    product = make_product("Widget", opening_stock=15, opening_unit_cost="40.00")
    customer_a = make_customer("Customer A")
    customer_b = make_customer("Customer B")

    assert_costing_invariant(db, product.id)
    order_a = order_for(customer_a, product, 20)
    assert_costing_invariant(db, product.id)
    order_for(customer_b, product, 6)
    assert_costing_invariant(db, product.id)
    inventory_service.receive_stock(db, product.id, 4, purchase_unit_cost="45.00")
    assert_costing_invariant(db, product.id)
    inventory_service.receive_stock(db, product.id, 30, purchase_unit_cost="52.50")
    assert_costing_invariant(db, product.id)

    # 49 units in, nothing out yet: reserving never touches the cost layers.
    assert stock_state(db, product.id)["physical"] == D(49)
    assert cost_state(db, product.id)["layer_quantity"] == D(49)

    resync(db)
    deliver_all(db, order_service.get_order(db, order_a.id))
    assert_costing_invariant(db, product.id)
    assert stock_state(db, product.id)["physical"] == D(29)


def test_a_rejected_receipt_leaves_no_cost_records(db, make_product, make_customer, order_for):
    """A receipt that breaks a rule must not open a cost layer either."""
    from app.errors import AllocationError

    product = make_product("Widget", opening_stock=0)
    customer = make_customer("Customer A")
    order = order_for(customer, product, 5)

    layers_before = db.execute(select(func.count()).select_from(StockCostLayer)).scalar_one()

    with pytest.raises(AllocationError):
        inventory_service.receive_stock(
            db,
            product.id,
            10,
            purchase_unit_cost="40.00",
            # Under-allocates: 2 of the 5 that are owed.
            allocations=[{"order_item_id": order.items[0].id, "quantity": 2}],
        )

    resync(db)
    assert db.execute(select(func.count()).select_from(StockCostLayer)).scalar_one() == layers_before
    assert db.execute(select(func.count()).select_from(StockLayerConsumption)).scalar_one() == 0
    assert cost_state(db, product.id)["stock_value"] == M(0)
    assert_costing_invariant(db, product.id)


def test_negative_purchase_price_is_rejected(db, make_product):
    product = make_product("Widget", opening_stock=0)
    with pytest.raises(ValidationError):
        inventory_service.receive_stock(db, product.id, 10, purchase_unit_cost="-1")


def test_sales_report_rolls_up_trading_figures(db, make_product, make_customer, order_for):
    product = make_product("Widget", opening_stock=10, opening_unit_cost="40.00", mrp="100.00")
    customer = make_customer("Customer A")
    order = order_for(customer, product, 15, discount_percent="20")
    deliver_all(db, order)

    report = order_service.sales_report(db)
    # 10 delivered at 80 against 40 of cost each; 5 still owed at 80.
    assert report["revenue_delivered"] == M(800)
    assert report["cost_of_goods_sold"] == M(400)
    assert report["gross_profit"] == M(400)
    assert report["margin_percent"] == M("50.00")
    assert report["discounts_given"] == M(300)
    assert report["outstanding_order_value"] == M(400)


def test_dashboard_reports_money(db, make_product, make_customer, order_for):
    product = make_product("Widget", opening_stock=10, opening_unit_cost="40.00", mrp="100.00")
    customer = make_customer("Customer A")
    order = order_for(customer, product, 4)
    deliver_all(db, order)
    inventory_service.receive_stock(db, product.id, 5, purchase_unit_cost="60.00")

    summary = inventory_service.inventory_summary(db)
    # 6 left from the opening batch at 40, plus 5 at 60.
    assert summary["total_stock_value"] == M(540)
    assert summary["purchase_spend"] == M(300)
    assert summary["revenue_delivered"] == M(400)
    assert summary["cost_of_goods_sold"] == M(160)
    assert summary["gross_profit"] == M(240)
    assert summary["recent_receipts"][0]["unit_cost"] == Decimal("60.0000")
    assert summary["recent_receipts"][0]["total_cost"] == M(300)
    assert summary["recent_orders"][0]["total_amount"] == M(400)
