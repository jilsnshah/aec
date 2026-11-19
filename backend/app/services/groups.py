"""Smart customer groups.

A group is filled by rules over figures the business already records -- how
often a customer orders, how much they spend, how long they have bought from
us, how they pay, where their sites are -- plus customers added or kept out
by hand. Each group can carry a price list; prices for a customer are the best
of everything that applies to them (see pricelists.resolve).

Membership is recalculated on demand and once a day.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..database import begin_write
from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import Address, Customer, CustomerGroup, CustomerGroupMember, OrderStatus, PriceList, SalesOrder, User

#: Every figure a rule can test, with how it is shown.
FIELDS: List[Dict[str, Any]] = [
    {"key": "orders_12m", "label": "Orders in the last 12 months", "unit": "orders", "type": "number"},
    {"key": "orders_90d", "label": "Orders in the last 90 days", "unit": "orders", "type": "number"},
    {"key": "orders_total", "label": "Orders ever", "unit": "orders", "type": "number"},
    {"key": "spend_12m", "label": "Spend in the last 12 months", "unit": "₹", "type": "money"},
    {"key": "spend_total", "label": "Spend ever", "unit": "₹", "type": "money"},
    {"key": "average_order", "label": "Average order value", "unit": "₹", "type": "money"},
    {"key": "years_with_us", "label": "Years buying from us", "unit": "years", "type": "number"},
    {"key": "days_since_last_order", "label": "Days since last order", "unit": "days", "type": "number"},
    {"key": "days_between_orders", "label": "Average days between orders", "unit": "days", "type": "number"},
    {"key": "owed", "label": "Amount owed now", "unit": "₹", "type": "money"},
    {"key": "overdue", "label": "Amount overdue", "unit": "₹", "type": "money"},
    {"key": "oldest_overdue_days", "label": "Days the oldest invoice is late", "unit": "days", "type": "number"},
    {"key": "segment", "label": "Segment", "type": "choice", "choices": ["champion", "loyal", "at_risk", "dormant", "new", "occasional", "prospect"]},
    {"key": "city", "label": "City (of an address or site)", "type": "text"},
    {"key": "state", "label": "State (of an address or site)", "type": "text"},
]
FIELD_KEYS = {f["key"]: f for f in FIELDS}
OPS = {">=", "<=", ">", "<", "=", "!="}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def metrics(session: Session, customer_ids: Optional[Iterable[uuid.UUID]] = None) -> Dict[uuid.UUID, Dict[str, Any]]:
    """The figures rules test, for every active customer (or the ones given)."""
    from . import finance, insights

    ids = list(customer_ids) if customer_ids is not None else None
    stmt = select(Customer).where(Customer.is_active.is_(True))
    if ids is not None:
        stmt = stmt.where(Customer.id.in_(ids))
    customers = session.execute(stmt).scalars().all()
    now = _now()
    year_ago, quarter_ago = now - timedelta(days=365), now - timedelta(days=90)
    orders: Dict[uuid.UUID, List] = defaultdict(list)
    for customer_id, created, total in session.execute(
        select(SalesOrder.customer_id, SalesOrder.created_at, SalesOrder.total_amount).where(SalesOrder.status != OrderStatus.CANCELLED).order_by(SalesOrder.created_at)
    ).all():
        orders[customer_id].append((created, float(total or 0)))
    owed = {row["party_id"]: row for row in finance.receivables(session)["parties"]}
    oldest: Dict[uuid.UUID, int] = defaultdict(int)
    for doc in finance.receivables(session)["overdue"]:
        oldest[doc["party_id"]] = max(oldest[doc["party_id"]], doc["days_overdue"])
    segments = {row["customer_id"]: row["segment"] for row in insights.customer_segments(session)["customers"]}
    places: Dict[uuid.UUID, Dict[str, set]] = defaultdict(lambda: {"city": set(), "state": set()})
    for customer_id, city, state in session.execute(
        select(Address.customer_id, Address.city, Address.state).where(Address.customer_id.is_not(None), Address.is_active.is_(True))
    ).all():
        if city:
            places[customer_id]["city"].add(city.strip().lower())
        if state:
            places[customer_id]["state"].add(state.strip().lower())
    out: Dict[uuid.UUID, Dict[str, Any]] = {}
    for c in customers:
        history = orders.get(c.id, [])
        dates = [d for d, _ in history]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        first = dates[0] if dates else c.created_at
        out[c.id] = {
            "orders_12m": sum(1 for d, _ in history if d >= year_ago),
            "orders_90d": sum(1 for d, _ in history if d >= quarter_ago),
            "orders_total": len(history),
            "spend_12m": round(sum(v for d, v in history if d >= year_ago), 2),
            "spend_total": round(sum(v for _, v in history), 2),
            "average_order": round(sum(v for _, v in history) / len(history), 2) if history else 0.0,
            "years_with_us": round((now - first).days / 365.25, 2) if first else 0.0,
            "days_since_last_order": (now - dates[-1]).days if dates else None,
            "days_between_orders": round(sum(gaps) / len(gaps), 1) if gaps else None,
            "owed": float(owed.get(c.id, {}).get("open", 0.0)),
            "overdue": float(owed.get(c.id, {}).get("overdue", 0.0)),
            "oldest_overdue_days": oldest.get(c.id, 0),
            "segment": segments.get(c.id, "prospect"),
            "city": places[c.id]["city"],
            "state": places[c.id]["state"],
        }
    return out


def _check_rules(rules: Any, match: str) -> List[Dict[str, Any]]:
    if match not in ("all", "any"):
        raise ValidationError("Match must be all or any.")
    if not isinstance(rules, list):
        raise ValidationError("Rules must be a list.")
    clean = []
    for rule in rules:
        field = FIELD_KEYS.get((rule or {}).get("field"))
        if field is None:
            raise ValidationError("Unknown rule field '{}'.".format((rule or {}).get("field")))
        op = rule.get("op")
        if op not in OPS:
            raise ValidationError("Unknown comparison '{}'.".format(op))
        value = rule.get("value")
        if field["type"] in ("number", "money"):
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValidationError("'{}' needs a number.".format(field["label"]))
        else:
            if op not in ("=", "!="):
                raise ValidationError("'{}' can only be equal or not equal.".format(field["label"]))
            value = str(value or "").strip().lower()
            if not value:
                raise ValidationError("'{}' needs a value.".format(field["label"]))
        clean.append({"field": field["key"], "op": op, "value": value})
    return clean


def _test(rule: Dict[str, Any], figures: Dict[str, Any]) -> bool:
    actual = figures.get(rule["field"])
    op, value = rule["op"], rule["value"]
    if isinstance(actual, set):  # city/state: any of the customer's places
        hit = value in actual
        return hit if op == "=" else not hit
    if actual is None:
        return False
    if isinstance(actual, str):
        return (actual == value) if op == "=" else (actual != value)
    return {">=": actual >= value, "<=": actual <= value, ">": actual > value, "<": actual < value,
            "=": abs(actual - value) < 1e-9, "!=": abs(actual - value) >= 1e-9}[op]


def matching(figures: Dict[uuid.UUID, Dict[str, Any]], rules: List[Dict[str, Any]], match: str) -> List[uuid.UUID]:
    if not rules:
        return []
    out = []
    for customer_id, f in figures.items():
        results = [_test(rule, f) for rule in rules]
        if (all(results) if match == "all" else any(results)):
            out.append(customer_id)
    return out


def preview(session: Session, rules: Any, match: str = "all") -> Dict[str, Any]:
    """Who a set of rules would put in a group, with their figures."""
    clean = _check_rules(rules, match)
    figures = metrics(session)
    ids = matching(figures, clean, match)
    names = dict(session.execute(select(Customer.id, Customer.name).where(Customer.id.in_(ids))).all()) if ids else {}
    rows = [{"customer_id": cid, "name": names.get(cid), **{k: v for k, v in figures[cid].items() if k not in ("city", "state")}} for cid in ids]
    rows.sort(key=lambda r: -r["spend_12m"])
    return {"count": len(rows), "of": len(figures), "customers": rows}


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


def view(session: Session, group: CustomerGroup, with_members: bool = False) -> Dict[str, Any]:
    out = {
        "id": group.id, "name": group.name, "description": group.description, "rules": group.rules or [], "match": group.match,
        "price_list_id": group.price_list_id, "price_list_name": group.price_list.name if group.price_list else None,
        "price_list_discount": float(group.price_list.discount_percent) if group.price_list else None,
        "is_active": group.is_active, "member_count": group.member_count, "last_computed_at": group.last_computed_at,
    }
    if with_members:
        rows = session.execute(
            select(CustomerGroupMember, Customer.name).join(Customer, CustomerGroupMember.customer_id == Customer.id)
            .where(CustomerGroupMember.group_id == group.id).order_by(Customer.name)
        ).all()
        out["members"] = [{"customer_id": m.customer_id, "name": name, "source": m.source, "added_at": m.added_at} for m, name in rows]
    return out


def _get(session: Session, group_id: uuid.UUID) -> CustomerGroup:
    group = session.get(CustomerGroup, group_id)
    if group is None:
        raise NotFoundError("Group not found.")
    return group


def list_groups(session: Session) -> List[Dict[str, Any]]:
    return [view(session, g) for g in session.execute(select(CustomerGroup).order_by(CustomerGroup.name)).scalars()]


def get(session: Session, group_id: uuid.UUID) -> Dict[str, Any]:
    return view(session, _get(session, group_id), with_members=True)


def save(session: Session, data: Dict[str, Any], group_id: Optional[uuid.UUID] = None, user: Optional[User] = None) -> Dict[str, Any]:
    begin_write(session)
    try:
        group = _get(session, group_id) if group_id else CustomerGroup()
        if "name" in data or group_id is None:
            name = (data.get("name") or "").strip()
            if not name:
                raise ValidationError("Give the group a name.")
            clash = session.execute(select(CustomerGroup).where(func.lower(CustomerGroup.name) == name.lower())).scalar_one_or_none()
            if clash is not None and clash.id != group.id:
                raise ConflictError("A group called '{}' already exists.".format(name))
            group.name = name
        if "description" in data:
            group.description = (data.get("description") or "").strip() or None
        if "rules" in data or "match" in data:
            match = data.get("match", group.match or "all")
            group.rules = _check_rules(data.get("rules", group.rules or []), match)
            group.match = match
        if "price_list_id" in data:
            list_id = data.get("price_list_id")
            if list_id:
                price_list = session.get(PriceList, uuid.UUID(str(list_id)))
                if price_list is None or price_list.customer_id is not None:
                    raise ValidationError("Choose a shared price list.")
                group.price_list_id = price_list.id
            else:
                group.price_list_id = None
        if data.get("is_active") is not None:
            group.is_active = bool(data["is_active"])
        session.add(group)
        session.flush()
        _recompute(session, group)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get(session, group.id)


def _recompute(session: Session, group: CustomerGroup, figures: Optional[Dict[uuid.UUID, Dict[str, Any]]] = None) -> None:
    """Refresh the rule-made members; members added or kept out by hand stay."""
    figures = figures if figures is not None else metrics(session)
    wanted = set(matching(figures, group.rules or [], group.match or "all")) if group.is_active else set()
    existing = {m.customer_id: m for m in session.execute(select(CustomerGroupMember).where(CustomerGroupMember.group_id == group.id)).scalars()}
    for customer_id, member in existing.items():
        if member.source == "rule" and customer_id not in wanted:
            session.delete(member)
    for customer_id in wanted:
        if customer_id not in existing:
            session.add(CustomerGroupMember(group_id=group.id, customer_id=customer_id, source="rule"))
    session.flush()
    group.member_count = session.execute(
        select(func.count(CustomerGroupMember.id)).where(CustomerGroupMember.group_id == group.id, CustomerGroupMember.source != "excluded")
    ).scalar_one()
    group.last_computed_at = _now()


def recompute(session: Session, group_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    begin_write(session)
    try:
        figures = metrics(session)
        groups = [_get(session, group_id)] if group_id else session.execute(select(CustomerGroup)).scalars().all()
        for group in groups:
            _recompute(session, group, figures)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {"groups": len(groups)}


def set_member(session: Session, group_id: uuid.UUID, customer_id: uuid.UUID, source: Optional[str]) -> Dict[str, Any]:
    """Add a customer by hand (manual), keep one out (excluded), or undo either (None)."""
    begin_write(session)
    try:
        group = _get(session, group_id)
        if session.get(Customer, customer_id) is None:
            raise NotFoundError("Customer not found.")
        member = session.execute(select(CustomerGroupMember).where(CustomerGroupMember.group_id == group_id, CustomerGroupMember.customer_id == customer_id)).scalar_one_or_none()
        if source not in (None, "manual", "excluded"):
            raise ValidationError("Choose manual, excluded or nothing.")
        if source is None:
            if member is not None:
                session.delete(member)
        elif member is None:
            session.add(CustomerGroupMember(group_id=group_id, customer_id=customer_id, source=source))
        else:
            member.source = source
        session.flush()
        _recompute(session, group)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get(session, group_id)


def delete_group(session: Session, group_id: uuid.UUID) -> None:
    begin_write(session)
    group = _get(session, group_id)
    session.execute(delete(CustomerGroupMember).where(CustomerGroupMember.group_id == group_id))
    session.delete(group)
    session.commit()


def groups_of(session: Session, customer_id: uuid.UUID) -> List[CustomerGroup]:
    """Active groups a customer belongs to (not kept out)."""
    return session.execute(
        select(CustomerGroup).join(CustomerGroupMember, CustomerGroupMember.group_id == CustomerGroup.id)
        .where(CustomerGroupMember.customer_id == customer_id, CustomerGroupMember.source != "excluded", CustomerGroup.is_active.is_(True))
        .order_by(CustomerGroup.name)
    ).scalars().all()


def recompute_if_due() -> int:
    """Background job: recalculate every group once a day."""
    from ..database import SessionLocal

    session = SessionLocal()
    try:
        stale = session.execute(
            select(func.count(CustomerGroup.id)).where(
                (CustomerGroup.last_computed_at.is_(None)) | (CustomerGroup.last_computed_at < _now() - timedelta(hours=24))
            )
        ).scalar_one()
        if not stale:
            return 0
        recompute(session)
        return stale
    finally:
        session.close()


