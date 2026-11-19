"""price lists become customer groups

Price lists are no longer shown on their own: a group carries its members'
prices. Every shared price list becomes (or joins) a group, and customers
assigned to a list directly become members of that group by hand, so nobody's
prices change.

Revision ID: 5b7e2c1d9a40
Revises: 483188d8000b
Create Date: 2026-11-20 05:10:00
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5b7e2c1d9a40'
down_revision: Union[str, None] = '483188d8000b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _unique_name(conn, name: str) -> str:
    candidate, n = name[:80], 2
    while conn.execute(sa.text("SELECT 1 FROM customer_groups WHERE lower(name) = lower(:n)"), {"n": candidate}).first():
        suffix = " ({})".format(n)
        candidate, n = name[: 80 - len(suffix)] + suffix, n + 1
    return candidate


def _clone_list(conn, list_id, label: str):
    new_id = uuid.uuid4()
    row = conn.execute(sa.text("SELECT discount_percent, is_active FROM price_lists WHERE id = :id"), {"id": list_id}).first()
    conn.execute(
        sa.text("INSERT INTO price_lists (id, name, discount_percent, is_active, created_at, updated_at) VALUES (:id, :name, :d, :a, now(), now())"),
        {"id": new_id, "name": "Group prices · {} · {}".format(label[:40], str(new_id)[:8]), "d": row.discount_percent, "a": row.is_active},
    )
    conn.execute(
        sa.text(
            "INSERT INTO price_list_items (id, price_list_id, product_id, min_quantity, price, discount_percent) "
            "SELECT gen_random_uuid(), :new, product_id, min_quantity, price, discount_percent FROM price_list_items WHERE price_list_id = :old"
        ),
        {"new": new_id, "old": list_id},
    )
    return new_id


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    lists = conn.execute(sa.text("SELECT id, name, is_active FROM price_lists WHERE customer_id IS NULL ORDER BY name")).all()
    for plist in lists:
        groups = conn.execute(sa.text("SELECT id, name FROM customer_groups WHERE price_list_id = :id ORDER BY name"), {"id": plist.id}).all()
        customers = [r.id for r in conn.execute(sa.text("SELECT id FROM customers WHERE price_list_id = :id"), {"id": plist.id})]
        if groups:
            target = groups[0].id
            # Each further group gets its own copy, so editing one group's prices never changes another's.
            for extra in groups[1:]:
                conn.execute(sa.text("UPDATE customer_groups SET price_list_id = :l WHERE id = :g"), {"l": _clone_list(conn, plist.id, extra.name), "g": extra.id})
        else:
            target = uuid.uuid4()
            conn.execute(
                sa.text(
                    "INSERT INTO customer_groups (id, name, description, rules, match, price_list_id, is_active, member_count, last_computed_at, created_at, updated_at) "
                    "VALUES (:id, :name, :d, CAST(:rules AS JSON), 'all', :l, :a, 0, :now, :now, :now)"
                ),
                {"id": target, "name": _unique_name(conn, plist.name), "d": "Made from the price list '{}'.".format(plist.name), "rules": json.dumps([]),
                 "l": plist.id, "a": plist.is_active, "now": now},
            )
        for customer_id in customers:
            existing = conn.execute(sa.text("SELECT source FROM customer_group_members WHERE group_id = :g AND customer_id = :c"), {"g": target, "c": customer_id}).first()
            if existing is None:
                conn.execute(
                    sa.text("INSERT INTO customer_group_members (id, group_id, customer_id, source, added_at) VALUES (:id, :g, :c, 'manual', :now)"),
                    {"id": uuid.uuid4(), "g": target, "c": customer_id, "now": now},
                )
            elif existing.source == "excluded":
                conn.execute(sa.text("UPDATE customer_group_members SET source = 'manual' WHERE group_id = :g AND customer_id = :c"), {"g": target, "c": customer_id})
        conn.execute(
            sa.text("UPDATE customer_groups SET member_count = (SELECT count(*) FROM customer_group_members WHERE group_id = :g AND source <> 'excluded') WHERE id = :g"),
            {"g": target},
        )
    conn.execute(sa.text("UPDATE customers SET price_list_id = NULL WHERE price_list_id IS NOT NULL"))


def downgrade() -> None:
    # Data only: the groups made here stay and keep pricing their members.
    pass
