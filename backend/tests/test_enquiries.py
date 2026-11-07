"""Customer enquiries: pricing, editing, and conversion into a sales order."""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models import (
    CustomerEnquiry,
    CustomerEnquiryItem,
    EnquiryStatus,
    OrderStatus,
    SalesOrder,
    StockAllocation,
    StockMovement,
)
from app.services import enquiries as enquiry_service
from app.services import orders as order_service
from app.services import pricing
from tests.conftest import (
    D,
    M,
    assert_costing_invariant,
    deliver_all,
    resync,
    state,
    stock_state,
)


@pytest.fixture()
def enquiry_for(db):
    def _make(customer, lines, notes=None):
        return enquiry_service.create_enquiry(db, customer.id, lines, notes)

    return _make


def line(product, quantity, discount=0):
    return {"product_id": product.id, "quantity": quantity, "discount_percent": discount}


# ---------------------------------------------------------------------------
# Tests 1-2: creation
# ---------------------------------------------------------------------------

def test_1_create_enquiry_with_one_product(db, make_product, make_customer, enquiry_for):
    product = make_product("Widget", opening_stock=50, mrp="1000.00")
    customer = make_customer("ABC Traders")

    enquiry = enquiry_for(customer, [line(product, 10)])

    assert enquiry.enquiry_number.startswith("ENQ-")
    assert enquiry.status == EnquiryStatus.OPEN
    assert enquiry.customer_id == customer.id
    assert len(enquiry.items) == 1

    item = enquiry.items[0]
    assert item.product_id == product.id
    assert item.quantity == D(10)
    assert item.mrp_snapshot == Decimal("1000.0000")
    # A new line starts at full price.
    assert item.discount_percent == M(0)
    assert item.quoted_unit_price == Decimal("1000.0000")
    assert item.line_total == M(10000)
    assert enquiry_service.enquiry_total(enquiry) == M(10000)


def test_2_create_enquiry_with_several_products_and_notes(
    db, make_product, make_customer, enquiry_for
):
    """The worked example from the brief: 10 @ 1000 less 15%, 20 @ 500 less 10%."""
    product_a = make_product("Product A", opening_stock=100, mrp="1000.00", sku="P-A")
    product_b = make_product("Product B", opening_stock=100, mrp="500.00", sku="P-B")
    customer = make_customer("ABC Traders")

    enquiry = enquiry_for(
        customer,
        [line(product_a, 10, "15"), line(product_b, 20, "10")],
        notes="Customer requires delivery in two batches. Call before dispatch.",
    )

    by_product = {item.product_id: item for item in enquiry.items}
    assert by_product[product_a.id].quoted_unit_price == Decimal("850.0000")
    assert by_product[product_a.id].line_total == M(8500)
    assert by_product[product_b.id].quoted_unit_price == Decimal("450.0000")
    assert by_product[product_b.id].line_total == M(9000)

    assert enquiry_service.enquiry_total(enquiry) == M(17500)
    assert "two batches" in enquiry.notes

    view = enquiry_service.to_view(enquiry)
    assert view["mrp_total"] == M(20000)
    assert view["discount_total"] == M(2500)
    assert view["total_amount"] == M(17500)
    assert view["item_count"] == 2


def test_adding_a_product_twice_consolidates_the_quantity(
    db, make_product, make_customer, enquiry_for
):
    product = make_product("Widget", opening_stock=50, mrp="100.00")
    customer = make_customer("ABC Traders")

    enquiry = enquiry_for(customer, [line(product, 10), line(product, 5, "20")])

    assert len(enquiry.items) == 1
    assert enquiry.items[0].quantity == D(15)
    assert enquiry.items[0].discount_percent == M(20)
    assert enquiry.items[0].line_total == M(1200)


# ---------------------------------------------------------------------------
# Test 3: the MRP comes from the product master
# ---------------------------------------------------------------------------

