"""purchase assignments: settle waiting orders when a purchase is confirmed

Revision ID: 7a0d1333b75e
Revises: 3928d051146b
Create Date: 2026-10-29 18:41:57.441834
"""
from typing import Sequence, Union

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from alembic import op
import sqlalchemy as sa


revision: str = '7a0d1333b75e'
down_revision: Union[str, None] = '3928d051146b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'sales_order_items',
        sa.Column('quantity_incoming', sa.Numeric(18, 3), nullable=False, server_default='0'),
    )
    op.create_check_constraint(
        'ck_order_items_incoming_non_negative', 'sales_order_items', 'quantity_incoming >= 0'
    )
    op.create_check_constraint(
        'ck_order_items_covered_within_ordered',
        'sales_order_items',
        'quantity_fulfilled + quantity_cancelled + quantity_reserved + quantity_incoming'
        ' <= quantity_ordered',
    )
    op.create_table('purchase_assignments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('purchase_order_item_id', sa.Uuid(), nullable=False),
    sa.Column('order_item_id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('quantity', sa.Numeric(18, 3), nullable=False),
    sa.Column('quantity_released', sa.Numeric(18, 3), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('quantity > 0', name='ck_assignments_quantity_positive'),
    sa.CheckConstraint('quantity_released >= 0 AND quantity_released <= quantity', name='ck_assignments_released_within_quantity'),
    sa.ForeignKeyConstraint(['order_item_id'], ['sales_order_items.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['purchase_order_item_id'], ['purchase_order_items.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_assignments_order_item', 'purchase_assignments', ['order_item_id'], unique=False)
    op.create_index('ix_assignments_po_item', 'purchase_assignments', ['purchase_order_item_id'], unique=False)
    op.create_index('ix_assignments_product', 'purchase_assignments', ['product_id'], unique=False)

    _settle_open_purchase_orders(op.get_bind())


def _settle_open_purchase_orders(connection) -> None:
    """Give purchase orders already placed the settlement they would get now.

    Oldest purchase order first, each line spread oldest sales order first over
    whatever is neither delivered, cancelled nor already in the warehouse.
    """
    po_lines = connection.execute(sa.text(
        """
        SELECT poi.id, poi.product_id, poi.quantity_ordered - poi.quantity_received AS due
        FROM purchase_order_items poi
        JOIN purchase_orders po ON po.id = poi.purchase_order_id
        WHERE po.status IN ('ORDERED', 'PARTIALLY_RECEIVED')
          AND poi.quantity_ordered > poi.quantity_received
        ORDER BY po.ordered_at NULLS LAST, po.po_number, poi.line_number
        """
    )).fetchall()
    uncovered = {}
    now = datetime.now(timezone.utc)
    for po_item_id, product_id, due in po_lines:
        if product_id not in uncovered:
            uncovered[product_id] = [
                [row[0], Decimal(row[1])]
                for row in connection.execute(sa.text(
                    """
                    SELECT soi.id,
                           soi.quantity_ordered - soi.quantity_fulfilled
                             - soi.quantity_cancelled - soi.quantity_reserved
                    FROM sales_order_items soi
                    JOIN sales_orders so ON so.id = soi.order_id
                    WHERE soi.product_id = :product AND so.status <> 'CANCELLED'
                      AND soi.quantity_ordered - soi.quantity_fulfilled
                          - soi.quantity_cancelled - soi.quantity_reserved > 0
                    ORDER BY so.created_at, so.order_number, soi.line_number, soi.id
                    """
                ), {"product": product_id}).fetchall()
            ]
        free = Decimal(due)
        for line in uncovered[product_id]:
            if free <= 0:
                break
            take = min(free, line[1])
            if take <= 0:
                continue
            connection.execute(sa.text(
                "INSERT INTO purchase_assignments (id, purchase_order_item_id, order_item_id, "
                "product_id, quantity, quantity_released, created_at) "
                "VALUES (:id, :po_item, :item, :product, :qty, 0, :now)"
            ), {"id": uuid.uuid4(), "po_item": po_item_id, "item": line[0],
                "product": product_id, "qty": take, "now": now})
            connection.execute(sa.text(
                "UPDATE sales_order_items SET quantity_incoming = quantity_incoming + :qty "
                "WHERE id = :item"
            ), {"qty": take, "item": line[0]})
            line[1] -= take
            free -= take


def downgrade() -> None:
    op.drop_index('ix_assignments_product', table_name='purchase_assignments')
    op.drop_index('ix_assignments_po_item', table_name='purchase_assignments')
    op.drop_index('ix_assignments_order_item', table_name='purchase_assignments')
    op.drop_table('purchase_assignments')
    op.drop_constraint('ck_order_items_covered_within_ordered', 'sales_order_items', type_='check')
    op.drop_constraint('ck_order_items_incoming_non_negative', 'sales_order_items', type_='check')
    op.drop_column('sales_order_items', 'quantity_incoming')
