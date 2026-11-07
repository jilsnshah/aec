"""Test fixtures.

The suite runs against PostgreSQL, the only database this application
supports. Each test gets its own schema in that database, created before it and
dropped after, so tests are isolated while still exercising the real thing --
including ``SELECT ... FOR UPDATE`` row locking, which the concurrency tests
depend on and which no other backend provides.

Point ``TEST_DATABASE_URL`` at a scratch database to keep test schemas out of
your development one; it falls back to ``DATABASE_URL``.
"""
from __future__ import annotations

import os
import uuid
from decimal import Decimal
from typing import Any, Dict, Iterator, List, Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.database import create_app_engine, get_db
from app.main import app
from app.models import Base, DocumentCounter
from app.services import customers as customer_service
from app.services import inventory as inventory_service
from app.services import orders as order_service
from app.services import products as product_service


def _test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", "").strip() or get_settings().database_url


COUNTER_SEEDS = [
    {"name": "sales_order", "last_value": 0},
    {"name": "stock_receipt", "last_value": 0},
    {"name": "customer_enquiry", "last_value": 0},
    {"name": "supplier", "last_value": 0},
    {"name": "purchase_order", "last_value": 0},
    {"name": "goods_receipt", "last_value": 0},
    {"name": "customer_delivery", "last_value": 0},
]


def _prepare(eng) -> None:
    Base.metadata.create_all(eng)
    with eng.begin() as connection:
        connection.execute(DocumentCounter.__table__.insert(), COUNTER_SEEDS)


@pytest.fixture(scope="session")
def admin_engine():
    """A connection to the test database, used only to make and drop schemas."""
    eng = create_app_engine(_test_database_url())
    yield eng
    eng.dispose()


@pytest.fixture()
def engine(admin_engine):
    schema = "t_{}".format(uuid.uuid4().hex[:16])
    with admin_engine.begin() as connection:
        connection.execute(text('CREATE SCHEMA "{}"'.format(schema)))

    eng = create_app_engine(_test_database_url(), schema=schema)
    try:
        _prepare(eng)
        yield eng
    finally:
        eng.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text('DROP SCHEMA IF EXISTS "{}" CASCADE'.format(schema)))


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@pytest.fixture()
def db(session_factory) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(session_factory) -> Iterator[TestClient]:
    def override_get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Convenience builders used by the business-rule tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def make_product(db):
    counter = {"n": 0}

    def _make(name: str = "Product", opening_stock: Any = 0, sku: Optional[str] = None, **kwargs):
        counter["n"] += 1
        return product_service.create_product(
            db,
            sku=sku or "SKU-{:03d}".format(counter["n"]),
            name=name,
            unit_of_measure=kwargs.pop("unit_of_measure", "pcs"),
            mrp=kwargs.pop("mrp", "100.00"),
            opening_stock=opening_stock,
            **kwargs
        )

    return _make


@pytest.fixture()
def make_customer(db):
    def _make(name: str = "Customer", **kwargs):
        return customer_service.create_customer(db, name=name, **kwargs)

    return _make


@pytest.fixture()
def make_supplier(db):
    counter = {"n": 0}

    def _make(name: str = "Supplier", **kwargs):
        counter["n"] += 1
        from app.services import suppliers as supplier_service

        return supplier_service.create_supplier(
            db, name="{} {}".format(name, counter["n"]) if name == "Supplier" else name, **kwargs
        )

    return _make


@pytest.fixture()
def make_purchase_order(db):
    def _make(supplier, lines, confirm: bool = True, **kwargs):
        from app.services import purchasing as purchasing_service

        return purchasing_service.create_purchase_order(
            db, supplier.id, lines, confirm=confirm, **kwargs
        )

    return _make


def po_line(product, quantity, unit_cost=0):
    return {
        "product_id": product.id,
        "quantity_ordered": quantity,
        "unit_cost": unit_cost,
    }


def receipt_line(po_item, quantity, **kwargs):
    entry = {"purchase_order_item_id": po_item.id, "quantity": quantity}
    entry.update(kwargs)
    return entry


@pytest.fixture()
def make_order(db):
    def _make(customer, lines: List[Dict[str, Any]], notes: Optional[str] = None):
        return order_service.create_order(db, customer.id, lines, notes)

    return _make


@pytest.fixture()
def order_for(db, make_order):
    """Shorthand: one customer orders one quantity of one product."""

    def _make(customer, product, qty: Any, unit_price: Any = None, discount_percent: Any = 0):
        return make_order(
            customer,
            [
                {
                    "product_id": product.id,
                    "quantity_ordered": qty,
                    "unit_price": unit_price,
                    "discount_percent": discount_percent,
                }
            ],
        )

    return _make


