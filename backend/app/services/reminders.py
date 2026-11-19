"""Payment reminders (dunning).

Customers with overdue invoices, each at a reminder level set by how late the
oldest invoice is: a friendly nudge, a firm reminder, then a final notice. The
message lists the overdue invoices. Sending is done by the user (WhatsApp link
or a call); marking it sent logs it and plans a follow-up to check payment.
Modelled on Business Central reminder terms and Odoo follow-up levels.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import NotFoundError, ValidationError
from ..models import AuditEvent, Customer, User
from . import finance, integration_settings as settings_service

LEVELS = [
    {"level": 1, "name": "Friendly reminder", "from_days": 1, "follow_up_days": 3},
    {"level": 2, "name": "Firm reminder", "from_days": 16, "follow_up_days": 3},
    {"level": 3, "name": "Final notice", "from_days": 46, "follow_up_days": 2},
]


def _level(days: int) -> Dict[str, Any]:
    chosen = LEVELS[0]
    for level in LEVELS:
        if days >= level["from_days"]:
            chosen = level
    return chosen


def _money(value: float) -> str:
    return "Rs {:,.2f}".format(value)


def _message(level: int, name: str, seller: str, docs: List[Dict[str, Any]], total: float) -> str:
    lines = "\n".join("- {} ({}) {} due {}, {} days late".format(d["number"], d["order_number"], _money(d["open"]), d["due_date"].strftime("%d %b"), d["days_overdue"]) for d in docs[:8])
    sign = "\n\nThank you,\n{}".format(seller) if seller else "\n\nThank you."
    if level == 1:
        head = "Hello {}, a friendly reminder that {} is now due on these invoices:".format(name, _money(total))
        tail = "If it is already paid, please ignore this message."
    elif level == 2:
        head = "Hello {}, our records show {} overdue on these invoices:".format(name, _money(total))
        tail = "Please arrange the payment this week, or let us know when we can expect it."
    else:
        head = "Hello {}, this is a final notice: {} remains unpaid on these invoices:".format(name, _money(total))
        tail = "Please pay within 2 days. New orders will be held until the account is settled."
    return "{}\n{}\n\n{}{}".format(head, lines, tail, sign)


def due(session: Session) -> Dict[str, Any]:
    """Every customer who should get a reminder now, most overdue first."""
    receivables = finance.receivables(session)
    seller = settings_service.get(session, settings_service.TALLY).config.get("seller_name") or ""
    by_party: Dict[uuid.UUID, List[Dict[str, Any]]] = {}
    for doc in receivables["overdue"]:
        by_party.setdefault(doc["party_id"], []).append(doc)
    last = {
        row[0]: (row[1], row[2])
        for row in session.execute(
            select(AuditEvent.entity_id, func.max(AuditEvent.at), func.count(AuditEvent.id))
            .where(AuditEvent.action == "payment_reminder").group_by(AuditEvent.entity_id)
        ).all()
    }
    customers = {c.id: c for c in session.execute(select(Customer).where(Customer.id.in_(list(by_party)))).scalars()} if by_party else {}
    rows = []
    for party_id, docs in by_party.items():
        customer = customers.get(party_id)
        if customer is None:
            continue
        docs.sort(key=lambda d: -d["days_overdue"])
        oldest = docs[0]["days_overdue"]
        total = round(sum(float(d["open"]) for d in docs), 2)
        level = _level(oldest)
        reminded = last.get(str(party_id))
        rows.append({
            "customer_id": party_id, "name": customer.name, "phone": customer.phone,
            "overdue": total, "invoices": len(docs), "oldest_days": oldest,
            "level": level["level"], "level_name": level["name"],
            "last_reminded": reminded[0] if reminded else None, "reminders_sent": reminded[1] if reminded else 0,
            "message": _message(level["level"], customer.name, seller, [dict(d, open=float(d["open"])) for d in docs], total),
        })
    rows.sort(key=lambda r: (-r["level"], -r["overdue"]))
    return {"customers": rows, "total_overdue": round(sum(r["overdue"] for r in rows), 2),
            "levels": [{"level": l["level"], "name": l["name"], "from_days": l["from_days"]} for l in LEVELS]}


def mark_sent(session: Session, customer_id: uuid.UUID, user: Optional[User], channel: str = "whatsapp") -> Dict[str, Any]:
    """Log that a reminder went out and plan a follow-up to check payment."""
    from . import controls, tasks

    if channel not in ("whatsapp", "call", "email", "visit"):
        raise ValidationError("Channel must be whatsapp, call, email or visit.")
    row = next((r for r in due(session)["customers"] if r["customer_id"] == customer_id), None)
    if row is None:
        if session.get(Customer, customer_id) is None:
            raise NotFoundError("Customer not found.")
        raise ValidationError("This customer has nothing overdue.")
    level = next(l for l in LEVELS if l["level"] == row["level"])
    controls.log(session, user, "payment_reminder", "customer", str(customer_id),
                 "{} sent to {} by {}: {:,.2f} overdue".format(row["level_name"], row["name"], channel, row["overdue"]),
                 {"level": row["level"], "channel": channel, "overdue": row["overdue"]})
    session.commit()
    task = tasks.create_task(
        session, "Check payment from {} ({})".format(row["name"], row["level_name"].lower()),
        notes="{:,.2f} overdue on {} invoice(s), oldest {} days.".format(row["overdue"], row["invoices"], row["oldest_days"]),
        due_date=(finance._today() + timedelta(days=level["follow_up_days"])),
        priority="HIGH" if row["level"] >= 2 else "NORMAL", created_by_id=user.id if user else None,
        source="reminder", customer_id=customer_id,
    )
    return {"logged": True, "follow_up_task_id": task.id, "follow_up_due": task.due_date}
