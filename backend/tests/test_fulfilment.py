"""Reservation versus delivery, and the pending-commitments view.

Reserving stock promises it to a customer. Delivering it is what actually takes
it out of inventory and clears the obligation. These tests pin the difference.
"""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models import (
    CustomerDelivery,
    CustomerDeliveryItem,
    MovementType,
    OrderStatus,
    StockAllocation,
    StockMovement,
    StockReservation,
)
from app.services import deliveries as delivery_service
from app.services import inventory as inventory_service
from app.services import orders as order_service
from tests.conftest import (
    D,
    M,
    assert_costing_invariant,
    assert_reservations_match_lines,
    ledger_balance,
    resync,
    stock_state,
)


def deliver(db, order, item, quantity, **kwargs):
    return delivery_service.create_delivery(
        db, order.id, [{"order_item_id": item.id, "quantity": quantity}], **kwargs
    )


# ---------------------------------------------------------------------------
# Tests 16-17: reservation is not delivery
# ---------------------------------------------------------------------------

def test_16_reserved_stock_is_not_counted_as_delivered(
    db, make_product, make_customer, order_for
):
    product = make_product("Widget", opening_stock=0, opening_unit_cost="40.00")
    customer = make_customer("Customer A")
    order = order_for(customer, product, 20)

    inventory_service.receive_stock(db, product.id, 10, purchase_unit_cost="40.00")

    resync(db)
    item = order_service.get_order(db, order.id).items[0]
    assert item.quantity_reserved == D(10)
    assert item.quantity_fulfilled == D(0)
    # Still owed in full: the goods are here but the customer has not had them.
    assert item.quantity_pending == D(20)

    # The stock is still on the shelf and still in the cost layers.
    assert stock_state(db, product.id)["physical"] == D(10)
    assert ledger_balance(db, product.id) == D(10)
    assert db.execute(select(func.count()).select_from(StockAllocation)).scalar_one() == 0
    assert_costing_invariant(db, product.id)

    fulfilment = delivery_service.order_fulfilment(db, order.id)
    line = fulfilment["lines"][0]
    assert line["quantity_delivered"] == D(0)
    assert line["quantity_reserved"] == D(10)
    assert line["quantity_unallocated"] == D(10)
    assert line["quantity_deliverable"] == D(10)
    assert fulfilment["can_deliver"] is True


def test_17_reserved_stock_is_not_available_to_another_customer(
    db, make_product, make_customer, order_for
):
    product = make_product("Widget", opening_stock=10)
    first = make_customer("Customer A")
    second = make_customer("Customer B")

    order_for(first, product, 10)
    second_order = order_for(second, product, 10)

    assert stock_state(db, product.id)["available"] == D(0)
    assert second_order.items[0].quantity_reserved == D(0)

    # The second customer cannot be delivered stock that belongs to the first.
    with pytest.raises(ValidationError, match="only 0.000 is reserved"):
        deliver(db, second_order, second_order.items[0], 1)

    resync(db)
    assert stock_state(db, product.id)["physical"] == D(10)
    assert_reservations_match_lines(db, product.id)


# ---------------------------------------------------------------------------
# Tests 18-19: partial then full delivery
# ---------------------------------------------------------------------------