def test_3_mrp_is_read_from_the_product_master_not_the_client(
    db, make_product, make_customer
):
    product = make_product("Widget", opening_stock=10, mrp="1000.00")
    customer = make_customer("ABC Traders")

    # Whatever price fields a caller invents are ignored: only product_id,
    # quantity and discount_percent are read.
    enquiry = enquiry_service.create_enquiry(
        db,
        customer.id,
        [
            {
                "product_id": product.id,
                "quantity": 2,
                "discount_percent": 0,
                "mrp_snapshot": "1",
                "quoted_unit_price": "1",
                "line_total": "2",
            }
        ],
    )
    item = enquiry.items[0]
    assert item.mrp_snapshot == Decimal("1000.0000")
    assert item.quoted_unit_price == Decimal("1000.0000")
    assert item.line_total == M(2000)


def test_a_later_mrp_change_does_not_move_an_agreed_price(
    db, make_product, make_customer, enquiry_for
):
    from app.services import products as product_service

    product = make_product("Widget", opening_stock=10, mrp="1000.00")
    customer = make_customer("ABC Traders")
    enquiry = enquiry_for(customer, [line(product, 2, "10")])

    product_service.update_product(db, product.id, {"mrp": "2500.00"})

    refreshed = enquiry_service.get_enquiry(db, enquiry.id)
    assert refreshed.items[0].mrp_snapshot == Decimal("1000.0000")
    assert refreshed.items[0].quoted_unit_price == Decimal("900.0000")

    # And the deal that gets converted is the one that was agreed.
    result = enquiry_service.convert_enquiry(db, enquiry.id)
    order_item = result["order"].items[0]
    assert order_item.mrp_snapshot == Decimal("1000.0000")
    assert order_item.unit_price_net == Decimal("900.0000")


# ---------------------------------------------------------------------------
# Test 4: discount values
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "discount,expected_price,expected_total",
    [
        ("0", "1000.0000", "2000.00"),
        ("12.5", "875.0000", "1750.00"),
        ("100", "0.0000", "0.00"),
    ],
)
def test_4_discount_values(
    db, make_product, make_customer, enquiry_for, discount, expected_price, expected_total
):
    product = make_product("Widget", opening_stock=10, mrp="1000.00")
    customer = make_customer("ABC Traders")

    enquiry = enquiry_for(customer, [line(product, 2, discount)])
    item = enquiry.items[0]

    assert item.quoted_unit_price == Decimal(expected_price)
    assert item.line_total == M(expected_total)
    assert item.quoted_unit_price >= 0


def test_free_lines_can_be_forbidden_by_configuration(db, make_product, make_customer):
    from app.config import get_settings

    settings = get_settings()
    product = make_product("Widget", opening_stock=10, mrp="1000.00")
    customer = make_customer("ABC Traders")

    settings.allow_zero_price_lines = False
    try:
        with pytest.raises(ValidationError, match="would be free"):
            enquiry_service.create_enquiry(db, customer.id, [line(product, 1, "100")])
    finally:
        settings.allow_zero_price_lines = True

    # Nothing was written.
    resync(db)
    assert db.execute(select(func.count()).select_from(CustomerEnquiry)).scalar_one() == 0


# ---------------------------------------------------------------------------
# Test 5: rejections
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_discount", ["-1", "100.01", "250"])
def test_5_discounts_outside_the_range_are_rejected(
    db, make_product, make_customer, bad_discount
):
    product = make_product("Widget", opening_stock=10)
    customer = make_customer("ABC Traders")
    with pytest.raises(ValidationError, match="between 0 and 100"):
        enquiry_service.create_enquiry(db, customer.id, [line(product, 1, bad_discount)])


@pytest.mark.parametrize("bad_quantity", [0, "-5"])
def test_5_non_positive_quantities_are_rejected(
    db, make_product, make_customer, bad_quantity
):
    product = make_product("Widget", opening_stock=10)
    customer = make_customer("ABC Traders")
    with pytest.raises(ValidationError, match="greater than zero"):
        enquiry_service.create_enquiry(db, customer.id, [line(product, bad_quantity)])


