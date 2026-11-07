"""Suppliers, purchase orders and goods receipts."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models import (
    GoodsReceipt,
    GoodsReceiptItem,
    MovementType,
    PurchaseOrder,
    PurchaseOrderStatus,
    StockMovement,
    StockReservation,
    Supplier,
)
from app.services import purchasing as purchasing_service
from app.services import suppliers as supplier_service
from tests.conftest import (
    D,
    M,
    assert_costing_invariant,
    assert_reservations_match_lines,
    ledger_balance,
    po_line,
    receipt_line,
    resync,
    stock_state,
)


# ---------------------------------------------------------------------------
# Test 1: supplier master
# ---------------------------------------------------------------------------

def test_1_supplier_crud_and_archiving(db, make_supplier):
    created = supplier_service.create_supplier(
        db, name="Northgate Mills", contact_person="R. Shah", phone="555-0100"
    )
    # The backend generates a code when none is supplied.
    assert created.code.startswith("SUP-")
    assert created.is_active is True

    with_code = supplier_service.create_supplier(db, code=" acme-1 ", name="Acme Supplies")
    assert with_code.code == "ACME-1"

    with pytest.raises(ConflictError, match="already exists"):
        supplier_service.create_supplier(db, code="acme-1", name="Clone")
    with pytest.raises(ValidationError, match="name is required"):
        supplier_service.create_supplier(db, name="   ")

    updated = supplier_service.update_supplier(
        db, created.id, {"name": "Northgate Mills Ltd", "email": "sales@northgate.test"}
    )
    assert updated.name == "Northgate Mills Ltd"
    assert updated.email == "sales@northgate.test"

    assert [row.id for row in supplier_service.list_suppliers(db, search="acme")] == [
        with_code.id
    ]
    assert len(supplier_service.list_suppliers(db)) == 2

    archived = supplier_service.archive_supplier(db, created.id)
    assert archived.is_active is False
    assert created.id not in {row.id for row in supplier_service.list_suppliers(db)}
    assert created.id in {
        row.id for row in supplier_service.list_suppliers(db, include_inactive=True)
    }

    with pytest.raises(NotFoundError):
        supplier_service.get_supplier(db, uuid.uuid4())


def test_30_an_archived_supplier_keeps_its_history(
    db, make_supplier, make_product, make_purchase_order
):
    supplier = make_supplier("Northgate Mills")
    product = make_product("Widget", opening_stock=0)
    order = make_purchase_order(supplier, [po_line(product, 50, "40.00")])

    purchasing_service.create_goods_receipt(
        db, order.id, [receipt_line(order.items[0], 20)]
    )
    supplier_service.archive_supplier(db, supplier.id)

    resync(db)
    detail = supplier_service.supplier_detail(db, supplier.id)
    assert detail["is_active"] is False
    assert len(detail["purchase_orders"]) == 1
    assert detail["purchase_orders"][0]["po_number"] == order.po_number
    assert len(detail["goods_receipts"]) == 1
    assert detail["goods_receipts"][0]["total_quantity"] == D(20)
    # The database itself refuses to lose a supplier that has history.
    assert supplier_service.has_history(db, supplier.id) is True


# ---------------------------------------------------------------------------
# Tests 2-4: purchase orders
# ---------------------------------------------------------------------------

def test_2_create_a_purchase_order_with_several_products(
    db, make_supplier, make_product, make_purchase_order
):
    supplier = make_supplier("Northgate Mills")
    first = make_product("Product A", opening_stock=0, sku="P-A")
    second = make_product("Product B", opening_stock=0, sku="P-B")

    order = make_purchase_order(
        supplier,
        [po_line(first, 100, "40.00"), po_line(second, 50, "12.50")],
        confirm=False,
        notes="Call before delivery",
    )

    assert order.po_number.startswith("PO-")
    assert order.status == PurchaseOrderStatus.DRAFT
    assert len(order.items) == 2

    view = purchasing_service.to_po_view(order)
    assert view["total_ordered"] == D(150)
    assert view["total_remaining"] == D(150)
    assert view["total_cost"] == M(4625)
    assert view["is_editable"] is True
    assert view["can_receive"] is False


def test_the_same_product_twice_is_consolidated(
    db, make_supplier, make_product, make_purchase_order
):
    supplier = make_supplier("Northgate Mills")
    product = make_product("Widget", opening_stock=0)
    order = make_purchase_order(
        supplier, [po_line(product, 30, "40.00"), po_line(product, 20, "41.00")]
    )
    assert len(order.items) == 1
    assert order.items[0].quantity_ordered == D(50)
    assert order.items[0].unit_cost == Decimal("41.0000")


def test_3_confirming_a_purchase_order_moves_no_stock(
    db, make_supplier, make_product, make_purchase_order
):
    supplier = make_supplier("Northgate Mills")
    product = make_product("Widget", opening_stock=7)
    before = stock_state(db, product.id)
    movements_before = db.execute(select(func.count()).select_from(StockMovement)).scalar_one()

    order = make_purchase_order(supplier, [po_line(product, 100, "40.00")], confirm=False)
    assert stock_state(db, product.id) == before

    confirmed = purchasing_service.confirm_purchase_order(db, order.id)
    assert confirmed.status == PurchaseOrderStatus.ORDERED
    assert confirmed.ordered_at is not None
    assert confirmed.can_receive is True

    # Ordering is a promise, not an arrival: nothing moved.
    resync(db)
    assert stock_state(db, product.id) == before
    assert (
        db.execute(select(func.count()).select_from(StockMovement)).scalar_one()
        == movements_before
    )

    with pytest.raises(ConflictError, match="already ordered"):
        purchasing_service.confirm_purchase_order(db, order.id)


def test_4_invalid_suppliers_products_and_quantities_are_rejected(
    db, make_supplier, make_product
):
    supplier = make_supplier("Northgate Mills")
    product = make_product("Widget", opening_stock=0)

    with pytest.raises(NotFoundError, match="Supplier"):
        purchasing_service.create_purchase_order(db, uuid.uuid4(), [po_line(product, 1)])
    with pytest.raises(NotFoundError, match="Product"):
        purchasing_service.create_purchase_order(
            db, supplier.id, [{"product_id": uuid.uuid4(), "quantity_ordered": 1}]
        )
    with pytest.raises(ValidationError, match="greater than zero"):
        purchasing_service.create_purchase_order(db, supplier.id, [po_line(product, 0)])
    with pytest.raises(ValidationError, match="greater than zero"):
        purchasing_service.create_purchase_order(db, supplier.id, [po_line(product, "-5")])
    with pytest.raises(ValidationError, match="at least one product"):
        purchasing_service.create_purchase_order(db, supplier.id, [])
    with pytest.raises(ValidationError, match="cannot be negative"):
        purchasing_service.create_purchase_order(
            db, supplier.id, [po_line(product, 5, "-1.00")]
        )

    resync(db)
    assert db.execute(select(func.count()).select_from(PurchaseOrder)).scalar_one() == 0


def test_an_archived_supplier_or_product_cannot_be_ordered_from(
    db, make_supplier, make_product
):
    from app.services import products as product_service

    supplier = make_supplier("Northgate Mills")
    product = make_product("Widget", opening_stock=0)

    product_service.archive_product(db, product.id)
    with pytest.raises(ValidationError, match="archived"):
        purchasing_service.create_purchase_order(db, supplier.id, [po_line(product, 5)])

    product_service.update_product(db, product.id, {"is_active": True})
    supplier_service.archive_supplier(db, supplier.id)
    with pytest.raises(ValidationError, match="archived"):
        purchasing_service.create_purchase_order(db, supplier.id, [po_line(product, 5)])


def test_a_draft_order_can_be_edited_but_a_placed_one_cannot(
    db, make_supplier, make_product, make_purchase_order
):
    supplier = make_supplier("Northgate Mills")
    first = make_product("Product A", opening_stock=0, sku="P-A")
    second = make_product("Product B", opening_stock=0, sku="P-B")

    order = make_purchase_order(supplier, [po_line(first, 10, "40.00")], confirm=False)
    updated = purchasing_service.update_purchase_order(
        db,
        order.id,
        {"items": [po_line(first, 25, "42.00"), po_line(second, 5, "9.00")], "notes": "Revised"},
    )
    assert {item.product_id: item.quantity_ordered for item in updated.items} == {
        first.id: D(25),
        second.id: D(5),
    }
    assert updated.notes == "Revised"

    purchasing_service.confirm_purchase_order(db, order.id)
    with pytest.raises(ConflictError, match="already been placed"):
        purchasing_service.update_purchase_order(
            db, order.id, {"items": [po_line(first, 99)]}
        )
    # Notes stay editable after placing.
    assert purchasing_service.update_purchase_order(
        db, order.id, {"notes": "Chased supplier"}
    ).notes == "Chased supplier"


# ---------------------------------------------------------------------------
# Tests 5-8: receiving
# ---------------------------------------------------------------------------

def test_5_and_6_partial_then_final_receipt(
    db, make_supplier, make_product, make_purchase_order
):
    """The brief's example: 100 of A and 50 of B, delivered in two drops."""
    supplier = make_supplier("Northgate Mills")
    product_a = make_product("Product A", opening_stock=0, sku="P-A")
    product_b = make_product("Product B", opening_stock=0, sku="P-B")
    order = make_purchase_order(
        supplier, [po_line(product_a, 100, "40.00"), po_line(product_b, 50, "12.00")]
    )
    item_a, item_b = order.items[0], order.items[1]

    first = purchasing_service.create_goods_receipt(
        db,
        order.id,
        [receipt_line(item_a, 40), receipt_line(item_b, 50)],
        delivery_note_reference="DN-771",
    )

    assert first["receipt_number"].startswith("GR-")
    assert first["total_received"] == D(90)
    assert first["po_status"] == PurchaseOrderStatus.PARTIALLY_RECEIVED
    by_sku = {line["product_sku"]: line for line in first["lines"]}
    assert by_sku["P-A"]["quantity_received_on_po"] == D(40)
    assert by_sku["P-A"]["quantity_remaining_on_po"] == D(60)
    assert by_sku["P-B"]["quantity_received_on_po"] == D(50)
    assert by_sku["P-B"]["quantity_remaining_on_po"] == D(0)

    assert stock_state(db, product_a.id)["physical"] == D(40)
    assert stock_state(db, product_b.id)["physical"] == D(50)

    resync(db)
    second = purchasing_service.create_goods_receipt(
        db, order.id, [receipt_line(order.items[0], 60)]
    )
    assert second["po_status"] == PurchaseOrderStatus.RECEIVED
    assert second["lines"][0]["quantity_remaining_on_po"] == D(0)

    resync(db)
    assert stock_state(db, product_a.id)["physical"] == D(100)
    assert ledger_balance(db, product_a.id) == D(100)
    final = purchasing_service.to_po_view(purchasing_service.get_purchase_order(db, order.id))
    assert final["total_received"] == D(150)
    assert final["total_remaining"] == D(0)
    assert len(final["receipts"]) == 2
    assert_costing_invariant(db, product_a.id)


