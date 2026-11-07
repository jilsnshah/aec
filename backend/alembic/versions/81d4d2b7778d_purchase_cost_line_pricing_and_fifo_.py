"""purchase cost, line pricing and FIFO cost layers

Revision ID: 81d4d2b7778d
Revises: 5aaef60a1502
Create Date: 2026-10-28 16:02:15.130287
"""
import datetime
import decimal
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '81d4d2b7778d'
down_revision: Union[str, None] = '5aaef60a1502'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- New money columns on existing tables ----------------------------
    # Every NOT NULL addition carries a server default so rows that already
    # exist remain valid; the defaults are then dropped from the model's point
    # of view because the application always supplies a value.
    with op.batch_alter_table("products", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("last_purchase_price", sa.Numeric(precision=14, scale=4), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_products_last_purchase_price_non_negative",
            "last_purchase_price IS NULL OR last_purchase_price >= 0",
        )

    with op.batch_alter_table("sales_order_items", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "discount_percent",
                sa.Numeric(precision=5, scale=2),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "unit_price_net",
                sa.Numeric(precision=14, scale=4),
                nullable=False,
                server_default="0",
            )
        )

    # Orders placed before discounts existed were sold at the list price.
    op.execute("UPDATE sales_order_items SET unit_price = 0 WHERE unit_price IS NULL")
    op.execute("UPDATE sales_order_items SET unit_price_net = unit_price")

    with op.batch_alter_table("sales_order_items", schema=None) as batch_op:
        batch_op.alter_column(
            "unit_price",
            existing_type=sa.NUMERIC(precision=14, scale=2),
            type_=sa.Numeric(precision=14, scale=4),
            nullable=False,
            existing_nullable=True,
        )
        batch_op.create_check_constraint(
            "ck_order_items_unit_price_non_negative", "unit_price >= 0"
        )
        batch_op.create_check_constraint(
            "ck_order_items_unit_price_net_non_negative", "unit_price_net >= 0"
        )
        batch_op.create_check_constraint(
            "ck_order_items_discount_percent_range",
            "discount_percent >= 0 AND discount_percent <= 100",
        )

    with op.batch_alter_table("sales_orders", schema=None) as batch_op:
        for column in ("subtotal_amount", "discount_amount", "total_amount"):
            batch_op.add_column(
                sa.Column(
                    column, sa.Numeric(precision=14, scale=2), nullable=False, server_default="0"
                )
            )

    op.execute(
        """
        UPDATE sales_orders SET
            subtotal_amount = COALESCE((
                SELECT SUM(i.unit_price * i.quantity_ordered)
                FROM sales_order_items i WHERE i.order_id = sales_orders.id
            ), 0),
            total_amount = COALESCE((
                SELECT SUM(i.unit_price_net * i.quantity_ordered)
                FROM sales_order_items i WHERE i.order_id = sales_orders.id
            ), 0)
        """
    )
    op.execute("UPDATE sales_orders SET discount_amount = subtotal_amount - total_amount")

    with op.batch_alter_table("stock_allocations", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "cost_amount",
                sa.Numeric(precision=14, scale=2),
                nullable=False,
                server_default="0",
            )
        )

    with op.batch_alter_table("stock_receipts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "unit_cost", sa.Numeric(precision=14, scale=4), nullable=False, server_default="0"
            )
        )
        batch_op.add_column(
            sa.Column(
                "total_cost", sa.Numeric(precision=14, scale=2), nullable=False, server_default="0"
            )
        )
        batch_op.add_column(sa.Column("supplier_reference", sa.String(length=128), nullable=True))
        batch_op.create_check_constraint(
            "ck_stock_receipts_unit_cost_non_negative", "unit_cost >= 0"
        )

    # --- FIFO cost layers -------------------------------------------------
    op.create_table(
        "stock_cost_layers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "OPENING_STOCK",
                "STOCK_RECEIPT",
                "ORDER_FULFILMENT",
                "ADJUSTMENT",
                name="movement_type",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("unit_cost", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("quantity_remaining", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_cost_layers_quantity_positive"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_cost_layers_unit_cost_non_negative"),
        sa.CheckConstraint(
            "quantity_remaining >= 0 AND quantity_remaining <= quantity",
            name="ck_cost_layers_remaining_within_quantity",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("stock_cost_layers", schema=None) as batch_op:
        batch_op.create_index(
            "ix_cost_layers_fifo", ["product_id", "created_at", "id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_stock_cost_layers_created_at"), ["created_at"], unique=False
        )

    op.create_table(
        "stock_layer_consumptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("stock_allocation_id", sa.Uuid(), nullable=False),
        sa.Column("stock_cost_layer_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("cost_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_layer_consumptions_quantity_positive"),
        sa.ForeignKeyConstraint(
            ["stock_allocation_id"], ["stock_allocations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["stock_cost_layer_id"], ["stock_cost_layers.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("stock_layer_consumptions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_stock_layer_consumptions_stock_allocation_id"),
            ["stock_allocation_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_stock_layer_consumptions_stock_cost_layer_id"),
            ["stock_cost_layer_id"],
            unique=False,
        )

    _backfill_cost_layers()


def _backfill_cost_layers() -> None:
    """Open one zero-cost layer per product that already holds stock.

    Stock that predates cost tracking has no known purchase price. Valuing it at
    zero is honest -- it says "we do not know what this cost" rather than
    inventing a figure -- and it keeps the costing invariant (layers sum to
    physical stock) true from the first day. The note on each layer flags it so
    the gap is visible in the audit trail.
    """
    connection = op.get_bind()
    products = connection.execute(
        sa.text(
            "SELECT id, physical_stock, created_at FROM products WHERE physical_stock > 0"
        )
    ).fetchall()
    if not products:
        return

    layers = sa.table(
        "stock_cost_layers",
        sa.column("id", sa.Uuid()),
        sa.column("product_id", sa.Uuid()),
        sa.column("source", sa.String()),
        sa.column("source_id", sa.Uuid()),
        sa.column("unit_cost", sa.Numeric(14, 4)),
        sa.column("quantity", sa.Numeric(18, 3)),
        sa.column("quantity_remaining", sa.Numeric(18, 3)),
        sa.column("note", sa.Text()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        layers,
        [
            {
                "id": uuid.uuid4(),
                "product_id": row[0] if isinstance(row[0], uuid.UUID) else uuid.UUID(str(row[0])),
                "source": "OPENING_STOCK",
                "source_id": None,
                "unit_cost": decimal.Decimal("0.0000"),
                "quantity": decimal.Decimal(str(row[1])),
                "quantity_remaining": decimal.Decimal(str(row[1])),
                "note": "Backfilled when cost tracking was introduced; purchase price unknown",
                "created_at": row[2] if isinstance(row[2], datetime.datetime) else datetime.datetime.now(datetime.timezone.utc),
            }
            for row in products
        ],
    )


def downgrade() -> None:
    op.drop_table("stock_layer_consumptions")
    op.drop_table("stock_cost_layers")

    with op.batch_alter_table("stock_receipts", schema=None) as batch_op:
        batch_op.drop_constraint("ck_stock_receipts_unit_cost_non_negative", type_="check")
        batch_op.drop_column("supplier_reference")
        batch_op.drop_column("total_cost")
        batch_op.drop_column("unit_cost")

    with op.batch_alter_table("stock_allocations", schema=None) as batch_op:
        batch_op.drop_column("cost_amount")

    with op.batch_alter_table("sales_orders", schema=None) as batch_op:
        batch_op.drop_column("total_amount")
        batch_op.drop_column("discount_amount")
        batch_op.drop_column("subtotal_amount")

    with op.batch_alter_table("sales_order_items", schema=None) as batch_op:
        batch_op.drop_constraint("ck_order_items_discount_percent_range", type_="check")
        batch_op.drop_constraint("ck_order_items_unit_price_net_non_negative", type_="check")
        batch_op.drop_constraint("ck_order_items_unit_price_non_negative", type_="check")
        batch_op.alter_column(
            "unit_price",
            existing_type=sa.Numeric(precision=14, scale=4),
            type_=sa.NUMERIC(precision=14, scale=2),
            nullable=True,
        )
        batch_op.drop_column("unit_price_net")
        batch_op.drop_column("discount_percent")

    with op.batch_alter_table("products", schema=None) as batch_op:
        batch_op.drop_constraint(
            "ck_products_last_purchase_price_non_negative", type_="check"
        )
        batch_op.drop_column("last_purchase_price")
