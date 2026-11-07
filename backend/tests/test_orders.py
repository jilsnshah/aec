"""Sales order creation, priority ordering, status derivation and cancellation."""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models import CancellationKind, OrderCancellation, OrderStatus, StockMovement
from app.services import inventory as inventory_service
from app.services import orders as order_service
from tests.conftest import (
    D,
    assert_reservations_match_lines,
    ledger_balance,
    resync,
    state,
    stock_state,
)


def test_multi_product_order_fulfils_each_line_independently(db, make_product, make_customer, make_order):
    plentiful = make_product("Plentiful", opening_stock=100, sku="SKU-PLENTY")
    scarce = make_product("Scarce", opening_stock=2, sku="SKU-SCARCE")
    none_left = make_product("Empty", opening_stock=0, sku="SKU-EMPTY")
    customer = make_customer("Customer A")

    order = make_order(
        customer,
        [
            {"product_id": plentiful.id, "quantity_ordered": 10},
            {"product_id": scarce.id, "quantity_ordered": 5},
            {"product_id": none_left.id, "quantity_ordered": 3},
        ],
    )

    by_product = {item.product_id: item for item in order.items}
    # Stock on hand is reserved, not delivered.
    assert by_product[plentiful.id].quantity_reserved == D(10)
    assert by_product[plentiful.id].quantity_unallocated == D(0)
    assert by_product[scarce.id].quantity_reserved == D(2)
    assert by_product[scarce.id].quantity_unallocated == D(3)
    assert by_product[none_left.id].quantity_reserved == D(0)
    assert by_product[none_left.id].quantity_unallocated == D(3)
    assert all(item.quantity_fulfilled == D(0) for item in order.items)
    assert order.status == OrderStatus.PENDING

    assert state(db, scarce.id)["net"] == D(-3)
    assert state(db, none_left.id)["net"] == D(-3)
    for product in (plentiful, scarce, none_left):
        assert_reservations_match_lines(db, product.id)


def test_order_number_is_generated_and_unique(db, make_product, make_customer, order_for):
    product = make_product("Widget", opening_stock=100)
    customer = make_customer("Customer A")
    numbers = {order_for(customer, product, 1).order_number for _ in range(5)}
    assert len(numbers) == 5
    assert all(number.startswith("SO-") for number in numbers)


def test_older_orders_keep_priority_over_a_new_one(db, make_product, make_customer, order_for):
    """A later order cannot eat stock that an older order is already owed."""
    product = make_product("Widget", opening_stock=5)
    first = make_customer("First")
    second = make_customer("Second")

    order_one = order_for(first, product, 8)
    assert order_one.items[0].quantity_reserved == D(5)
    assert order_one.items[0].quantity_unallocated == D(3)

    # Nothing is free, so the second order gets no stock reserved at all.
    order_two = order_for(second, product, 4)
    assert order_two.items[0].quantity_reserved == D(0)
    assert order_two.items[0].quantity_unallocated == D(4)
    assert order_two.status == OrderStatus.PENDING

    assert stock_state(db, product.id) == {
        "physical": D(5),
        "reserved": D(5),
        "available": D(0),
        "pending": D(12),
        "net": D(-7),
    }


def test_a_fully_stocked_order_is_reserved_in_full(db, make_product, make_customer, order_for):
    product = make_product("Widget", opening_stock=50)
    customer = make_customer("Customer A")
    order = order_for(customer, product, 20)
    # Covered by stock, but still owed until it is delivered.
    assert order.items[0].quantity_reserved == D(20)
    assert order.items[0].quantity_unallocated == D(0)
    assert order.status == OrderStatus.PENDING
    assert stock_state(db, product.id) == {
        "physical": D(50),
        "reserved": D(20),
        "available": D(30),
        "pending": D(20),
        "net": D(30),
    }


