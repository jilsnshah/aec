"""Business controls at order entry, and the audit log.

Before an order is placed the draft is checked (see records.check_order):
credit limit including undelivered orders, overdue invoices past a grace
period, discount above the allowed maximum, margin below the minimum, price
below cost. In "warn" mode the order goes through and the warnings come back;
in "block" mode it is held unless an admin overrides with a reason, and the
override is written to the audit log. Modelled on NetSuite's Warn / Enforce
holds, Zoho Books' Restrict / Warn and ERPNext's credit-controller role.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import HoldError
from ..models import AuditEvent, Customer, IntegrationSetting, Product, User
from . import integration_settings as settings_service
from . import records


def settings(session: Session) -> Dict[str, Any]:
    row = session.get(IntegrationSetting, settings_service.CONTROLS)
    base = dict(settings_service.DEFINITIONS[settings_service.CONTROLS]["config"])
    if row is not None:
        base.update(row.config or {})
    return base


def evaluate(session: Session, customer_id: Optional[uuid.UUID], items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """What the controls say about a draft order: holds (would block) and
    warnings (always reported)."""
    config = settings(session)
    lines = []
    for item in items:
        product = session.get(Product, uuid.UUID(str(item["product_id"])))
        if product is None:
            continue
        price = item.get("unit_price")
        lines.append({"product_id": str(product.id), "quantity_ordered": float(item.get("quantity_ordered") or 0),
                      "unit_price": float(price) if price not in (None, "") else float(product.mrp or 0),
                      "discount_percent": float(item.get("discount_percent") or 0)})
    check = records.check_order(session, customer_id, lines)
    holds: List[Dict[str, Any]] = []
    mode = config["credit_check"]
    credit = check.get("credit")
    if mode != "off" and credit:
        if credit["limit"] is not None and credit["exposure_after"] > credit["limit"]:
            holds.append({"kind": "credit_limit", "text": next(w["text"] for w in check["warnings"] if w["kind"] == "credit_limit")})
        if config["block_on_overdue"] and credit["overdue"] > 0:
            oldest = _oldest_overdue_days(session, customer_id)
            if oldest > int(config["overdue_grace_days"] or 0):
                holds.append({"kind": "overdue", "text": "Invoices are {} days overdue (₹{:,.2f}); the limit is {} days.".format(oldest, credit["overdue"], config["overdue_grace_days"])})
    for line_in, line in zip(lines, check["lines"]):
        maximum = float(config["max_discount_percent"] or 0)
        if maximum and line_in["discount_percent"] > maximum:
            holds.append({"kind": "discount", "text": "{}% discount on {} is above the {}% allowed.".format(line_in["discount_percent"], line["name"], maximum)})
        if config["block_below_cost"] and line["cost"] and line["net_price"] < line["cost"]:
            holds.append({"kind": "below_cost", "text": "{} is priced below its cost (₹{:,.2f} < ₹{:,.2f}).".format(line["name"], line["net_price"], line["cost"])})
        elif float(config["min_margin_percent"] or 0) and line["margin_percent"] is not None and line["margin_percent"] < float(config["min_margin_percent"]):
            holds.append({"kind": "margin", "text": "{} earns {}% margin, below the {}% minimum.".format(line["name"], line["margin_percent"], config["min_margin_percent"])})
    blocking = [h for h in holds if mode == "block" or h["kind"] in ("discount", "below_cost", "margin")]
    if mode != "block":
        blocking = [h for h in blocking if h["kind"] not in ("credit_limit", "overdue")]
    return {"mode": mode, "holds": blocking, "warnings": check["warnings"], "check": check}


def _oldest_overdue_days(session: Session, customer_id: uuid.UUID) -> int:
    from . import finance

    entries = finance.statement(session, "customer", customer_id)["entries"]
    return max([e.get("days_overdue", 0) for e in entries if e["kind"] == "invoice" and e.get("open", 0) > 0] or [0])


def enforce(session: Session, customer_id: Optional[uuid.UUID], items: List[Dict[str, Any]], user: Optional[User],
            override: bool = False, reason: Optional[str] = None, reference: str = "order") -> Dict[str, Any]:
    """Raise HoldError when a control blocks the order, unless an admin
    overrides it with a reason (logged)."""
    result = evaluate(session, customer_id, items)
    if not result["holds"]:
        return result
    texts = [h["text"] for h in result["holds"]]
    if not override:
        raise HoldError("This order needs approval: " + " ".join(texts),
                        {"holds": result["holds"], "can_override": bool(user and user.is_admin)})
    if not (user and user.is_admin):
        raise HoldError("Only an admin can approve an order on hold.", {"holds": result["holds"], "can_override": False})
    if not (reason or "").strip():
        raise HoldError("Give a reason for approving the order on hold.", {"holds": result["holds"], "can_override": True})
    customer = session.get(Customer, customer_id) if customer_id else None
    log(session, user, "control_override", "customer", str(customer_id) if customer_id else None,
        "Approved {} for {} despite: {} Reason: {}".format(reference, customer.name if customer else "?", " ".join(texts), reason.strip()),
        {"holds": result["holds"], "reason": reason.strip()})
    session.commit()
    return result


def log(session: Session, user: Optional[User], action: str, entity: str, entity_id: Optional[str], summary: str, data: Optional[Dict[str, Any]] = None) -> None:
    session.add(AuditEvent(user_id=user.id if user else None, username=user.username if user else None,
                           action=action, entity=entity, entity_id=entity_id, summary=summary, data=data))
    session.flush()


def audit_list(session: Session, limit: int = 100, action: Optional[str] = None, entity_id: Optional[str] = None) -> List[Dict[str, Any]]:
    stmt = select(AuditEvent).order_by(AuditEvent.at.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if entity_id:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    return [{"id": e.id, "at": e.at, "user": e.username, "action": e.action, "entity": e.entity, "entity_id": e.entity_id,
             "summary": e.summary, "data": e.data} for e in session.execute(stmt).scalars()]