def test_18_and_19_partial_then_final_delivery(db, make_product, make_customer, order_for):
    """The brief's example: 20 ordered, 15 delivered, a receipt of 10, then 5 out."""
    product = make_product("Widget", opening_stock=15, opening_unit_cost="40.00", mrp="100.00")
    customer = make_customer("Customer A")
    order = order_for(customer, product, 20)

    # Deliver the 15 that are on hand.
    first = deliver(db, order, order.items[0], 15)
    assert first["delivery_number"].startswith("DN-")
    assert first["total_delivered"] == D(15)
    assert first["lines"][0]["quantity_delivered_total"] == D(15)
    assert first["lines"][0]["quantity_outstanding"] == D(5)
    assert first["order_status"] == OrderStatus.PARTIALLY_FULFILLED

    assert stock_state(db, product.id) == {
        "physical": D(0),
        "reserved": D(0),
        "available": D(0),
        "pending": D(5),
        "net": D(-5),
    }
    assert ledger_balance(db, product.id) == D(0)

    # A receipt of 10: five are owed, five are free.
    resync(db)
    inventory_service.receive_stock(db, product.id, 10, purchase_unit_cost="50.00")
    assert stock_state(db, product.id) == {
        "physical": D(10),
        "reserved": D(5),
        "available": D(5),
        "pending": D(5),
        "net": D(5),
    }

    # Delivering the reserved five clears the obligation.
    resync(db)
    reloaded = order_service.get_order(db, order.id)
    second = deliver(db, reloaded, reloaded.items[0], 5)

    assert second["lines"][0]["quantity_delivered_total"] == D(20)
    assert second["lines"][0]["quantity_outstanding"] == D(0)
    assert second["lines"][0]["quantity_reserved"] == D(0)
    assert second["order_status"] == OrderStatus.FULFILLED
    assert second["order_outstanding_after"] == D(0)

    # Five surplus units remain, free for anybody.
    assert stock_state(db, product.id) == {
        "physical": D(5),
        "reserved": D(0),
        "available": D(5),
        "pending": D(0),
        "net": D(5),
    }
    assert ledger_balance(db, product.id) == D(5)
    assert_costing_invariant(db, product.id)
    assert_reservations_match_lines(db, product.id)

    # Cost of goods followed the deliveries, not the receipts.
    financials = order_service.order_financials(db, order_service.get_order(db, order.id))
    assert financials["totals"]["cost_of_goods_sold"] == M(850)
    assert financials["totals"]["delivered_amount"] == M(2000)


def test_a_delivery_writes_one_stock_movement_out(db, make_product, make_customer, order_for):
    product = make_product("Widget", opening_stock=10)
    customer = make_customer("Customer A")
    order = order_for(customer, product, 10)

    deliver(db, order, order.items[0], 4)

    resync(db)
    movements = (
        db.execute(
            select(StockMovement)
            .where(StockMovement.product_id == product.id)
            .order_by(StockMovement.created_at)
        )
        .scalars()
        .all()
    )
    assert [movement.movement_type for movement in movements] == [
        MovementType.OPENING_STOCK,
        MovementType.CUSTOMER_DELIVERY,
    ]
    assert movements[1].quantity_change == D(-4)
    assert movements[1].reference_type == "customer_delivery_item"
    assert ledger_balance(db, product.id) == D(6)


# ---------------------------------------------------------------------------
# Tests 20-21: delivery limits
# ---------------------------------------------------------------------------

def test_20_a_delivery_cannot_exceed_what_is_eligible(db, make_product, make_customer, order_for):
    product = make_product("Widget", opening_stock=5)
    customer = make_customer("Customer A")
    order = order_for(customer, product, 20)

    # Only 5 are reserved, even though 20 are outstanding.
    with pytest.raises(ValidationError, match="only 5.000 is reserved"):
        deliver(db, order, order.items[0], 6)

    # And never more than is outstanding, however much is reserved.
    inventory_service.receive_stock(db, product.id, 30)
    resync(db)
    reloaded = order_service.get_order(db, order.id)
    with pytest.raises(ValidationError, match="only 20.000 is still outstanding"):
        deliver(db, reloaded, reloaded.items[0], 21)

    resync(db)
    assert stock_state(db, product.id)["physical"] == D(35)
    assert db.execute(select(func.count()).select_from(CustomerDelivery)).scalar_one() == 0


def test_21_the_same_reserved_quantity_cannot_be_delivered_twice(
    db, make_product, make_customer, order_for
):
    product = make_product("Widget", opening_stock=10)
    customer = make_customer("Customer A")
    order = order_for(customer, product, 10)

    deliver(db, order, order.items[0], 10)

    resync(db)
    reloaded = order_service.get_order(db, order.id)
    assert reloaded.items[0].quantity_reserved == D(0)
    assert reloaded.items[0].quantity_fulfilled == D(10)

    with pytest.raises(ValidationError, match="still outstanding"):
        deliver(db, reloaded, reloaded.items[0], 1)

    resync(db)
    assert stock_state(db, product.id)["physical"] == D(0)
    assert ledger_balance(db, product.id) == D(0)
    # One reservation, fully released; no second draw on it.
    reservation = db.execute(select(StockReservation)).scalars().one()
    assert reservation.quantity == D(10)
    assert reservation.quantity_released == D(10)
    assert reservation.quantity_open == D(0)


