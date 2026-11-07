"""The compulsory allocation rules -- the heart of the system.

Since Phase 3, allocating stock to an order **reserves** it rather than
delivering it: the units stay on the shelf, out of everybody else's reach,
until somebody actually hands them over. So a receipt raises physical stock and
reserved stock together, and only a delivery brings physical stock back down.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.errors import AllocationError, ValidationError
from app.models import (
    AllocationSource,
    MovementType,
    OrderStatus,
    StockAllocation,
    StockMovement,
    StockReceipt,
    StockReservation,
)
from app.services import inventory as inventory_service
from app.services import orders as order_service
from app.services import reservations as reservation_service
from tests.conftest import (
    D,
    assert_reservations_match_lines,
    ledger_balance,
    resync,
    stock_state,
)


def test_1_stock_on_hand_is_reserved_not_delivered(db, make_product, make_customer, order_for):
    """15 in stock, 20 ordered: 15 reserved, 5 unallocated, nothing delivered."""
    product = make_product("Widget A", opening_stock=15)
    customer = make_customer("Customer A")

    order = order_for(customer, product, 20)
    item = order.items[0]

    assert item.quantity_ordered == D(20)
    # The goods have not left the building, so nothing is delivered yet.
    assert item.quantity_fulfilled == D(0)
    assert item.quantity_reserved == D(15)
    assert item.quantity_pending == D(20)
    assert item.quantity_unallocated == D(5)
    assert order.status == OrderStatus.PENDING

    assert stock_state(db, product.id) == {
        "physical": D(15),
        "reserved": D(15),
        "available": D(0),
        "pending": D(20),
        "net": D(-5),
    }
    # Reserving moves no stock, so the ledger is untouched.
    assert ledger_balance(db, product.id) == D(15)
    assert_reservations_match_lines(db, product.id)


def test_2_a_receipt_settles_what_is_still_unallocated(db, make_product, make_customer, order_for):
    """Receiving 10 reserves the 5 that had no stock behind them."""
    product = make_product("Widget A", opening_stock=15)
    customer = make_customer("Customer A")
    order = order_for(customer, product, 20)

    result = inventory_service.receive_stock(db, product.id, 10)

    assert result["receipt_quantity"] == D(10)
    assert result["unallocated_before"] == D(5)
    assert result["required_allocation"] == D(5)
    assert result["allocated_total"] == D(5)
    assert result["surplus_quantity"] == D(5)
    assert len(result["allocations"]) == 1
    assert result["allocations"][0]["customer_name"] == "Customer A"
    assert result["allocations"][0]["quantity_allocated"] == D(5)
    assert result["physical_stock_after"] == D(25)
    assert result["reserved_stock_after"] == D(20)
    assert result["available_stock_after"] == D(5)
    assert result["unallocated_after"] == D(0)

    assert stock_state(db, product.id) == {
        "physical": D(25),
        "reserved": D(20),
        "available": D(5),
        "pending": D(20),
        "net": D(5),
    }
    assert ledger_balance(db, product.id) == D(25)
    assert_reservations_match_lines(db, product.id)

    refreshed = order_service.get_order(db, order.id)
    assert refreshed.items[0].quantity_reserved == D(20)
    assert refreshed.items[0].quantity_unallocated == D(0)
    # Still owed in full: reserved is not delivered.
    assert refreshed.items[0].quantity_pending == D(20)
    assert refreshed.status == OrderStatus.PENDING


def test_3_fifo_across_three_customers(db, make_product, make_customer, order_for):
    """Unallocated 5, 4 and 6; receive 10; FIFO gives 5, 4, 1."""
    product = make_product("Widget A", opening_stock=0)
    customer_a = make_customer("Customer A")
    customer_b = make_customer("Customer B")
    customer_c = make_customer("Customer C")

    order_a = order_for(customer_a, product, 5)
    order_b = order_for(customer_b, product, 4)
    order_c = order_for(customer_c, product, 6)

    preview = inventory_service.pending_orders_for_product(db, product.id, 10)
    assert [row["customer_name"] for row in preview["items"]] == [
        "Customer A",
        "Customer B",
        "Customer C",
    ]
    assert [row["proposed_allocation"] for row in preview["items"]] == [D(5), D(4), D(1)]
    assert preview["required_allocation"] == D(10)
    assert preview["surplus_quantity"] == D(0)

    result = inventory_service.receive_stock(db, product.id, 10)
    allocated = {row["customer_name"]: row["quantity_allocated"] for row in result["allocations"]}
    assert allocated == {"Customer A": D(5), "Customer B": D(4), "Customer C": D(1)}

    resync(db)
    assert order_service.get_order(db, order_a.id).items[0].quantity_unallocated == D(0)
    assert order_service.get_order(db, order_b.id).items[0].quantity_unallocated == D(0)
    item_c = order_service.get_order(db, order_c.id).items[0]
    assert item_c.quantity_reserved == D(1)
    assert item_c.quantity_unallocated == D(5)

    # Nothing is left free while a customer is still waiting.
    assert stock_state(db, product.id) == {
        "physical": D(10),
        "reserved": D(10),
        "available": D(0),
        "pending": D(15),
        "net": D(-5),
    }
    assert_reservations_match_lines(db, product.id)


def test_4a_custom_allocation_is_accepted_when_valid(db, make_product, make_customer, order_for):
    product = make_product("Widget A", opening_stock=0)
    customer_a = make_customer("Customer A")
    customer_b = make_customer("Customer B")
    customer_c = make_customer("Customer C")
    order_a = order_for(customer_a, product, 5)
    order_b = order_for(customer_b, product, 4)
    order_c = order_for(customer_c, product, 6)

    # The operator overrides FIFO: skip A entirely, serve C in full.
    allocations = [
        {"order_item_id": order_b.items[0].id, "quantity": 4},
        {"order_item_id": order_c.items[0].id, "quantity": 6},
    ]
    result = inventory_service.receive_stock(db, product.id, 10, allocations=allocations)

    allocated = {row["customer_name"]: row["quantity_allocated"] for row in result["allocations"]}
    assert allocated == {"Customer B": D(4), "Customer C": D(6)}
    assert result["allocated_total"] == D(10)

    resync(db)
    assert order_service.get_order(db, order_a.id).items[0].quantity_reserved == D(0)
    assert order_service.get_order(db, order_b.id).items[0].quantity_reserved == D(4)
    assert order_service.get_order(db, order_c.id).items[0].quantity_reserved == D(6)
    assert stock_state(db, product.id)["available"] == D(0)
    assert_reservations_match_lines(db, product.id)


@pytest.mark.parametrize("short_or_long", ["short", "long"])
def test_4b_allocation_sum_must_equal_required(
    db, make_product, make_customer, order_for, short_or_long
):
    """An allocation that does not total min(receipt, demand) changes nothing."""
    product = make_product("Widget A", opening_stock=0)
    customer_a = make_customer("Customer A")
    customer_b = make_customer("Customer B")
    order_a = order_for(customer_a, product, 5)
    order_b = order_for(customer_b, product, 6)

    quantities, expected = {
        # Under-allocating would leave new stock free while orders are waiting.
        "short": ((3, 2), "exactly 10.000"),
        # Over-allocating would hand out stock that was never received.
        "long": ((5, 6), "exceeds the"),
    }[short_or_long]
    allocations = [
        {"order_item_id": order_a.items[0].id, "quantity": quantities[0]},
        {"order_item_id": order_b.items[0].id, "quantity": quantities[1]},
    ]

    with pytest.raises(AllocationError) as excinfo:
        inventory_service.receive_stock(db, product.id, 10, allocations=allocations)
    assert expected in str(excinfo.value)

    assert stock_state(db, product.id) == {
        "physical": D(0),
        "reserved": D(0),
        "available": D(0),
        "pending": D(11),
        "net": D(-11),
    }
    assert db.execute(select(func.count()).select_from(StockReceipt)).scalar_one() == 0
    assert db.execute(select(func.count()).select_from(StockReservation)).scalar_one() == 0


def test_4c_a_line_cannot_take_more_than_it_is_owed(db, make_product, make_customer, order_for):
    product = make_product("Widget A", opening_stock=0)
    customer_a = make_customer("Customer A")
    order_a = order_for(customer_a, product, 5)

    with pytest.raises(AllocationError, match="at most 5.000"):
        inventory_service.receive_stock(
            db,
            product.id,
            10,
            allocations=[{"order_item_id": order_a.items[0].id, "quantity": 7}],
        )
    assert stock_state(db, product.id)["pending"] == D(5)


def test_4d_duplicate_and_unknown_lines_are_rejected(db, make_product, make_customer, order_for):
    import uuid

    product = make_product("Widget A", opening_stock=0)
    customer_a = make_customer("Customer A")
    order_a = order_for(customer_a, product, 5)
    item_id = order_a.items[0].id

    with pytest.raises(AllocationError, match="more than once"):
        inventory_service.receive_stock(
            db,
            product.id,
            10,
            allocations=[
                {"order_item_id": item_id, "quantity": 3},
                {"order_item_id": item_id, "quantity": 2},
            ],
        )

    with pytest.raises(AllocationError, match="not awaiting stock"):
        inventory_service.receive_stock(
            db, product.id, 10, allocations=[{"order_item_id": uuid.uuid4(), "quantity": 5}]
        )

    with pytest.raises(AllocationError, match="cannot be negative"):
        inventory_service.receive_stock(
            db, product.id, 10, allocations=[{"order_item_id": item_id, "quantity": -1}]
        )


def test_5_receipt_larger_than_demand_leaves_a_surplus(db, make_product, make_customer, order_for):
    """5 unallocated, 20 received: 5 reserved, 15 genuinely free."""
    product = make_product("Widget A", opening_stock=0)
    customer = make_customer("Customer A")
    order_for(customer, product, 5)

    result = inventory_service.receive_stock(db, product.id, 20)

    assert result["required_allocation"] == D(5)
    assert result["allocated_total"] == D(5)
    assert result["surplus_quantity"] == D(15)
    assert result["physical_stock_after"] == D(20)
    assert result["available_stock_after"] == D(15)

    assert stock_state(db, product.id) == {
        "physical": D(20),
        "reserved": D(5),
        "available": D(15),
        "pending": D(5),
        "net": D(15),
    }
    assert ledger_balance(db, product.id) == D(20)
    assert_reservations_match_lines(db, product.id)


def test_receipt_with_no_waiting_orders_is_all_free_stock(db, make_product):
    product = make_product("Widget A", opening_stock=0)
    result = inventory_service.receive_stock(db, product.id, 7)
    assert result["required_allocation"] == D(0)
    assert result["allocations"] == []
    assert stock_state(db, product.id)["available"] == D(7)


def test_the_same_demand_cannot_be_reserved_twice(db, make_product, make_customer, order_for):
    product = make_product("Widget A", opening_stock=0)
    customer = make_customer("Customer A")
    order = order_for(customer, product, 5)
    item_id = order.items[0].id

    inventory_service.receive_stock(db, product.id, 5)
    resync(db)
    assert order_service.get_order(db, order.id).items[0].quantity_unallocated == D(0)

    # The line is fully covered, so it is no longer eligible for allocation.
    with pytest.raises(AllocationError, match="not awaiting stock"):
        inventory_service.receive_stock(
            db, product.id, 5, allocations=[{"order_item_id": item_id, "quantity": 5}]
        )

    resync(db)
    assert order_service.get_order(db, order.id).items[0].quantity_reserved == D(5)
    assert_reservations_match_lines(db, product.id)


def test_reserved_stock_is_not_offered_to_another_customer(
    db, make_product, make_customer, order_for
):
    """Test 17: once reserved, those units are gone from available stock."""
    product = make_product("Widget A", opening_stock=10)
    first = make_customer("Customer A")
    second = make_customer("Customer B")

    order_for(first, product, 10)
    assert stock_state(db, product.id)["available"] == D(0)

    # The second customer orders the same product: there is nothing free to
    # give them, even though 10 units are physically on the shelf.
    later = order_for(second, product, 10)
    assert later.items[0].quantity_reserved == D(0)
    assert later.items[0].quantity_unallocated == D(10)

    assert stock_state(db, product.id) == {
        "physical": D(10),
        "reserved": D(10),
        "available": D(0),
        "pending": D(20),
        "net": D(-10),
    }
    assert_reservations_match_lines(db, product.id)


def test_fractional_quantities_allocate_exactly(db, make_product, make_customer, order_for):
    product = make_product("Loose grain", opening_stock=0, unit_of_measure="kg")
    customer_a = make_customer("Customer A")
    customer_b = make_customer("Customer B")
    order_for(customer_a, product, "2.750")
    order_for(customer_b, product, "1.500")

    result = inventory_service.receive_stock(db, product.id, "3.000")
    assert result["allocated_total"] == D("3.000")
    assert [row["quantity_allocated"] for row in result["allocations"]] == [
        D("2.750"),
        D("0.250"),
    ]
    assert stock_state(db, product.id)["available"] == D(0)
    assert stock_state(db, product.id)["pending"] == D("4.250")


def test_audit_trail_explains_which_orders_the_stock_was_held_for(
    db, make_product, make_customer, order_for
):
    product = make_product("Widget A", opening_stock=0)
    customer_a = make_customer("Customer A")
    customer_b = make_customer("Customer B")
    order_a = order_for(customer_a, product, 5)
    order_for(customer_b, product, 4)

    inventory_service.receive_stock(db, product.id, 10, note="Lorry 42")

    resync(db)
    rows = reservation_service.reservation_rows(db, order_a.items[0].id)
    assert [row["quantity"] for row in rows] == [D(5)]
    assert rows[0]["source"] == AllocationSource.STOCK_RECEIPT
    assert rows[0]["stock_receipt_id"] is not None

    movements = (
        db.execute(
            select(StockMovement)
            .where(StockMovement.product_id == product.id)
            .order_by(StockMovement.created_at)
        )
        .scalars()
        .all()
    )
    # One movement only: the goods arriving. Reserving moves nothing.
    assert [movement.movement_type for movement in movements] == [MovementType.STOCK_RECEIPT]
    assert ledger_balance(db, product.id) == D(10)
    # No cost of goods yet either: nothing has been sold.
    assert db.execute(select(func.count()).select_from(StockAllocation)).scalar_one() == 0


def test_opening_stock_is_recorded_as_a_movement(db, make_product):
    product = make_product("Widget A", opening_stock=12)
    movements = (
        db.execute(select(StockMovement).where(StockMovement.product_id == product.id))
        .scalars()
        .all()
    )
    assert len(movements) == 1
    assert movements[0].movement_type == MovementType.OPENING_STOCK
    assert movements[0].quantity_change == D(12)
    assert ledger_balance(db, product.id) == D(12) == product.physical_stock


def test_receipt_quantity_must_be_positive(db, make_product):
    product = make_product("Widget A")
    with pytest.raises(ValidationError, match="greater than zero"):
        inventory_service.receive_stock(db, product.id, 0)
    with pytest.raises(ValidationError, match="greater than zero"):
        inventory_service.receive_stock(db, product.id, -5)


def test_idempotency_key_prevents_duplicate_receipts(db, make_product, make_customer, order_for):
    product = make_product("Widget A", opening_stock=0)
    customer = make_customer("Customer A")
    order_for(customer, product, 5)

    first = inventory_service.receive_stock(db, product.id, 10, idempotency_key="submit-1")
    second = inventory_service.receive_stock(db, product.id, 10, idempotency_key="submit-1")

    assert second["receipt_id"] == str(first["receipt_id"])
    assert db.execute(select(func.count()).select_from(StockReceipt)).scalar_one() == 1
    assert stock_state(db, product.id) == {
        "physical": D(10),
        "reserved": D(5),
        "available": D(5),
        "pending": D(5),
        "net": D(5),
    }
    assert_reservations_match_lines(db, product.id)