def test_5_unknown_customer_or_product_is_rejected(db, make_product, make_customer):
    product = make_product("Widget", opening_stock=10)
    customer = make_customer("ABC Traders")

    with pytest.raises(NotFoundError, match="Customer"):
        enquiry_service.create_enquiry(db, uuid.uuid4(), [line(product, 1)])
    with pytest.raises(NotFoundError, match="Product"):
        enquiry_service.create_enquiry(
            db, customer.id, [{"product_id": uuid.uuid4(), "quantity": 1}]
        )
    with pytest.raises(ValidationError, match="at least one product"):
        enquiry_service.create_enquiry(db, customer.id, [])

    resync(db)
    assert db.execute(select(func.count()).select_from(CustomerEnquiry)).scalar_one() == 0


def test_5_archived_customer_or_product_is_rejected(db, make_product, make_customer):
    from app.services import customers as customer_service
    from app.services import products as product_service

    product = make_product("Widget", opening_stock=10)
    customer = make_customer("ABC Traders")

    product_service.archive_product(db, product.id)
    with pytest.raises(ValidationError, match="archived"):
        enquiry_service.create_enquiry(db, customer.id, [line(product, 1)])

    product_service.update_product(db, product.id, {"is_active": True})
    customer_service.archive_customer(db, customer.id)
    with pytest.raises(ValidationError, match="archived"):
        enquiry_service.create_enquiry(db, customer.id, [line(product, 1)])


# ---------------------------------------------------------------------------
# Tests 6-7: pricing is stored and totalled by the backend
# ---------------------------------------------------------------------------

def test_6_and_7_pricing_is_calculated_and_stored_per_line(
    db, make_product, make_customer, enquiry_for
):
    product_a = make_product("Odd price", opening_stock=100, mrp="1999.00", sku="P-A")
    product_b = make_product("Round price", opening_stock=100, mrp="250.00", sku="P-B")
    customer = make_customer("ABC Traders")

    enquiry = enquiry_for(customer, [line(product_a, 3, "12.5"), line(product_b, 7, "5")])
    by_product = {item.product_id: item for item in enquiry.items}

    # 1999 less 12.5% = 1749.125, kept at four decimals per unit.
    assert by_product[product_a.id].quoted_unit_price == Decimal("1749.1250")
    assert by_product[product_a.id].line_total == M("5247.38")
    assert by_product[product_b.id].quoted_unit_price == Decimal("237.5000")
    assert by_product[product_b.id].line_total == M("1662.50")

    assert enquiry_service.enquiry_total(enquiry) == M("6909.88")
    # Every line keeps the MRP it was negotiated against.
    assert by_product[product_a.id].mrp_snapshot == Decimal("1999.0000")
    assert by_product[product_b.id].mrp_snapshot == Decimal("250.0000")


# ---------------------------------------------------------------------------
# Test 8: editing an open enquiry
# ---------------------------------------------------------------------------

def test_8_editing_an_open_enquiry_updates_values_and_totals(
    db, make_product, make_customer, enquiry_for
):
    product_a = make_product("Product A", opening_stock=100, mrp="1000.00", sku="P-A")
    product_b = make_product("Product B", opening_stock=100, mrp="500.00", sku="P-B")
    product_c = make_product("Product C", opening_stock=100, mrp="200.00", sku="P-C")
    customer = make_customer("ABC Traders")

    enquiry = enquiry_for(customer, [line(product_a, 10), line(product_b, 20)])
    assert enquiry_service.enquiry_total(enquiry) == M(20000)

    updated = enquiry_service.update_enquiry(
        db,
        enquiry.id,
        {
            "notes": "Revised after a call",
            "items": [
                line(product_a, 10, "15"),
                line(product_c, 5, "0"),
            ],
        },
    )

    by_product = {item.product_id: item for item in updated.items}
    assert set(by_product) == {product_a.id, product_c.id}
    assert by_product[product_a.id].line_total == M(8500)
    assert by_product[product_c.id].line_total == M(1000)
    assert enquiry_service.enquiry_total(updated) == M(9500)
    assert updated.notes == "Revised after a call"

    # The removed line is gone, not merely detached.
    resync(db)
    assert db.execute(select(func.count()).select_from(CustomerEnquiryItem)).scalar_one() == 2