def D(value: Any) -> Decimal:
    """Quantity-scaled decimal, for readable assertions."""
    return Decimal(str(value)).quantize(Decimal("0.001"))


def M(value: Any) -> Decimal:
    """Money-scaled decimal, for readable assertions."""
    return Decimal(str(value)).quantize(Decimal("0.01"))


def cost_state(db: Session, product_id) -> Dict[str, Decimal]:
    """Stock valuation read back from the FIFO cost layers."""
    from app.services import costing

    resync(db)
    return costing.stock_valuation(db, product_id)


def assert_costing_invariant(db: Session, product_id) -> None:
    """The open cost layers must always account for exactly the physical stock."""
    from app.services import products as product_service

    resync(db)
    product = product_service.get_product(db, product_id)
    on_hand = cost_state(db, product_id)["layer_quantity"]
    assert on_hand == D(product.physical_stock), (
        "cost layers hold {} but physical stock is {}".format(on_hand, product.physical_stock)
    )


def resync(db: Session) -> None:
    """End this session's read transaction so it sees other sessions' commits.

    A session that still holds an open transaction keeps reading its original
    snapshot. API requests get a fresh session each time; long-lived test
    sessions have to ask for a new snapshot explicitly.
    """
    db.rollback()
    db.expire_all()


def state(db: Session, product_id) -> Dict[str, Decimal]:
    """The three stock figures for a product, read back from the database."""
    from app.services.common import pending_quantity_for_product

    resync(db)
    product = product_service.get_product(db, product_id)
    physical = Decimal(str(product.physical_stock))
    pending = pending_quantity_for_product(db, product_id)
    return {
        "physical": physical,
        "pending": pending,
        "net": physical - pending,
    }


def deliver_all(db: Session, order) -> Dict[str, Any]:
    """Deliver everything currently reserved on an order.

    Handy in tests about money: revenue and cost of goods are recognised when
    the goods go out, so a test about profit has to actually ship them.
    """
    from app.services import deliveries as delivery_service

    lines = [
        {"order_item_id": item.id, "quantity": item.quantity_reserved}
        for item in order.items
        if item.quantity_reserved > Decimal("0")
    ]
    return delivery_service.create_delivery(db, order.id, lines)


def stock_state(db: Session, product_id) -> Dict[str, Decimal]:
    """The full stock picture: physical, reserved, available, owed, net.

    * physical  -- units on the shelf
    * reserved  -- of those, units already promised to an order
    * available -- physical less reserved: what can still be sold
    * pending   -- what customers are owed but have not received
    * net       -- physical less pending; negative when short
    """
    from app.services import products as product_service
    from app.services import reservations
    from app.services.common import pending_quantity_for_product

    resync(db)
    product = product_service.get_product(db, product_id)
    physical = Decimal(str(product.physical_stock))
    reserved = reservations.reserved_for_product(db, product_id)
    pending = pending_quantity_for_product(db, product_id)
    return {
        "physical": physical,
        "reserved": reserved,
        "available": physical - reserved,
        "pending": pending,
        "net": physical - pending,
    }


def assert_reservations_match_lines(db: Session, product_id) -> None:
    """Reserved stock must equal what the order lines say is reserved, and
    must never exceed what is physically there."""
    from sqlalchemy import func, select

    from app.models import SalesOrderItem
    from app.services import products as product_service
    from app.services import reservations

    resync(db)
    on_lines = db.execute(
        select(func.coalesce(func.sum(SalesOrderItem.quantity_reserved), 0)).where(
            SalesOrderItem.product_id == product_id
        )
    ).scalar_one()
    held = reservations.reserved_for_product(db, product_id)
    assert D(on_lines) == held, "order lines claim {} reserved, reservations hold {}".format(
        on_lines, held
    )
    physical = Decimal(str(product_service.get_product(db, product_id).physical_stock))
    assert held <= physical, "reserved {} exceeds physical stock {}".format(held, physical)


def ledger_balance(db: Session, product_id) -> Decimal:
    from sqlalchemy import func, select

    resync(db)

    from app.models import StockMovement

    total = db.execute(
        select(func.coalesce(func.sum(StockMovement.quantity_change), 0)).where(
            StockMovement.product_id == product_id
        )
    ).scalar_one()
    return Decimal(str(total or 0))