def test_order_validation_failures(db, make_product, make_customer):
    import uuid

    product = make_product("Widget", opening_stock=5)
    customer = make_customer("Customer A")

    with pytest.raises(ValidationError, match="at least one product line"):
        order_service.create_order(db, customer.id, [])

    with pytest.raises(ValidationError, match="greater than zero"):
        order_service.create_order(
            db, customer.id, [{"product_id": product.id, "quantity_ordered": 0}]
        )
    with pytest.raises(ValidationError, match="greater than zero"):
        order_service.create_order(
            db, customer.id, [{"product_id": product.id, "quantity_ordered": -3}]
        )

    with pytest.raises(NotFoundError, match="Customer"):
        order_service.create_order(
            db, uuid.uuid4(), [{"product_id": product.id, "quantity_ordered": 1}]
        )
    with pytest.raises(NotFoundError, match="Product"):
        order_service.create_order(
            db, customer.id, [{"product_id": uuid.uuid4(), "quantity_ordered": 1}]
        )

    # A rejected order leaves no trace at all.
    assert db.execute(select(func.count()).select_from(StockMovement)).scalar_one() == 1
    assert stock_state(db, product.id) == {
        "physical": D(5),
        "reserved": D(0),
        "available": D(5),
        "pending": D(0),
        "net": D(5),
    }


def test_archived_product_or_customer_cannot_be_ordered(db, make_product, make_customer):
    from app.services import customers as customer_service
    from app.services import products as product_service

    product = make_product("Widget", opening_stock=5)
    customer = make_customer("Customer A")

    product_service.archive_product(db, product.id)
    with pytest.raises(ValidationError, match="archived"):
        order_service.create_order(
            db, customer.id, [{"product_id": product.id, "quantity_ordered": 1}]
        )

    product_service.update_product(db, product.id, {"is_active": True})
    customer_service.archive_customer(db, customer.id)
    with pytest.raises(ValidationError, match="archived"):
        order_service.create_order(
            db, customer.id, [{"product_id": product.id, "quantity_ordered": 1}]
        )


# ---------------------------------------------------------------------------
# Test 8: cancellation
# ---------------------------------------------------------------------------

def test_8a_cancelling_an_unfulfilled_order(db, make_product, make_customer, order_for):
    product = make_product("Widget", opening_stock=0)
    customer = make_customer("Customer A")
    order = order_for(customer, product, 6)
    assert state(db, product.id)["pending"] == D(6)

    cancelled = order_service.cancel_order(db, order.id, reason="Customer changed their mind")

    assert cancelled.status == OrderStatus.CANCELLED
    assert cancelled.cancelled_at is not None
    assert cancelled.items[0].quantity_cancelled == D(6)
    assert cancelled.items[0].quantity_pending == D(0)
    # The obligation is gone, so it no longer drags the net position negative.
    assert state(db, product.id) == {"physical": D(0), "pending": D(0), "net": D(0)}

    audit = db.execute(select(OrderCancellation)).scalars().all()
    assert len(audit) == 1
    assert audit[0].kind == CancellationKind.FULL
    assert audit[0].reason == "Customer changed their mind"


def test_8b_cancelling_the_remainder_keeps_what_was_delivered(
    db, make_product, make_customer, order_for
):
    from app.services import deliveries as delivery_service

    product = make_product("Widget", opening_stock=15)
    customer = make_customer("Customer A")
    order = order_for(customer, product, 20)

    # Deliver the 15 that were reserved, leaving 5 outstanding.
    delivery_service.create_delivery(
        db, order.id, [{"order_item_id": order.items[0].id, "quantity": 15}]
    )
    resync(db)
    ledger_before = ledger_balance(db, product.id)

    with pytest.raises(ConflictError, match="already fulfilled"):
        order_service.cancel_order(db, order.id)

    updated = order_service.cancel_remaining(db, order.id, reason="Short-closed")

    assert updated.items[0].quantity_fulfilled == D(15)
    assert updated.items[0].quantity_cancelled == D(5)
    assert updated.items[0].quantity_pending == D(0)
    assert updated.status == OrderStatus.PARTIALLY_FULFILLED
    # Cancelling moves no stock: the 15 already handed over stay handed over.
    assert ledger_balance(db, product.id) == ledger_before == D(0)
    assert stock_state(db, product.id) == {
        "physical": D(0),
        "reserved": D(0),
        "available": D(0),
        "pending": D(0),
        "net": D(0),
    }

    audit = db.execute(select(OrderCancellation)).scalars().all()
    assert [row.kind for row in audit] == [CancellationKind.REMAINING]