def test_notes_can_be_edited_without_touching_the_lines(
    db, make_product, make_customer, enquiry_for
):
    product = make_product("Widget", opening_stock=10, mrp="100.00")
    customer = make_customer("ABC Traders")
    enquiry = enquiry_for(customer, [line(product, 4, "10")])

    updated = enquiry_service.update_enquiry(db, enquiry.id, {"notes": "Ring before dispatch"})
    assert updated.notes == "Ring before dispatch"
    assert len(updated.items) == 1
    assert updated.items[0].line_total == M(360)


# ---------------------------------------------------------------------------
# Tests 9-11: conversion
# ---------------------------------------------------------------------------

def test_9_conversion_preserves_the_whole_deal(db, make_product, make_customer, enquiry_for):
    product_a = make_product("Product A", opening_stock=100, mrp="1000.00", sku="P-A")
    product_b = make_product("Product B", opening_stock=100, mrp="500.00", sku="P-B")
    customer = make_customer("ABC Traders")

    enquiry = enquiry_for(
        customer,
        [line(product_a, 10, "15"), line(product_b, 20, "10")],
        notes="Deliver in two batches.",
    )

    result = enquiry_service.convert_enquiry(db, enquiry.id)
    order = result["order"]
    converted = result["enquiry"]

    assert converted.status == EnquiryStatus.CONVERTED
    assert converted.sales_order_id == order.id
    assert converted.converted_at is not None
    assert order.enquiry_id == enquiry.id
    assert order.customer_id == customer.id
    assert enquiry.enquiry_number in order.notes
    # The enquiry keeps its own notes, and the order carries a copy.
    assert "two batches" in order.notes
    assert converted.notes == "Deliver in two batches."

    by_product = {item.product_id: item for item in order.items}
    assert by_product[product_a.id].quantity_ordered == D(10)
    assert by_product[product_a.id].mrp_snapshot == Decimal("1000.0000")
    assert by_product[product_a.id].discount_percent == M(15)
    assert by_product[product_a.id].unit_price_net == Decimal("850.0000")
    assert by_product[product_b.id].unit_price_net == Decimal("450.0000")

    assert order.subtotal_amount == M(20000)
    assert order.discount_amount == M(2500)
    assert order.total_amount == M(17500)
    assert order.total_amount == enquiry_service.enquiry_total(enquiry)


def test_10_conversion_runs_the_phase_1_inventory_logic(
    db, make_product, make_customer, enquiry_for
):
    product = make_product("Widget", opening_stock=15, opening_unit_cost="400.00", mrp="1000.00")
    customer = make_customer("ABC Traders")
    enquiry = enquiry_for(customer, [line(product, 20, "10")])

    result = enquiry_service.convert_enquiry(db, enquiry.id)
    order = result["order"]

    # Exactly the same behaviour as an order typed in directly: the 15 on hand
    # are reserved, 5 have no stock behind them, net position -5.
    assert order.items[0].quantity_reserved == D(15)
    assert order.items[0].quantity_unallocated == D(5)
    assert order.items[0].quantity_pending == D(20)
    assert order.status == OrderStatus.PENDING
    assert stock_state(db, product.id) == {
        "physical": D(15),
        "reserved": D(15),
        "available": D(0),
        "pending": D(20),
        "net": D(-5),
    }
    assert_costing_invariant(db, product.id)

    # Delivering the reserved units is what books the revenue and the cost.
    resync(db)
    deliver_all(db, order_service.get_order(db, order.id))
    resync(db)
    assert db.execute(select(func.count()).select_from(StockAllocation)).scalar_one() == 1
    financials = order_service.order_financials(db, order_service.get_order(db, order.id))
    assert financials["totals"]["delivered_amount"] == M(13500)
    assert financials["totals"]["cost_of_goods_sold"] == M(6000)
    assert financials["totals"]["gross_profit"] == M(7500)