def test_7_over_receipt_is_rejected_unless_overridden(
    db, make_supplier, make_product, make_purchase_order
):
    supplier = make_supplier("Northgate Mills")
    product = make_product("Widget", opening_stock=0)
    order = make_purchase_order(supplier, [po_line(product, 10, "40.00")])

    with pytest.raises(ValidationError, match="over-receipt override"):
        purchasing_service.create_goods_receipt(
            db, order.id, [receipt_line(order.items[0], 12)]
        )
    resync(db)
    assert stock_state(db, product.id)["physical"] == D(0)
    assert db.execute(select(func.count()).select_from(GoodsReceipt)).scalar_one() == 0

    # The override needs a recorded reason.
    with pytest.raises(ValidationError, match="needs a recorded reason"):
        purchasing_service.create_goods_receipt(
            db, order.id, [receipt_line(order.items[0], 12)], allow_over_receipt=True
        )

    resync(db)
    result = purchasing_service.create_goods_receipt(
        db,
        order.id,
        [receipt_line(order.items[0], 12, over_receipt_reason="Supplier shipped a full case")],
        allow_over_receipt=True,
    )
    assert result["lines"][0]["is_over_receipt"] is True
    assert result["lines"][0]["over_receipt_reason"] == "Supplier shipped a full case"
    assert result["po_status"] == PurchaseOrderStatus.RECEIVED

    resync(db)
    assert stock_state(db, product.id)["physical"] == D(12)
    # Remaining never goes negative.
    assert purchasing_service.get_purchase_order(db, order.id).items[0].quantity_remaining == D(0)


