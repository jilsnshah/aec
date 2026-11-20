"""Audiences: who a campaign is for, built from what the ERP already knows.

A definition combines, all of which must hold:
- ``group_ids``: members of any of these customer groups;
- ``rules`` / ``match``: the same figures customer groups use (spend, orders,
  days since last order, segment, city, overdue...);
- ``products`` / ``categories``: bought (or not bought) these, optionally
  within N days;
- ``occasion``: birthday or anniversary within N days;
- ``open_enquiry``: has an open enquiry;
- ``only``: limited to these customers (used by automations that pick people);
then ``include`` adds people by hand and ``exclude`` keeps people out.
An empty definition means every active customer.

Consent is not part of the audience: the executor checks it per channel, so
the preview shows how many of the audience can actually be reached.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import begin_write
from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import (
    Customer, CustomerEnquiry, CustomerGroupMember, EnquiryStatus, MarketingAudience, OrderStatus, Product, SalesOrder,
    SalesOrderItem,
)
from . import groups, marketing_policy

OCCASIONS = ("birthday", "anniversary")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid_list(values: Any, what: str) -> List[str]:
    out = []
    for v in values or []:
        try:
            out.append(str(uuid.UUID(str(v))))
        except ValueError:
            raise ValidationError("Unknown {} '{}'.".format(what, v))
    return out


def clean(definition: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    d = dict(definition or {})
    out: Dict[str, Any] = {}
    if d.get("group_ids"):
        out["group_ids"] = _uuid_list(d["group_ids"], "group")
    if d.get("rules"):
        out["match"] = d.get("match") or "all"
        out["rules"] = groups._check_rules(d["rules"], out["match"])
    for key in ("products", "categories"):
        part = d.get(key) or {}
        values = part.get("ids" if key == "products" else "names") or []
        if values:
            mode = part.get("mode") or "bought"
            if mode not in ("bought", "not_bought"):
                raise ValidationError("Choose bought or not bought.")
            within = part.get("within_days")
            entry: Dict[str, Any] = {"mode": mode, "within_days": int(within) if within not in (None, "") else None}
            if key == "products":
                entry["ids"] = _uuid_list(values, "product")
            else:
                entry["names"] = [str(v).strip() for v in values if str(v).strip()]
            out[key] = entry
    occ = d.get("occasion") or {}
    if occ.get("kind"):
        if occ["kind"] not in OCCASIONS:
            raise ValidationError("Occasion must be birthday or anniversary.")
        out["occasion"] = {"kind": occ["kind"], "within_days": max(0, min(int(occ.get("within_days") or 7), 60))}
    if d.get("open_enquiry"):
        out["open_enquiry"] = True
    if d.get("only"):
        out["only"] = _uuid_list(d["only"], "customer")
    if d.get("include"):
        out["include"] = _uuid_list(d["include"], "customer")
    if d.get("exclude"):
        out["exclude"] = _uuid_list(d["exclude"], "customer")
    return out


def _bought(session: Session, part: Dict[str, Any], by: str) -> Set[uuid.UUID]:
    stmt = (select(SalesOrder.customer_id).join(SalesOrderItem, SalesOrderItem.order_id == SalesOrder.id)
            .where(SalesOrder.status != OrderStatus.CANCELLED))
    if by == "products":
        stmt = stmt.where(SalesOrderItem.product_id.in_([uuid.UUID(i) for i in part["ids"]]))
    else:
        stmt = stmt.join(Product, Product.id == SalesOrderItem.product_id).where(Product.category.in_(part["names"]))
    if part.get("within_days"):
        stmt = stmt.where(SalesOrder.created_at >= _now() - timedelta(days=part["within_days"]))
    return set(session.execute(stmt.distinct()).scalars().all())


def _days_to(day: Optional[date], today: date) -> Optional[int]:
    if day is None:
        return None
    try:
        this_year = day.replace(year=today.year)
    except ValueError:  # 29 Feb
        this_year = date(today.year, 3, 1)
    if this_year < today:
        try:
            this_year = day.replace(year=today.year + 1)
        except ValueError:
            this_year = date(today.year + 1, 3, 1)
    return (this_year - today).days


def resolve(session: Session, definition: Optional[Dict[str, Any]]) -> List[uuid.UUID]:
    """The customers in an audience right now."""
    d = clean(definition)
    active = set(session.execute(select(Customer.id).where(Customer.is_active.is_(True))).scalars().all())
    people = set(active)
    if d.get("only"):
        people &= {uuid.UUID(i) for i in d["only"]}
    if d.get("group_ids"):
        people &= set(session.execute(select(CustomerGroupMember.customer_id).where(
            CustomerGroupMember.group_id.in_([uuid.UUID(g) for g in d["group_ids"]]))).scalars().all())
    if d.get("rules"):
        figures = groups.metrics(session, people)
        people &= set(groups.matching(figures, d["rules"], d["match"]))
    for key in ("products", "categories"):
        if d.get(key):
            hit = _bought(session, d[key], key)
            people = (people & hit) if d[key]["mode"] == "bought" else (people - hit)
    if d.get("occasion"):
        field = Customer.birthday if d["occasion"]["kind"] == "birthday" else Customer.anniversary
        today = _now().date()
        rows = session.execute(select(Customer.id, field).where(field.is_not(None), Customer.id.in_(people or [uuid.uuid4()]))).all()
        people = {cid for cid, day in rows if (_days_to(day, today) is not None and _days_to(day, today) <= d["occasion"]["within_days"])}
    if d.get("open_enquiry"):
        people &= set(session.execute(select(CustomerEnquiry.customer_id).where(
            CustomerEnquiry.status == EnquiryStatus.OPEN, CustomerEnquiry.customer_id.is_not(None))).scalars().all())
    people |= {uuid.UUID(i) for i in d.get("include", [])} & active
    people -= {uuid.UUID(i) for i in d.get("exclude", [])}
    return sorted(people, key=str)


def preview(session: Session, definition: Optional[Dict[str, Any]], channels: Optional[List[str]] = None, limit: int = 50) -> Dict[str, Any]:
    """How many people, how many each channel can reach and why not, and a sample."""
    ids = resolve(session, definition)
    reach: Dict[str, Any] = {}
    for channel in channels or ["whatsapp"]:
        if channel not in marketing_policy.CHANNELS:
            continue
        reasons = marketing_policy.eligibility(session, channel, ids)
        blocked: Dict[str, int] = {}
        for why in reasons.values():
            if why:
                blocked[why] = blocked.get(why, 0) + 1
        reach[channel] = {"reachable": sum(1 for v in reasons.values() if v is None), "blocked": blocked}
    sample = []
    if ids:
        names = {c.id: c for c in session.execute(select(Customer).where(Customer.id.in_(ids[:limit]))).scalars()}
        figures = groups.metrics(session, ids[:limit])
        consent = marketing_policy.opted_in(session, "whatsapp", ids[:limit])
        for cid in ids[:limit]:
            c, f = names.get(cid), figures.get(cid, {})
            if c is None:
                continue
            sample.append({"customer_id": cid, "name": c.name, "phone": c.phone, "segment": f.get("segment"),
                           "spend_12m": f.get("spend_12m"), "days_since_last_order": f.get("days_since_last_order"),
                           "whatsapp_consent": cid in consent})
    return {"count": len(ids), "reach": reach, "sample": sample}


def describe(session: Session, definition: Optional[Dict[str, Any]]) -> str:
    """The audience in words, for people and for the agents."""
    from ..models import CustomerGroup

    d = clean(definition)
    parts: List[str] = []
    if d.get("group_ids"):
        names = session.execute(select(CustomerGroup.name).where(CustomerGroup.id.in_([uuid.UUID(g) for g in d["group_ids"]]))).scalars().all()
        parts.append("in " + " or ".join(names))
    for rule in d.get("rules", []):
        label = groups.FIELD_KEYS[rule["field"]]["label"].lower()
        parts.append("{} {} {}".format(label, rule["op"], rule["value"]))
    if d.get("products"):
        names = session.execute(select(Product.name).where(Product.id.in_([uuid.UUID(i) for i in d["products"]["ids"]]))).scalars().all()
        within = " in the last {} days".format(d["products"]["within_days"]) if d["products"].get("within_days") else ""
        parts.append(("bought " if d["products"]["mode"] == "bought" else "never bought ") + ", ".join(names) + within)
    if d.get("categories"):
        within = " in the last {} days".format(d["categories"]["within_days"]) if d["categories"].get("within_days") else ""
        parts.append(("bought " if d["categories"]["mode"] == "bought" else "never bought ") + ", ".join(d["categories"]["names"]) + within)
    if d.get("occasion"):
        parts.append("{} in the next {} days".format(d["occasion"]["kind"], d["occasion"]["within_days"]))
    if d.get("open_enquiry"):
        parts.append("with an open enquiry")
    if d.get("only"):
        parts.insert(0, "{} chosen customer{}".format(len(d["only"]), "s" if len(d["only"]) != 1 else ""))
    text = "Customers: " + "; ".join(parts) if parts else "All active customers"
    if d.get("include"):
        text += ", plus {} added by hand".format(len(d["include"]))
    if d.get("exclude"):
        text += ", minus {} kept out".format(len(d["exclude"]))
    return text


# ---------------------------------------------------------------------------
# Saved audiences
# ---------------------------------------------------------------------------


def view(session: Session, row: MarketingAudience) -> Dict[str, Any]:
    return {"id": row.id, "name": row.name, "description": row.description, "definition": row.definition or {},
            "summary": describe(session, row.definition), "is_active": row.is_active, "last_count": row.last_count,
            "created_at": row.created_at, "updated_at": row.updated_at}


def list_all(session: Session) -> List[Dict[str, Any]]:
    rows = session.execute(select(MarketingAudience).order_by(MarketingAudience.name)).scalars().all()
    return [view(session, r) for r in rows]


def get(session: Session, audience_id: uuid.UUID) -> MarketingAudience:
    row = session.get(MarketingAudience, audience_id)
    if row is None:
        raise NotFoundError("Audience not found.")
    return row


def save(session: Session, data: Dict[str, Any], audience_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValidationError("Give the audience a name.")
    definition = clean(data.get("definition"))
    try:
        begin_write(session)
        row = get(session, audience_id) if audience_id else MarketingAudience(name=name)
        clash = session.execute(select(MarketingAudience.id).where(MarketingAudience.name == name)).scalar_one_or_none()
        if clash is not None and clash != row.id:
            raise ConflictError("An audience called {} already exists.".format(name))
        row.name, row.description, row.definition = name, (data.get("description") or "").strip() or None, definition
        if "is_active" in data:
            row.is_active = bool(data["is_active"])
        if audience_id is None:
            session.add(row)
        session.flush()
        row.last_count = len(resolve(session, definition))
        session.commit()
    except Exception:
        session.rollback()
        raise
    return view(session, row)


def delete(session: Session, audience_id: uuid.UUID) -> None:
    row = get(session, audience_id)
    session.delete(row)
    session.commit()