def test_11_a_converted_order_settles_like_any_other(
    db, make_product, make_customer, enquiry_for
):
    """A later stock receipt settles the converted order by the same FIFO rules."""
    from app.services import inventory as inventory_service

    product = make_product("Widget", opening_stock=0, mrp="1000.00")
    customer = make_customer("ABC Traders")
    enquiry = enquiry_for(customer, [line(product, 20, "25")])
    result = enquiry_service.convert_enquiry(db, enquiry.id)
    order_id = result["order"].id

    assert stock_state(db, product.id) == {
        "physical": D(0),
        "reserved": D(0),
        "available": D(0),
        "pending": D(20),
        "net": D(-20),
    }

    receipt = inventory_service.receive_stock(db, product.id, 12, purchase_unit_cost="500.00")
    assert receipt["allocated_total"] == D(12)
    assert receipt["allocations"][0]["order_number"] == result["order"].order_number
    # The negotiated price, not the MRP, is what the revenue is recognised at.
    assert receipt["allocations"][0]["revenue"] == M(9000)

    resync(db)
    settled = order_service.get_order(db, order_id)
    assert settled.items[0].quantity_reserved == D(12)
    assert settled.items[0].quantity_unallocated == D(8)
    assert stock_state(db, product.id) == {
        "physical": D(12),
        "reserved": D(12),
        "available": D(0),
        "pending": D(20),
        "net": D(-8),
    }
    assert_costing_invariant(db, product.id)


def test_conversion_behaves_identically_to_a_direct_order(
    db, make_product, make_customer, enquiry_for, make_order
):
    """Same inputs, two routes, same inventory outcome."""
    via_enquiry = make_product("Via enquiry", opening_stock=15, mrp="100.00", sku="P-ENQ")
    direct = make_product("Direct", opening_stock=15, mrp="100.00", sku="P-DIR")
    customer = make_customer("ABC Traders")

    enquiry = enquiry_for(customer, [line(via_enquiry, 20, "10")])
    converted = enquiry_service.convert_enquiry(db, enquiry.id)["order"]
    typed = make_order(
        customer,
        [{"product_id": direct.id, "quantity_ordered": 20, "discount_percent": "10"}],
    )

    assert converted.items[0].quantity_reserved == typed.items[0].quantity_reserved
    assert converted.items[0].quantity_unallocated == typed.items[0].quantity_unallocated
    assert converted.items[0].quantity_pending == typed.items[0].quantity_pending
    assert converted.status == typed.status
    assert converted.total_amount == typed.total_amount
    assert state(db, via_enquiry.id) == state(db, direct.id)


# ---------------------------------------------------------------------------
# Test 12: rollback
# ---------------------------------------------------------------------------

def test_12_a_failed_conversion_rolls_everything_back(
    db, make_product, make_customer, enquiry_for
):
    """Archiving a product mid-negotiation makes conversion fail cleanly."""
    from app.services import products as product_service

    product = make_product("Widget", opening_stock=15, mrp="100.00")
    customer = make_customer("ABC Traders")
    enquiry = enquiry_for(customer, [line(product, 20, "10")])

    product_service.archive_product(db, product.id)

    orders_before = db.execute(select(func.count()).select_from(SalesOrder)).scalar_one()
    movements_before = db.execute(select(func.count()).select_from(StockMovement)).scalar_one()

    with pytest.raises(ValidationError, match="archived"):
        enquiry_service.convert_enquiry(db, enquiry.id)

    resync(db)
    assert db.execute(select(func.count()).select_from(SalesOrder)).scalar_one() == orders_before
    assert (
        db.execute(select(func.count()).select_from(StockMovement)).scalar_one()
        == movements_before
    )
    assert db.execute(select(func.count()).select_from(StockAllocation)).scalar_one() == 0

    # The enquiry is untouched and can still be converted once the product is back.
    reloaded = enquiry_service.get_enquiry(db, enquiry.id)
    assert reloaded.status == EnquiryStatus.OPEN
    assert reloaded.sales_order_id is None
    assert state(db, product.id) == {"physical": D(15), "pending": D(0), "net": D(15)}

    product_service.update_product(db, product.id, {"is_active": True})
    result = enquiry_service.convert_enquiry(db, enquiry.id)
    assert result["enquiry"].status == EnquiryStatus.CONVERTED