def test_8_a_cancelled_purchase_order_cannot_receive_goods(
    db, make_supplier, make_product, make_purchase_order
):
    supplier = make_supplier("Northgate Mills")
    product = make_product("Widget", opening_stock=0)
    order = make_purchase_order(supplier, [po_line(product, 10, "40.00")])

    purchasing_service.cancel_purchase_order(db, order.id, reason="Supplier out of stock")

    with pytest.raises(ConflictError, match="cancelled"):
        purchasing_service.create_goods_receipt(
            db, order.id, [receipt_line(order.items[0], 5)]
        )
    with pytest.raises(ConflictError, match="cancelled"):
        purchasing_service.preview_receipt(db, order.id, [receipt_line(order.items[0], 5)])

    resync(db)
    assert stock_state(db, product.id)["physical"] == D(0)
    assert db.execute(select(func.count()).select_from(GoodsReceipt)).scalar_one() == 0


def test_a_draft_order_cannot_receive_goods(
    db, make_supplier, make_product, make_purchase_order
):
    supplier = make_supplier("Northgate Mills")
    product = make_product("Widget", opening_stock=0)
    order = make_purchase_order(supplier, [po_line(product, 10)], confirm=False)

    with pytest.raises(ConflictError, match="only a placed order"):
        purchasing_service.create_goods_receipt(
            db, order.id, [receipt_line(order.items[0], 5)]
        )


