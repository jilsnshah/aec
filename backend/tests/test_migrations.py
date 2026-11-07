"""The migration chain itself: does it match the models, and does it keep data?

These run the real Alembic CLI in a subprocess against a throwaway PostgreSQL
database, because that is how migrations are actually applied.
"""
from __future__ import annotations

import os
import subprocess
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.database import create_app_engine
from app.models import Base
from tests.conftest import _test_database_url

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC = str(BACKEND_ROOT / ".venv" / "bin" / "alembic")
#: The last revision before customer enquiries existed.
PHASE_1_HEAD = "81d4d2b7778d"

pytestmark = pytest.mark.skipif(
    not Path(ALEMBIC).exists(), reason="alembic CLI not installed in .venv"
)


def _alembic(url: str, *args: str) -> None:
    environment = dict(os.environ, DATABASE_URL=url)
    environment.pop("TEST_DATABASE_URL", None)
    result = subprocess.run(
        [ALEMBIC, *args],
        cwd=str(BACKEND_ROOT),
        env=environment,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            "alembic {} failed:\n{}\n{}".format(" ".join(args), result.stdout, result.stderr)
        )


@pytest.fixture()
def scratch_url(admin_engine):
    """A brand-new, empty database for one test, dropped afterwards."""
    name = "aec_mig_{}".format(uuid.uuid4().hex[:12])
    base = _test_database_url()
    # CREATE DATABASE cannot run inside a transaction.
    with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text('CREATE DATABASE "{}"'.format(name)))
    try:
        yield base.rsplit("/", 1)[0] + "/" + name
    finally:
        with admin_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": name},
            )
            connection.execute(text('DROP DATABASE IF EXISTS "{}"'.format(name)))