# ---------------------------------------------------------------------------
# Tests 13-14: converting twice, and editing a closed enquiry
# ---------------------------------------------------------------------------

def test_13_converting_twice_creates_only_one_order(
    db, make_product, make_customer, enquiry_for
):
    product = make_product("Widget", opening_stock=50, mrp="100.00")
    customer = make_customer("ABC Traders")
    enquiry = enquiry_for(customer, [line(product, 10)])

    first = enquiry_service.convert_enquiry(db, enquiry.id)

    with pytest.raises(ConflictError, match="already been converted") as excinfo:
        enquiry_service.convert_enquiry(db, enquiry.id)
    # The error points at the order that already exists.
    assert excinfo.value.details["sales_order_id"] == str(first["order"].id)

    resync(db)
    assert db.execute(select(func.count()).select_from(SalesOrder)).scalar_one() == 1
    assert stock_state(db, product.id)["reserved"] == D(10)
    assert stock_state(db, product.id)["available"] == D(40)


def test_13b_concurrent_conversions_create_only_one_order(
    db, session_factory, make_product, make_customer, enquiry_for
):
    product = make_product("Widget", opening_stock=50, mrp="100.00")
    customer = make_customer("ABC Traders")
    enquiry = enquiry_for(customer, [line(product, 10)])

    def convert(_index):
        session = session_factory()
        try:
            return True, enquiry_service.convert_enquiry(session, enquiry.id)
        except Exception as exc:  # noqa: BLE001 - the outcome is the assertion
            return False, exc
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(convert, range(4)))

    successes = [payload for ok, payload in results if ok]
    assert len(successes) == 1, [str(payload) for ok, payload in results if not ok]

    resync(db)
    assert db.execute(select(func.count()).select_from(SalesOrder)).scalar_one() == 1
    assert stock_state(db, product.id)["reserved"] == D(10)
    assert stock_state(db, product.id)["available"] == D(40)
    assert_costing_invariant(db, product.id)


def test_14_a_closed_enquiry_cannot_be_edited_or_reconverted(
    db, make_product, make_customer, enquiry_for
):
    product = make_product("Widget", opening_stock=50, mrp="100.00")
    customer = make_customer("ABC Traders")

    converted = enquiry_for(customer, [line(product, 5)])
    enquiry_service.convert_enquiry(db, converted.id)
    with pytest.raises(ConflictError, match="read-only"):
        enquiry_service.update_enquiry(db, converted.id, {"notes": "too late"})
    with pytest.raises(ConflictError):
        enquiry_service.mark_lost(db, converted.id)

    lost = enquiry_for(customer, [line(product, 5)])
    enquiry_service.mark_lost(db, lost.id, reason="Went elsewhere")
    with pytest.raises(ConflictError, match="read-only"):
        enquiry_service.update_enquiry(db, lost.id, {"notes": "too late"})
    with pytest.raises(ConflictError, match="read-only"):
        enquiry_service.convert_enquiry(db, lost.id)

    resync(db)
    assert enquiry_service.get_enquiry(db, converted.id).notes is None
    assert enquiry_service.get_enquiry(db, lost.id).status == EnquiryStatus.LOST


# ---------------------------------------------------------------------------
# Test 15: lost enquiries
# ---------------------------------------------------------------------------