def test_cancelled_orders_drop_out_of_settlement(db, make_product, make_customer, order_for):
    product = make_product("Widget", opening_stock=0)
    customer_a = make_customer("Customer A")
    customer_b = make_customer("Customer B")
    order_a = order_for(customer_a, product, 5)
    order_for(customer_b, product, 4)

    order_service.cancel_order(db, order_a.id)

    result = inventory_service.receive_stock(db, product.id, 10)
    assert result["required_allocation"] == D(4)
    assert [row["customer_name"] for row in result["allocations"]] == ["Customer B"]
    assert stock_state(db, product.id) == {
        "physical": D(10),
        "reserved": D(4),
        "available": D(6),
        "pending": D(4),
        "net": D(6),
    }


def test_double_cancellation_is_rejected(db, make_product, make_customer, order_for):
    product = make_product("Widget", opening_stock=0)
    customer = make_customer("Customer A")
    order = order_for(customer, product, 5)
    order_service.cancel_order(db, order.id)

    with pytest.raises(ConflictError, match="already cancelled"):
        order_service.cancel_order(db, order.id)
    with pytest.raises(ConflictError, match="already cancelled"):
        order_service.cancel_remaining(db, order.id)


def test_cancel_remaining_with_nothing_outstanding_is_rejected(
    db, make_product, make_customer, order_for
):
    from app.services import deliveries as delivery_service

    product = make_product("Widget", opening_stock=10)
    customer = make_customer("Customer A")
    order = order_for(customer, product, 10)
    delivery_service.create_delivery(
        db, order.id, [{"order_item_id": order.items[0].id, "quantity": 10}]
    )
    with pytest.raises(ConflictError, match="no outstanding quantity"):
        order_service.cancel_remaining(db, order.id)


def test_cancelling_an_order_hands_its_reserved_stock_back(
    db, make_product, make_customer, order_for
):
    product = make_product("Widget", opening_stock=10)
    first = make_customer("Customer A")
    second = make_customer("Customer B")

    held = order_for(first, product, 10)
    waiting = order_for(second, product, 6)
    assert stock_state(db, product.id)["available"] == D(0)
    assert waiting.items[0].quantity_unallocated == D(6)

    order_service.cancel_order(db, held.id)

    # The 10 units are free again. They are not re-reserved automatically; the
    # next receipt or order picks them up.
    assert stock_state(db, product.id) == {
        "physical": D(10),
        "reserved": D(0),
        "available": D(10),
        "pending": D(6),
        "net": D(4),
    }
    assert_reservations_match_lines(db, product.id)


def test_order_allocations_explain_every_delivered_unit(db, make_product, make_customer, order_for):
    from app.models import AllocationSource
    from app.services import deliveries as delivery_service

    product = make_product("Widget", opening_stock=15)
    customer = make_customer("Customer A")
    order = order_for(customer, product, 20)
    inventory_service.receive_stock(db, product.id, 5)

    # Nothing has been delivered, so there is no cost trail yet.
    assert order_service.order_allocations(db, order.id) == []

    resync(db)
    delivery_service.create_delivery(
        db, order.id, [{"order_item_id": order.items[0].id, "quantity": 20}]
    )

    allocations = order_service.order_allocations(db, order.id)
    assert [(row["source"], row["quantity"]) for row in allocations] == [
        (AllocationSource.ORDER_CREATION, D(15)),
        (AllocationSource.STOCK_RECEIPT, D(5)),
    ]
    assert allocations[0]["stock_receipt_id"] is None
    assert allocations[1]["stock_receipt_id"] is not None