def test_migrations_produce_exactly_the_model_schema(scratch_url):
    """A migrated database and the ORM models must not have drifted apart."""
    _alembic(scratch_url, "upgrade", "head")

    engine = create_app_engine(scratch_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            diff = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert diff == [], diff


def test_26_and_16_history_survives_the_later_migrations(scratch_url):
    """Data written before Phase 2 and Phase 3 existed must still read correctly."""
    _alembic(scratch_url, "upgrade", PHASE_1_HEAD)

    product_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    order_id = uuid.uuid4()
    item_id = uuid.uuid4()

    engine = create_app_engine(scratch_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO products (id, sku, name, unit_of_measure, mrp, physical_stock,"
                    " is_active, created_at, updated_at) VALUES (:id, 'LEGACY-1',"
                    " 'Legacy widget', 'pcs', 250.00, 40, true, now(), now())"
                ),
                {"id": product_id},
            )
            connection.execute(
                text(
                    "INSERT INTO customers (id, name, is_active, created_at, updated_at)"
                    " VALUES (:id, 'Legacy Customer', true, now(), now())"
                ),
                {"id": customer_id},
            )
            connection.execute(
                text(
                    "INSERT INTO sales_orders (id, order_number, customer_id, status,"
                    " created_at, updated_at, subtotal_amount, discount_amount, total_amount)"
                    " VALUES (:id, 'SO-2026-000999', :customer_id, 'PARTIALLY_FULFILLED',"
                    " now(), now(), 2500.00, 0, 2500.00)"
                ),
                {"id": order_id, "customer_id": customer_id},
            )
            connection.execute(
                text(
                    "INSERT INTO sales_order_items (id, order_id, product_id, line_number,"
                    " quantity_ordered, quantity_fulfilled, quantity_cancelled, unit_price,"
                    " discount_percent, unit_price_net) VALUES (:id, :order_id, :product_id, 1,"
                    " 10, 4, 0, 250.00, 0, 250.00)"
                ),
                {"id": item_id, "order_id": order_id, "product_id": product_id},
            )
    finally:
        engine.dispose()

    _alembic(scratch_url, "upgrade", "head")

    from app.services import orders as order_service

    engine = create_app_engine(scratch_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        order = order_service.get_order(session, order_id)
        assert order.order_number == "SO-2026-000999"
        assert order.customer_id == customer_id
        assert order.total_amount == Decimal("2500.00")
        # Columns added by the later phases, nullable or defaulted.
        assert order.enquiry_id is None

        item = order.items[0]
        assert item.quantity_ordered == Decimal("10.000")
        # Phase 1 allocated by delivering at once, so this really was delivered.
        assert item.quantity_fulfilled == Decimal("4.000")
        # And nothing was merely reserved, which is what the default encodes.
        assert item.quantity_reserved == Decimal("0.000")
        assert item.quantity_pending == Decimal("6.000")
        assert item.quantity_unallocated == Decimal("6.000")
        # Backfilled from the list price the order was sold at.
        assert item.mrp_snapshot == Decimal("250.0000")

        financials = order_service.order_financials(session, order)
        assert financials["totals"]["total_amount"] == Decimal("2500.00")
        assert financials["totals"]["delivered_amount"] == Decimal("1000.00")
    finally:
        session.close()
        engine.dispose()


#: The last revision before purchase orders settled waiting customers.
PHASE_3_HEAD = "3928d051146b"


def test_open_purchase_orders_settle_waiting_customers_on_upgrade(scratch_url):
    """A purchase placed before settlement existed covers who was waiting."""
    _alembic(scratch_url, "upgrade", PHASE_3_HEAD)

    ids = {key: uuid.uuid4() for key in ("product", "customer", "order", "item", "supplier", "po", "po_item")}
    engine = create_app_engine(scratch_url)
    try:
        with engine.begin() as connection:
            for statement in (
                "INSERT INTO products (id, sku, name, unit_of_measure, mrp, physical_stock,"
                " is_active, created_at, updated_at) VALUES (:product, 'OLD-PO', 'Old widget',"
                " 'pcs', 10, 0, true, now(), now())",
                "INSERT INTO customers (id, name, is_active, created_at, updated_at)"
                " VALUES (:customer, 'Waiting Customer', true, now(), now())",
                "INSERT INTO sales_orders (id, order_number, customer_id, status, created_at,"
                " updated_at, subtotal_amount, discount_amount, total_amount)"
                " VALUES (:order, 'SO-2026-000900', :customer, 'PENDING', now(), now(), 60, 0, 60)",
                "INSERT INTO sales_order_items (id, order_id, product_id, line_number,"
                " quantity_ordered, quantity_fulfilled, quantity_cancelled, quantity_reserved,"
                " unit_price, discount_percent, unit_price_net) VALUES (:item, :order, :product,"
                " 1, 6, 0, 0, 0, 10, 0, 10)",
                "INSERT INTO suppliers (id, code, name, is_active, created_at, updated_at)"
                " VALUES (:supplier, 'SUP-OLD', 'Old Supplier', true, now(), now())",
                "INSERT INTO purchase_orders (id, po_number, supplier_id, status, ordered_at,"
                " created_at, updated_at) VALUES (:po, 'PO-2026-000900', :supplier, 'ORDERED',"
                " now(), now(), now())",
                "INSERT INTO purchase_order_items (id, purchase_order_id, product_id, line_number,"
                " quantity_ordered, quantity_received, unit_cost, created_at, updated_at)"
                " VALUES (:po_item, :po, :product, 1, 4, 0, 5, now(), now())",
            ):
                connection.execute(text(statement), ids)
    finally:
        engine.dispose()

    _alembic(scratch_url, "upgrade", "head")

    from app.services import orders as order_service

    engine = create_app_engine(scratch_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        item = order_service.get_order(session, ids["order"]).items[0]
        assert item.quantity_incoming == Decimal("4.000")
        assert item.quantity_unallocated == Decimal("2.000")
        assigned = session.execute(
            text("SELECT quantity FROM purchase_assignments WHERE purchase_order_item_id = :po_item"),
            {"po_item": ids["po_item"]},
        ).scalar_one()
        assert assigned == Decimal("4.000")
    finally:
        session.close()
        engine.dispose()