# ---------------------------------------------------------------------------
# Tests 9-15: compulsory allocation on a goods receipt
# ---------------------------------------------------------------------------

@pytest.fixture()
def three_waiting_customers(db, make_product, make_customer, order_for, make_supplier,
                            make_purchase_order):
    """5, 4 and 6 units waiting, in that order, with a PO for 30 on the way."""
    product = make_product("Widget", opening_stock=0, mrp="100.00")
    customers = [make_customer("Customer {}".format(letter)) for letter in "ABC"]
    orders = [
        order_for(customers[0], product, 5),
        order_for(customers[1], product, 4),
        order_for(customers[2], product, 6),
    ]
    supplier = make_supplier("Northgate Mills")
    po = make_purchase_order(supplier, [po_line(product, 30, "40.00")])
    return product, customers, orders, po


def test_9_and_10_fifo_allocation_on_a_goods_receipt(db, three_waiting_customers):
    product, _customers, orders, po = three_waiting_customers

    preview = purchasing_service.preview_receipt(db, po.id, [receipt_line(po.items[0], 10)])
    line = preview["lines"][0]
    assert line["eligible_demand"] == D(15)
    assert line["required_allocation"] == D(10)
    assert line["surplus_quantity"] == D(0)
    assert [row["proposed_allocation"] for row in line["allocations"]] == [D(5), D(4), D(1)]
    assert line["available_stock_after"] == D(0)

    result = purchasing_service.create_goods_receipt(
        db, po.id, [receipt_line(po.items[0], 10)]
    )
    allocated = {
        row["customer_name"]: row["quantity_allocated"] for row in result["lines"][0]["allocations"]
    }
    assert allocated == {"Customer A": D(5), "Customer B": D(4), "Customer C": D(1)}

    assert stock_state(db, product.id) == {
        "physical": D(10),
        "reserved": D(10),
        "available": D(0),
        "pending": D(15),
        "net": D(-5),
    }
    assert_reservations_match_lines(db, product.id)


def test_receipt_reports_stock_as_in_less_promised(db, three_waiting_customers):
    product, _customers, _orders, po = three_waiting_customers
    result = purchasing_service.create_goods_receipt(
        db, po.id, [receipt_line(po.items[0], 10)]
    )
    # 15 sold, 10 arrived: 5 short of what is physically here ...
    assert result["lines"][0]["net_stock_position_after"] == D(-5)
    # ... but stock counted all 30 when the PO was confirmed, so receiving
    # moves nothing: 30 bought less 15 sold.
    assert result["lines"][0]["stock_after"] == D(15)


def test_11_no_surplus_is_released_while_demand_is_unmet(db, three_waiting_customers):
    product, _customers, _orders, po = three_waiting_customers
    result = purchasing_service.create_goods_receipt(
        db, po.id, [receipt_line(po.items[0], 12)]
    )
    assert result["total_allocated"] == D(12)
    assert result["total_surplus"] == D(0)
    assert stock_state(db, product.id)["available"] == D(0)


