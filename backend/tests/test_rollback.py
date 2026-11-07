"""Test 7: an invalid stock receipt must leave no trace whatsoever."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.errors import AllocationError, NotFoundError, ValidationError
from app.models import (
    SalesOrderItem,
    StockAllocation,
    StockMovement,
    StockReceipt,
)
from app.services import inventory as inventory_service
from tests.conftest import D, ledger_balance, resync, state, stock_state


def _snapshot(db, product_id):
    return {
        "receipts": db.execute(select(func.count()).select_from(StockReceipt)).scalar_one(),
        "allocations": db.execute(select(func.count()).select_from(StockAllocation)).scalar_one(),
        "movements": db.execute(select(func.count()).select_from(StockMovement)).scalar_one(),
        "fulfilled": db.execute(
            select(func.coalesce(func.sum(SalesOrderItem.quantity_fulfilled), 0))
        ).scalar_one(),
        "reserved": db.execute(
            select(func.coalesce(func.sum(SalesOrderItem.quantity_reserved), 0))
        ).scalar_one(),
        "state": stock_state(db, product_id),
        "ledger": ledger_balance(db, product_id),
    }


@pytest.fixture()
def scenario(db, make_product, make_customer, order_for):
    """Two outstanding orders totalling 9 units, nothing in stock."""
    product = make_product("Widget", opening_stock=0)
    customer_a = make_customer("Customer A")
    customer_b = make_customer("Customer B")
    order_a = order_for(customer_a, product, 5)
    order_b = order_for(customer_b, product, 4)
    return product, order_a, order_b


def test_7_invalid_receipt_rolls_everything_back(db, scenario):
    product, order_a, order_b = scenario
    before = _snapshot(db, product.id)
    assert before["state"]["physical"] == D(0)
    assert before["state"]["pending"] == D(9)
    assert before["state"]["reserved"] == D(0)

    bad_allocations = [
        # Under-allocates: 6 of the 9 required.
        {"order_item_id": order_a.items[0].id, "quantity": 5},
        {"order_item_id": order_b.items[0].id, "quantity": 1},
    ]
    with pytest.raises(AllocationError):
        inventory_service.receive_stock(db, product.id, 9, allocations=bad_allocations)

    assert _snapshot(db, product.id) == before


def test_7b_rollback_for_every_class_of_invalid_receipt(db, scenario):
    product, order_a, _order_b = scenario
    before = _snapshot(db, product.id)

    failures = [
        # Non-existent product.
        (NotFoundError, dict(product_id=uuid.uuid4(), received_quantity=5)),
        # Non-positive receipt.
        (ValidationError, dict(product_id=product.id, received_quantity=0)),
        (ValidationError, dict(product_id=product.id, received_quantity=-3)),
        # A line asked for more than it is owed.
        (
            AllocationError,
            dict(
                product_id=product.id,
                received_quantity=10,
                allocations=[{"order_item_id": order_a.items[0].id, "quantity": 9}],
            ),
        ),
        # A line belonging to no outstanding order.
        (
            AllocationError,
            dict(
                product_id=product.id,
                received_quantity=5,
                allocations=[{"order_item_id": uuid.uuid4(), "quantity": 5}],
            ),
        ),
        # Allocation totalling more than was received.
        (
            AllocationError,
            dict(
                product_id=product.id,
                received_quantity=3,
                allocations=[{"order_item_id": order_a.items[0].id, "quantity": 5}],
            ),
        ),
    ]

    for expected_error, kwargs in failures:
        with pytest.raises(expected_error):
            inventory_service.receive_stock(db, **kwargs)
        assert _snapshot(db, product.id) == before, kwargs

    # The session is still usable, and a valid receipt still works afterwards.
    result = inventory_service.receive_stock(db, product.id, 9)
    assert result["allocated_total"] == D(9)
    # The nine arrived and are reserved to the waiting customers; they are
    # still owed until somebody delivers them.
    assert stock_state(db, product.id) == {
        "physical": D(9),
        "reserved": D(9),
        "available": D(0),
        "pending": D(9),
        "net": D(0),
    }


def test_7c_cached_stock_stays_consistent_with_the_ledger(db, scenario):
    product, _order_a, _order_b = scenario
    with pytest.raises(AllocationError):
        inventory_service.receive_stock(
            db, product.id, 9, allocations=[{"order_item_id": uuid.uuid4(), "quantity": 9}]
        )
    inventory_service.receive_stock(db, product.id, 20)

    db.expire_all()
    from app.services import products as product_service

    refreshed = product_service.get_product(db, product.id)
    # Twenty units arrived and none have left: reserving nine of them for
    # customers moves nothing, so the ledger and the cache both read 20.
    assert ledger_balance(db, product.id) == refreshed.physical_stock == D(20)