def test_a_repeated_delivery_submission_does_not_duplicate(
    db, make_product, make_customer, order_for
):
    product = make_product("Widget", opening_stock=10)
    customer = make_customer("Customer A")
    order = order_for(customer, product, 10)

    first = deliver(db, order, order.items[0], 4, idempotency_key="double-click")
    second = deliver(db, order, order.items[0], 4, idempotency_key="double-click")

    assert second["delivery_id"] == str(first["delivery_id"])
    resync(db)
    assert db.execute(select(func.count()).select_from(CustomerDelivery)).scalar_one() == 1
    assert db.execute(select(func.count()).select_from(CustomerDeliveryItem)).scalar_one() == 1
    assert stock_state(db, product.id)["physical"] == D(6)


def test_a_cancelled_order_cannot_be_delivered(db, make_product, make_customer, order_for):
    product = make_product("Widget", opening_stock=10)
    customer = make_customer("Customer A")
    order = order_for(customer, product, 10)
    order_service.cancel_order(db, order.id)

    resync(db)
    reloaded = order_service.get_order(db, order.id)
    with pytest.raises(ConflictError, match="cancelled"):
        deliver(db, reloaded, reloaded.items[0], 1)


def test_delivery_validation_failures(db, make_product, make_customer, order_for):
    product = make_product("Widget", opening_stock=10)
    customer = make_customer("Customer A")
    order = order_for(customer, product, 10)

    with pytest.raises(NotFoundError, match="not part of order"):
        delivery_service.create_delivery(
            db, order.id, [{"order_item_id": uuid.uuid4(), "quantity": 1}]
        )
    with pytest.raises(ValidationError, match="more than once"):
        delivery_service.create_delivery(
            db,
            order.id,
            [
                {"order_item_id": order.items[0].id, "quantity": 1},
                {"order_item_id": order.items[0].id, "quantity": 1},
            ],
        )
    with pytest.raises(ValidationError, match="at least one quantity"):
        delivery_service.create_delivery(
            db, order.id, [{"order_item_id": order.items[0].id, "quantity": 0}]
        )

    resync(db)
    assert db.execute(select(func.count()).select_from(CustomerDelivery)).scalar_one() == 0


# ---------------------------------------------------------------------------
# Test 23: rollback
# ---------------------------------------------------------------------------

def test_23_a_failed_delivery_rolls_everything_back(db, make_product, make_customer, make_order):
    """One good line and one over-quantity line: neither goes out."""
    first = make_product("Product A", opening_stock=10, sku="P-A")
    second = make_product("Product B", opening_stock=10, sku="P-B")
    customer = make_customer("Customer A")
    order = make_order(
        customer,
        [
            {"product_id": first.id, "quantity_ordered": 10},
            {"product_id": second.id, "quantity_ordered": 10},
        ],
    )
    movements_before = db.execute(select(func.count()).select_from(StockMovement)).scalar_one()

    with pytest.raises(ValidationError, match="still outstanding"):
        delivery_service.create_delivery(
            db,
            order.id,
            [
                {"order_item_id": order.items[0].id, "quantity": 5},
                {"order_item_id": order.items[1].id, "quantity": 50},
            ],
        )

    resync(db)
    assert db.execute(select(func.count()).select_from(CustomerDelivery)).scalar_one() == 0
    assert db.execute(select(func.count()).select_from(StockAllocation)).scalar_one() == 0
    assert (
        db.execute(select(func.count()).select_from(StockMovement)).scalar_one()
        == movements_before
    )
    assert stock_state(db, first.id)["physical"] == D(10)
    assert stock_state(db, first.id)["reserved"] == D(10)
    assert stock_state(db, second.id)["physical"] == D(10)

    reloaded = order_service.get_order(db, order.id)
    assert all(item.quantity_fulfilled == D(0) for item in reloaded.items)
    assert_reservations_match_lines(db, first.id)

    # The session still works and a valid delivery goes through.
    result = delivery_service.create_delivery(
        db, order.id, [{"order_item_id": reloaded.items[0].id, "quantity": 5}]
    )
    assert result["total_delivered"] == D(5)


# ---------------------------------------------------------------------------
# Test 24: concurrency
# ---------------------------------------------------------------------------