def test_12_a_valid_custom_distribution_is_accepted(db, three_waiting_customers):
    product, _customers, orders, po = three_waiting_customers

    result = purchasing_service.create_goods_receipt(
        db,
        po.id,
        [
            receipt_line(
                po.items[0],
                10,
                allocations=[
                    {"order_item_id": orders[1].items[0].id, "quantity": 4},
                    {"order_item_id": orders[2].items[0].id, "quantity": 6},
                ],
            )
        ],
    )
    allocated = {
        row["customer_name"]: row["quantity_allocated"] for row in result["lines"][0]["allocations"]
    }
    assert allocated == {"Customer B": D(4), "Customer C": D(6)}
    assert stock_state(db, product.id)["available"] == D(0)
    assert_reservations_match_lines(db, product.id)


@pytest.mark.parametrize("distribution", ["short", "long", "beyond_line"])
def test_13_an_invalid_distribution_changes_nothing(db, three_waiting_customers, distribution):
    from app.errors import AllocationError

    product, _customers, orders, po = three_waiting_customers
    cases = {
        "short": [{"order_item_id": orders[0].items[0].id, "quantity": 3}],
        "long": [
            {"order_item_id": orders[0].items[0].id, "quantity": 5},
            {"order_item_id": orders[1].items[0].id, "quantity": 4},
            {"order_item_id": orders[2].items[0].id, "quantity": 6},
        ],
        "beyond_line": [{"order_item_id": orders[0].items[0].id, "quantity": 10}],
    }

    with pytest.raises(AllocationError):
        purchasing_service.create_goods_receipt(
            db, po.id, [receipt_line(po.items[0], 10, allocations=cases[distribution])]
        )

    resync(db)
    assert stock_state(db, product.id)["physical"] == D(0)
    assert db.execute(select(func.count()).select_from(GoodsReceipt)).scalar_one() == 0
    assert db.execute(select(func.count()).select_from(StockReservation)).scalar_one() == 0
    assert db.execute(select(func.count()).select_from(StockMovement)).scalar_one() == 0
    assert purchasing_service.get_purchase_order(db, po.id).items[0].quantity_received == D(0)


def test_14_a_receipt_bigger_than_demand_leaves_a_surplus(
    db, make_product, make_customer, order_for, make_supplier, make_purchase_order
):
    product = make_product("Widget", opening_stock=0)
    customer = make_customer("Customer A")
    order_for(customer, product, 5)
    supplier = make_supplier("Northgate Mills")
    po = make_purchase_order(supplier, [po_line(product, 20, "40.00")])

    result = purchasing_service.create_goods_receipt(db, po.id, [receipt_line(po.items[0], 20)])

    assert result["total_allocated"] == D(5)
    assert result["total_surplus"] == D(15)
    assert stock_state(db, product.id) == {
        "physical": D(20),
        "reserved": D(5),
        "available": D(15),
        "pending": D(5),
        "net": D(15),
    }
    assert_reservations_match_lines(db, product.id)


def test_15_a_repeated_submission_does_not_duplicate_stock(db, three_waiting_customers):
    product, _customers, _orders, po = three_waiting_customers

    first = purchasing_service.create_goods_receipt(
        db, po.id, [receipt_line(po.items[0], 10)], idempotency_key="double-click"
    )
    second = purchasing_service.create_goods_receipt(
        db, po.id, [receipt_line(po.items[0], 10)], idempotency_key="double-click"
    )

    assert second["receipt_id"] == str(first["receipt_id"])
    resync(db)
    assert db.execute(select(func.count()).select_from(GoodsReceipt)).scalar_one() == 1
    assert db.execute(select(func.count()).select_from(GoodsReceiptItem)).scalar_one() == 1
    assert stock_state(db, product.id)["physical"] == D(10)
    assert stock_state(db, product.id)["reserved"] == D(10)
    assert purchasing_service.get_purchase_order(db, po.id).items[0].quantity_received == D(10)


# ---------------------------------------------------------------------------
# Test 22: rollback
# ---------------------------------------------------------------------------