def test_15_marking_an_enquiry_lost_creates_no_order_and_moves_no_stock(
    db, make_product, make_customer, enquiry_for
):
    product = make_product("Widget", opening_stock=15, mrp="100.00")
    customer = make_customer("ABC Traders")
    enquiry = enquiry_for(customer, [line(product, 20)])

    before = state(db, product.id)
    movements_before = db.execute(select(func.count()).select_from(StockMovement)).scalar_one()

    lost = enquiry_service.mark_lost(db, enquiry.id, reason="Lost on price")

    assert lost.status == EnquiryStatus.LOST
    assert lost.lost_reason == "Lost on price"
    assert lost.lost_at is not None
    assert lost.sales_order_id is None

    resync(db)
    assert db.execute(select(func.count()).select_from(SalesOrder)).scalar_one() == 0
    assert (
        db.execute(select(func.count()).select_from(StockMovement)).scalar_one()
        == movements_before
    )
    assert state(db, product.id) == before


# ---------------------------------------------------------------------------
# Test 17: identity is kept by id, not by name
# ---------------------------------------------------------------------------

def test_17_enquiries_and_orders_keep_their_customer_and_product_ids(
    db, make_product, make_customer, enquiry_for
):
    from app.services import customers as customer_service

    product = make_product("Widget", opening_stock=50, mrp="100.00")
    customer = make_customer("ABC Traders")
    enquiry = enquiry_for(customer, [line(product, 5)])
    order = enquiry_service.convert_enquiry(db, enquiry.id)["order"]

    # Renaming and archiving the customer changes no relationship.
    customer_service.update_customer(db, customer.id, {"name": "ABC Traders (Renamed)"})
    customer_service.archive_customer(db, customer.id)
    resync(db)

    reloaded = enquiry_service.get_enquiry(db, enquiry.id)
    assert reloaded.customer_id == customer.id
    assert reloaded.customer.name == "ABC Traders (Renamed)"
    assert reloaded.items[0].product_id == product.id

    reloaded_order = order_service.get_order(db, order.id)
    assert reloaded_order.customer_id == customer.id
    assert reloaded_order.enquiry_id == enquiry.id
    assert reloaded_order.items[0].product_id == product.id


# ---------------------------------------------------------------------------
# Listing and filtering
# ---------------------------------------------------------------------------

def test_listing_filters_by_status_customer_and_search(
    db, make_product, make_customer, enquiry_for
):
    product = make_product("Widget", opening_stock=100, mrp="100.00")
    first = make_customer("Northgate Traders")
    second = make_customer("Riverside Supplies")

    open_one = enquiry_for(first, [line(product, 1)])
    to_convert = enquiry_for(second, [line(product, 2)])
    to_lose = enquiry_for(second, [line(product, 3)])
    enquiry_service.convert_enquiry(db, to_convert.id)
    enquiry_service.mark_lost(db, to_lose.id)

    assert len(enquiry_service.list_enquiries(db)) == 3
    assert [e.id for e in enquiry_service.list_enquiries(db, status="OPEN")] == [open_one.id]
    assert [e.id for e in enquiry_service.list_enquiries(db, status="LOST")] == [to_lose.id]
    assert len(enquiry_service.list_enquiries(db, customer_id=second.id)) == 2
    assert [e.id for e in enquiry_service.list_enquiries(db, search="northgate")] == [open_one.id]
    assert [
        e.id for e in enquiry_service.list_enquiries(db, search=open_one.enquiry_number)
    ] == [open_one.id]

    with pytest.raises(ValidationError, match="not a valid enquiry status"):
        enquiry_service.list_enquiries(db, status="NONSENSE")


def test_enquiry_numbers_are_unique(db, make_product, make_customer, enquiry_for):
    product = make_product("Widget", opening_stock=100)
    customer = make_customer("ABC Traders")
    numbers = {enquiry_for(customer, [line(product, 1)]).enquiry_number for _ in range(5)}
    assert len(numbers) == 5


def test_pricing_service_matches_the_brief_worked_example():
    """A direct check of the arithmetic the brief specifies."""
    first = pricing.quote_line("1000.00", 10, "15")
    second = pricing.quote_line("500.00", 20, "10")
    assert first["quoted_unit_price"] == Decimal("850.0000")
    assert first["line_total"] == M(8500)
    assert second["quoted_unit_price"] == Decimal("450.0000")
    assert second["line_total"] == M(9000)
    assert pricing.sum_line_totals([first, second]) == M(17500)
