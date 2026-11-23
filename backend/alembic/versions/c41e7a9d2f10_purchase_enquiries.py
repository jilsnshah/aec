"""purchase enquiries: draft and to_choose states; PO links to its enquiry

Revision ID: c41e7a9d2f10
Revises: bbaab580d59a
Create Date: 2026-11-23 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c41e7a9d2f10'
down_revision: Union[str, None] = 'bbaab580d59a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('supplier_quote_requests') as batch:
        batch.drop_constraint('ck_rfq_status', type_='check')
        batch.create_check_constraint('ck_rfq_status', "status IN ('draft', 'open', 'to_choose', 'decided', 'ordered', 'cancelled')")
    with op.batch_alter_table('purchase_orders') as batch:
        batch.add_column(sa.Column('enquiry_id', sa.Uuid(), nullable=True))
        batch.create_foreign_key('fk_purchase_orders_enquiry_id', 'supplier_quote_requests', ['enquiry_id'], ['id'], ondelete='SET NULL')
        batch.create_index('ix_purchase_orders_enquiry_id', ['enquiry_id'])


def downgrade() -> None:
    with op.batch_alter_table('purchase_orders') as batch:
        batch.drop_index('ix_purchase_orders_enquiry_id')
        batch.drop_constraint('fk_purchase_orders_enquiry_id', type_='foreignkey')
        batch.drop_column('enquiry_id')
    op.execute("UPDATE supplier_quote_requests SET status = 'open' WHERE status IN ('draft', 'to_choose')")
    with op.batch_alter_table('supplier_quote_requests') as batch:
        batch.drop_constraint('ck_rfq_status', type_='check')
        batch.create_check_constraint('ck_rfq_status', "status IN ('open', 'decided', 'ordered', 'cancelled')")