def test_22_a_failed_goods_receipt_rolls_everything_back(
    db, make_supplier, make_product, make_purchase_order, make_customer, order_for
):
    """One good line and one bad line: neither is saved."""
    supplier = make_supplier("Northgate Mills")
    good = make_product("Product A", opening_stock=0, sku="P-A")
    bad = make_product("Product B", opening_stock=0, sku="P-B")
    customer = make_customer("Customer A")
    order_for(customer, good, 5)

    po = make_purchase_order(supplier, [po_line(good, 50, "40.00"), po_line(bad, 50, "12.00")])

    with pytest.raises(ValidationError, match="over-receipt override"):
        purchasing_service.create_goods_receipt(
            db,
            po.id,
            # The first line is fine; the second asks for more than was ordered.
            [receipt_line(po.items[0], 20), receipt_line(po.items[1], 80)],
        )

    resync(db)
    assert db.execute(select(func.count()).select_from(GoodsReceipt)).scalar_one() == 0
    assert db.execute(select(func.count()).select_from(StockMovement)).scalar_one() == 0
    assert db.execute(select(func.count()).select_from(StockReservation)).scalar_one() == 0
    assert stock_state(db, good.id)["physical"] == D(0)
    assert stock_state(db, bad.id)["physical"] == D(0)

    refreshed = purchasing_service.get_purchase_order(db, po.id)
    assert refreshed.status == PurchaseOrderStatus.ORDERED
    assert all(item.quantity_received == D(0) for item in refreshed.items)

    # And a valid receipt still works afterwards.
    result = purchasing_service.create_goods_receipt(
        db, po.id, [receipt_line(refreshed.items[0], 20)]
    )
    assert result["total_received"] == D(20)
    assert_costing_invariant(db, good.id)


def test_a_goods_receipt_writes_one_movement_per_line(
    db, make_supplier, make_product, make_purchase_order
):
    supplier = make_supplier("Northgate Mills")
    product = make_product("Widget", opening_stock=0)
    po = make_purchase_order(supplier, [po_line(product, 50, "40.00")])

    purchasing_service.create_goods_receipt(db, po.id, [receipt_line(po.items[0], 20)])

    resync(db)
    movements = (
        db.execute(select(StockMovement).where(StockMovement.product_id == product.id))
        .scalars()
        .all()
    )
    assert [movement.movement_type for movement in movements] == [MovementType.GOODS_RECEIPT]
    assert movements[0].quantity_change == D(20)
    assert movements[0].reference_type == "goods_receipt_item"
    assert ledger_balance(db, product.id) == D(20)


def test_actual_receipt_cost_can_differ_from_the_ordered_cost(
    db, make_supplier, make_product, make_purchase_order
):
    from app.services import costing

    supplier = make_supplier("Northgate Mills")
    product = make_product("Widget", opening_stock=0)
    po = make_purchase_order(supplier, [po_line(product, 20, "40.00")])

    # Ordered at 40, actually invoiced at 44.
    result = purchasing_service.create_goods_receipt(
        db, po.id, [receipt_line(po.items[0], 20, unit_cost="44.00")]
    )
    assert result["lines"][0]["unit_cost"] == Decimal("44.0000")
    assert result["total_cost"] == M(880)

    resync(db)
    # The purchase order keeps the price that was agreed.
    assert purchasing_service.get_purchase_order(db, po.id).items[0].unit_cost == Decimal("40.0000")
    # Stock is valued at what was actually paid.
    assert costing.stock_valuation(db, product.id)["stock_value"] == M(880)


def test_receipt_listing_and_detail(db, make_supplier, make_product, make_purchase_order):
    supplier = make_supplier("Northgate Mills")
    product = make_product("Widget", opening_stock=0)
    po = make_purchase_order(supplier, [po_line(product, 50, "40.00")])
    created = purchasing_service.create_goods_receipt(
        db, po.id, [receipt_line(po.items[0], 20)], delivery_note_reference="DN-900"
    )

    rows = purchasing_service.list_goods_receipts(db)
    assert [row["receipt_number"] for row in rows] == [created["receipt_number"]]
    assert rows[0]["delivery_note_reference"] == "DN-900"
    assert rows[0]["total_quantity"] == D(20)

    assert purchasing_service.list_goods_receipts(db, search="dn-900")[0]["id"] == rows[0]["id"]
    assert purchasing_service.list_goods_receipts(db, supplier_id=supplier.id)
    detail = purchasing_service.get_goods_receipt(db, created["receipt_id"])
    assert detail["receipt_number"] == created["receipt_number"]

    with pytest.raises(NotFoundError):
        purchasing_service.get_goods_receipt(db, uuid.uuid4())