def test_24_concurrent_deliveries_cannot_ship_the_same_stock_twice(
    db, session_factory, make_product, make_customer, order_for
):
    product = make_product("Widget", opening_stock=10)
    customer = make_customer("Customer A")
    order = order_for(customer, product, 10)
    item_id = order.items[0].id

    def ship(_index):
        session = session_factory()
        try:
            return True, delivery_service.create_delivery(
                session, order.id, [{"order_item_id": item_id, "quantity": 10}]
            )
        except Exception as exc:  # noqa: BLE001 - the outcome is the assertion
            return False, exc
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(ship, range(4)))

    successes = [payload for ok, payload in results if ok]
    assert len(successes) == 1, [str(payload) for ok, payload in results if not ok]

    resync(db)
    reloaded = order_service.get_order(db, order.id)
    assert reloaded.items[0].quantity_fulfilled == D(10)
    assert reloaded.items[0].quantity_reserved == D(0)
    assert stock_state(db, product.id)["physical"] == D(0)
    assert ledger_balance(db, product.id) == D(0)
    assert_costing_invariant(db, product.id)


def test_24b_concurrent_receipts_and_deliveries_stay_consistent(
    db, session_factory, make_product, make_customer, order_for
):
    product = make_product("Widget", opening_stock=0)
    customers = [make_customer("Customer {}".format(index)) for index in range(4)]
    for customer in customers:
        order_for(customer, product, 5)

    def receive(_index):
        session = session_factory()
        try:
            return True, inventory_service.receive_stock(session, product.id, 5)
        except Exception as exc:  # noqa: BLE001
            return False, exc
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(receive, range(4)))
    assert all(ok for ok, _ in results), [str(p) for ok, p in results if not ok]

    resync(db)
    # 20 units in, 20 units of demand: everything is spoken for, nothing twice.
    assert stock_state(db, product.id) == {
        "physical": D(20),
        "reserved": D(20),
        "available": D(0),
        "pending": D(20),
        "net": D(0),
    }
    assert_reservations_match_lines(db, product.id)


# ---------------------------------------------------------------------------
# Test 25: the ledger explains every change
# ---------------------------------------------------------------------------

def test_25_the_movement_ledger_matches_physical_stock(
    db, make_supplier, make_product, make_purchase_order, make_customer, order_for
):
    from app.services import purchasing as purchasing_service
    from tests.conftest import po_line, receipt_line

    product = make_product("Widget", opening_stock=5, opening_unit_cost="40.00")
    customer = make_customer("Customer A")
    order = order_for(customer, product, 12)
    supplier = make_supplier("Northgate Mills")
    po = make_purchase_order(supplier, [po_line(product, 20, "42.00")])

    purchasing_service.create_goods_receipt(db, po.id, [receipt_line(po.items[0], 20)])
    resync(db)
    reloaded = order_service.get_order(db, order.id)
    deliver(db, reloaded, reloaded.items[0], 12)

    resync(db)
    movements = (
        db.execute(
            select(StockMovement)
            .where(StockMovement.product_id == product.id)
            .order_by(StockMovement.created_at)
        )
        .scalars()
        .all()
    )
    assert [movement.movement_type for movement in movements] == [
        MovementType.OPENING_STOCK,
        MovementType.GOODS_RECEIPT,
        MovementType.CUSTOMER_DELIVERY,
    ]
    # 5 in, 20 in, 12 out.
    assert ledger_balance(db, product.id) == D(13)
    assert stock_state(db, product.id)["physical"] == D(13)
    assert_costing_invariant(db, product.id)
    # Every movement names the transaction that caused it.
    assert all(movement.reference_id is not None for movement in movements)


# ---------------------------------------------------------------------------
# Test 29: pending commitments
# ---------------------------------------------------------------------------

