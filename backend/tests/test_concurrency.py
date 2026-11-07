"""Test 9: concurrent operations must not fulfil the same quantity twice."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any, Callable, List, Tuple

from sqlalchemy import func, select

from app.models import SalesOrderItem, StockReceipt, StockReservation
from app.services import customers as customer_service
from app.services import inventory as inventory_service
from app.services import orders as order_service
from app.services import products as product_service
from tests.conftest import (
    D,
    assert_reservations_match_lines,
    ledger_balance,
    resync,
    state,
    stock_state,
)


def _run_concurrently(session_factory, work: Callable[[Any], Any], times: int) -> List[Tuple[bool, Any]]:
    """Run ``work`` in parallel threads, each with its own session."""

    def task(_index: int):
        session = session_factory()
        try:
            return True, work(session)
        except Exception as exc:  # noqa: BLE001 - the outcome is the assertion
            return False, exc
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=times) as pool:
        return list(pool.map(task, range(times)))


def test_9a_concurrent_receipts_never_reserve_the_same_demand_twice(db, session_factory):
    product = product_service.create_product(db, sku="C-1", name="Widget", opening_stock=0)
    customer = customer_service.create_customer(db, name="Customer A")
    order = order_service.create_order(
        db, customer.id, [{"product_id": product.id, "quantity_ordered": 5}]
    )
    item_id = order.items[0].id

    results = _run_concurrently(
        session_factory, lambda session: inventory_service.receive_stock(session, product.id, 5), 4
    )
    successes = [payload for ok, payload in results if ok]
    assert len(successes) == 4, [str(payload) for ok, payload in results if not ok]

    resync(db)
    reserved = db.execute(
        select(SalesOrderItem.quantity_reserved).where(SalesOrderItem.id == item_id)
    ).scalar_one()
    # Exactly the 5 that were owed, no matter how the receipts interleaved.
    assert Decimal(str(reserved)) == D(5)
    assert_reservations_match_lines(db, product.id)

    total_allocated = sum(payload["allocated_total"] for payload in successes)
    assert total_allocated == D(5)

    # 4 receipts of 5 = 20 in, nothing out: 5 held for the customer, 15 free.
    assert stock_state(db, product.id) == {
        "physical": D(20),
        "reserved": D(5),
        "available": D(15),
        "pending": D(5),
        "net": D(15),
    }
    assert ledger_balance(db, product.id) == D(20)
    assert db.execute(select(func.count()).select_from(StockReceipt)).scalar_one() == 4


def test_9b_concurrent_orders_never_reserve_the_same_stock_twice(db, session_factory):
    product = product_service.create_product(db, sku="C-2", name="Widget", opening_stock=15)
    customers = [
        customer_service.create_customer(db, name="Customer {}".format(index)) for index in range(4)
    ]
    ids = [customer.id for customer in customers]
    counter = {"n": 0}

    def place(session):
        index = counter["n"]
        counter["n"] += 1
        return order_service.create_order(
            session, ids[index % len(ids)], [{"product_id": product.id, "quantity_ordered": 10}]
        )

    results = _run_concurrently(session_factory, place, 4)
    assert all(ok for ok, _ in results), [str(payload) for ok, payload in results if not ok]

    resync(db)
    total_reserved = Decimal(
        str(
            db.execute(
                select(func.coalesce(func.sum(SalesOrderItem.quantity_reserved), 0))
            ).scalar_one()
        )
    )
    total_ordered = Decimal(
        str(
            db.execute(
                select(func.coalesce(func.sum(SalesOrderItem.quantity_ordered), 0))
            ).scalar_one()
        )
    )

    # The 15 units that exist were promised once and once only.
    assert total_reserved == D(15)
    assert total_ordered == D(40)
    assert stock_state(db, product.id) == {
        "physical": D(15),
        "reserved": D(15),
        "available": D(0),
        "pending": D(40),
        "net": D(-25),
    }
    assert ledger_balance(db, product.id) == D(15)
    assert_reservations_match_lines(db, product.id)


def test_9c_duplicate_submission_under_concurrency_creates_one_receipt(db, session_factory):
    product = product_service.create_product(db, sku="C-3", name="Widget", opening_stock=0)
    customer = customer_service.create_customer(db, name="Customer A")
    order_service.create_order(
        db, customer.id, [{"product_id": product.id, "quantity_ordered": 5}]
    )

    results = _run_concurrently(
        session_factory,
        lambda session: inventory_service.receive_stock(
            session, product.id, 10, idempotency_key="double-click"
        ),
        4,
    )
    successes = [payload for ok, payload in results if ok]
    failures = [payload for ok, payload in results if not ok]

    resync(db)
    # Whether a racing attempt is replayed or rejected, only one receipt lands.
    assert db.execute(select(func.count()).select_from(StockReceipt)).scalar_one() == 1
    assert successes, [str(payload) for payload in failures]

    assert stock_state(db, product.id) == {
        "physical": D(10),
        "reserved": D(5),
        "available": D(5),
        "pending": D(5),
        "net": D(5),
    }
    # One receipt of 10 in, nothing out.
    assert ledger_balance(db, product.id) == D(10)
