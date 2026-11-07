"""Test 6: product and customer master integrity."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models import Customer, OrderStatus, Product, SalesOrder
from app.services import customers as customer_service
from app.services import orders as order_service
from app.services import products as product_service
from tests.conftest import D, state, stock_state


def test_duplicate_sku_is_rejected(db, make_product):
    make_product("Widget", sku="ABC-1")
    with pytest.raises(ConflictError, match="already exists"):
        product_service.create_product(db, sku="ABC-1", name="Another widget")
    # SKUs are normalised, so case is not an escape hatch.
    with pytest.raises(ConflictError, match="already exists"):
        product_service.create_product(db, sku="abc-1", name="Another widget")
    assert db.execute(select(func.count()).select_from(Product)).scalar_one() == 1


def test_sku_cannot_be_changed_to_a_duplicate(db, make_product):
    first = make_product("First", sku="ABC-1")
    second = make_product("Second", sku="ABC-2")
    with pytest.raises(ConflictError):
        product_service.update_product(db, second.id, {"sku": "ABC-1"})
    db.expire_all()
    assert product_service.get_product(db, second.id).sku == "ABC-2"


def test_negative_mrp_and_stock_are_rejected(db):
    with pytest.raises(ValidationError, match="MRP cannot be negative"):
        product_service.create_product(db, sku="X-1", name="Widget", mrp="-1.00")
    with pytest.raises(ValidationError, match="Opening stock cannot be negative"):
        product_service.create_product(db, sku="X-2", name="Widget", opening_stock=-5)
    with pytest.raises(ValidationError, match="required"):
        product_service.create_product(db, sku="  ", name="Widget")
    with pytest.raises(ValidationError, match="name is required"):
        product_service.create_product(db, sku="X-3", name="   ")
    assert db.execute(select(func.count()).select_from(Product)).scalar_one() == 0


def test_product_edit_cannot_touch_stock(db, make_product):
    """Stock is not an editable product field; only stock operations move it."""
    from app import schemas

    product = make_product("Widget", opening_stock=10)
    assert "physical_stock" not in schemas.ProductUpdate.model_fields

    product_service.update_product(db, product.id, {"name": "Renamed", "mrp": "250.00"})
    db.expire_all()
    updated = product_service.get_product(db, product.id)
    assert updated.name == "Renamed"
    assert updated.physical_stock == D(10)


def test_unknown_ids_raise_not_found(db):
    missing = uuid.uuid4()
    with pytest.raises(NotFoundError):
        product_service.get_product(db, missing)
    with pytest.raises(NotFoundError):
        customer_service.get_customer(db, missing)
    with pytest.raises(NotFoundError):
        order_service.get_order(db, missing)


def test_customer_name_is_required(db):
    with pytest.raises(ValidationError, match="name is required"):
        customer_service.create_customer(db, name="   ")


def test_archiving_a_customer_leaves_history_untouched(db, make_product, make_customer, order_for):
    product = make_product("Widget", opening_stock=15)
    customer = make_customer("Customer A", phone="555-0100")
    order = order_for(customer, product, 20)

    customer_service.archive_customer(db, customer.id)
    db.expire_all()

    archived = customer_service.get_customer(db, customer.id)
    assert archived.is_active is False

    historical = order_service.get_order(db, order.id)
    assert historical.customer_id == customer.id
    assert historical.customer.name == "Customer A"
    assert historical.items[0].quantity_reserved == D(15)
    assert historical.items[0].quantity_pending == D(20)
    assert historical.status == OrderStatus.PENDING
    # The obligation survives archiving, so the net position is unchanged.
    assert state(db, product.id)["net"] == D(-5)

    # Archived customers drop out of the default list but are still reachable.
    assert customer.id not in {row.id for row in customer_service.list_customers(db)}
    assert customer.id in {
        row.id for row in customer_service.list_customers(db, include_inactive=True)
    }


def test_archiving_a_product_leaves_history_untouched(db, make_product, make_customer, order_for):
    product = make_product("Widget", opening_stock=15)
    customer = make_customer("Customer A")
    order = order_for(customer, product, 20)

    product_service.archive_product(db, product.id)
    db.expire_all()

    assert product_service.get_product(db, product.id).is_active is False
    assert order_service.get_order(db, order.id).items[0].quantity_reserved == D(15)
    assert product_service.has_history(db, product.id) is True


def test_products_and_customers_with_history_cannot_be_deleted(
    db, make_product, make_customer, order_for
):
    """Foreign keys are RESTRICT, so the database itself refuses the delete."""
    product = make_product("Widget", opening_stock=15)
    customer = make_customer("Customer A")
    order_for(customer, product, 20)

    db.expire_all()
    with pytest.raises(IntegrityError):
        db.execute(Product.__table__.delete().where(Product.id == product.id))
        db.flush()
    db.rollback()

    with pytest.raises(IntegrityError):
        db.execute(Customer.__table__.delete().where(Customer.id == customer.id))
        db.flush()
    db.rollback()

    assert db.execute(select(func.count()).select_from(Product)).scalar_one() == 1
    assert db.execute(select(func.count()).select_from(Customer)).scalar_one() == 1
    assert db.execute(select(func.count()).select_from(SalesOrder)).scalar_one() == 1


def test_product_search_and_sort(db, make_product):
    make_product("Alpha widget", sku="AA-1")
    make_product("Beta gadget", sku="BB-1")
    make_product("Gamma widget", sku="CC-1")

    names = [row["name"] for row in product_service.list_products(db, search="widget")]
    assert names == ["Alpha widget", "Gamma widget"]
    assert [row["sku"] for row in product_service.list_products(db, search="bb")] == ["BB-1"]

    descending = [row["name"] for row in product_service.list_products(db, sort_dir="desc")]
    assert descending == ["Gamma widget", "Beta gadget", "Alpha widget"]


def test_customer_outstanding_spans_products(db, make_product, make_customer, make_order):
    first = make_product("First", opening_stock=1, sku="P-1")
    second = make_product("Second", opening_stock=0, sku="P-2")
    customer = make_customer("Customer A")

    make_order(
        customer,
        [
            {"product_id": first.id, "quantity_ordered": 4},
            {"product_id": second.id, "quantity_ordered": 7},
        ],
    )

    outstanding = customer_service.customer_outstanding(db, customer.id)
    # Everything ordered is still owed: reserving the one unit on hand does not
    # reduce the obligation, only delivering it would.
    assert {row["product_sku"]: row["pending_quantity"] for row in outstanding} == {
        "P-1": D(4),
        "P-2": D(7),
    }