def test_29_pending_commitments_match_the_underlying_order_lines(
    db, make_product, make_customer, order_for
):
    product_a = make_product("Product A", opening_stock=8, mrp="100.00", sku="P-A")
    product_b = make_product("Product B", opening_stock=0, mrp="50.00", sku="P-B")
    first = make_customer("Northgate Traders")
    second = make_customer("Riverside Supplies")

    order_one = order_for(first, product_a, 10)
    order_for(second, product_a, 5)
    order_for(second, product_b, 4)

    # Deliver part of the first order so a partially delivered line appears.
    deliver(db, order_one, order_one.items[0], 3)

    resync(db)
    report = delivery_service.pending_commitments(db)

    assert report["totals"]["line_count"] == 3
    assert report["totals"]["customer_count"] == 2
    # 7 still owed on the first order, plus 5 and 4.
    assert report["totals"]["quantity_outstanding"] == D(16)
    assert report["totals"]["quantity_reserved"] == D(5)
    assert report["totals"]["quantity_unallocated"] == D(11)

    by_order = {row["order_number"]: row for row in report["rows"]}
    first_row = by_order[order_one.order_number]
    assert first_row["quantity_ordered"] == D(10)
    assert first_row["quantity_delivered"] == D(3)
    assert first_row["quantity_outstanding"] == D(7)
    assert first_row["quantity_reserved"] == D(5)
    assert first_row["quantity_unallocated"] == D(2)
    assert first_row["fulfilment_status"] == "PARTIALLY_DELIVERED"
    assert first_row["outstanding_value"] == M(700)

    # Oldest order first.
    assert report["rows"][0]["order_number"] == order_one.order_number

    summary = {row["customer_name"]: row for row in report["customers"]}
    assert summary["Northgate Traders"]["quantity_outstanding"] == D(7)
    assert summary["Riverside Supplies"]["quantity_outstanding"] == D(9)
    assert summary["Riverside Supplies"]["order_count"] == 2
    assert summary["Riverside Supplies"]["outstanding_value"] == M(700)

    # The roll-up agrees with the rows it was built from.
    assert sum(row["quantity_outstanding"] for row in report["customers"]) == D(16)


def test_pending_commitments_filters(db, make_product, make_customer, order_for):
    product_a = make_product("Product A", opening_stock=5, sku="P-A")
    product_b = make_product("Product B", opening_stock=0, sku="P-B")
    first = make_customer("Northgate Traders")
    second = make_customer("Riverside Supplies")

    order_for(first, product_a, 5)
    order_for(second, product_b, 4)

    assert len(delivery_service.pending_commitments(db)["rows"]) == 2
    assert len(delivery_service.pending_commitments(db, customer_id=first.id)["rows"]) == 1
    assert len(delivery_service.pending_commitments(db, product_id=product_b.id)["rows"]) == 1
    assert len(delivery_service.pending_commitments(db, search="riverside")["rows"]) == 1
    assert len(delivery_service.pending_commitments(db, search="P-A")["rows"]) == 1

    reserved_only = delivery_service.pending_commitments(db, only_reserved=True)["rows"]
    assert [row["product_sku"] for row in reserved_only] == ["P-A"]
    unallocated_only = delivery_service.pending_commitments(db, only_unallocated=True)["rows"]
    assert [row["product_sku"] for row in unallocated_only] == ["P-B"]

    # A cancelled order drops out entirely.
    order_service.cancel_order(
        db, delivery_service.pending_commitments(db, product_id=product_b.id)["rows"][0]["order_id"]
    )
    resync(db)
    assert len(delivery_service.pending_commitments(db)["rows"]) == 1


def test_delivery_history_is_listed_and_linked(db, make_product, make_customer, order_for):
    product = make_product("Widget", opening_stock=10)
    customer = make_customer("Customer A")
    order = order_for(customer, product, 10)

    created = deliver(db, order, order.items[0], 4, reference="Van 3")

    rows = delivery_service.list_deliveries(db)
    assert [row["delivery_number"] for row in rows] == [created["delivery_number"]]
    assert rows[0]["reference"] == "Van 3"
    assert rows[0]["total_quantity"] == D(4)
    assert rows[0]["order_number"] == order.order_number

    assert delivery_service.list_deliveries(db, customer_id=customer.id)
    assert delivery_service.list_deliveries(db, order_id=order.id)
    assert delivery_service.list_deliveries(db, search="van 3")

    fulfilment = delivery_service.order_fulfilment(db, order.id)
    assert len(fulfilment["deliveries"]) == 1
    assert fulfilment["deliveries"][0]["delivery_number"] == created["delivery_number"]
    assert fulfilment["lines"][0]["reservations"][0]["quantity_released"] == D(4)
