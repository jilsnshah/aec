"""The Collections and Customer care agents.

Collections: reminds customers of overdue bills on a schedule, by WhatsApp
(written by AI) or by a call, escalating to calls from a chosen reminder
level. On a call it records a promise to pay (and books a check on that
date) or a dispute (a task for a person).

Customer care: the after-sales check-in by call -- how did the delivery go,
a rating, and any complaint (a task for a person). The WhatsApp version
lives in triggers.run_after_sales; both save feedback through
``save_feedback``.

Calls are follow-ups (tasks) given to the phone AI with ``agent`` set, so they
share the scheduling, retries and reporting of every AI call, and show in
Follow-ups.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditEvent, Customer, CustomerDelivery, CustomerFeedback, Task, TaskStatus
from . import automation, triggers

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _open_agent_call(session: Session, customer_id: uuid.UUID, agent: str) -> bool:
    return session.execute(select(Task.id).where(Task.customer_id == customer_id, Task.agent == agent, Task.doer == "pai",
                                                 Task.status == TaskStatus.OPEN)).first() is not None


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


def _collections_brief(row: Dict[str, Any]) -> str:
    docs = "; ".join("{} (order {}) Rs {:,.2f}, {} days late".format(d["number"], d["order_number"], d["open"], d["days_overdue"]) for d in row["documents"][:6])
    tone = {1: "friendly", 2: "firm but polite", 3: "firm: this is the final reminder; new orders are held until it is settled"}.get(row["level"], "polite")
    return ("Payment reminder ({}). {} owes Rs {:,.2f} overdue on {} invoice(s): {}. Ask whether the payment has been made; if not, ask when it will be "
            "paid and how much. Record a promise with record_payment_promise, or a disagreement with record_dispute. Tone: {}. Never threaten; "
            "never offer a discount or new credit terms.").format(row["level_name"], row["name"], row["overdue"], row["invoices"], docs, tone)


def run_collections(session: Session, force: bool = False) -> Dict[str, Any]:
    """Remind customers with overdue bills, as the Payment reminders step says."""
    from . import agent_text, reminders, tasks

    data = automation.step(session, "sales.payment_reminders")
    if data.get("mode") == "off" and not force:
        return {"skipped": "off"}
    cfg = data["config"]
    if not force and not triggers.in_window(cfg):
        return {"skipped": "outside hours"}
    how = cfg.get("how") or "text"
    by_text = automation.allowed(data, "tai")
    by_phone = automation.allowed(data, "pai")
    if not (by_text or by_phone):
        return {"skipped": "no AI chosen for this step"}
    gap = timedelta(days=float(cfg.get("every_days") or 7))
    call_level = int(cfg.get("call_from_level") or 2)
    limit = int(cfg.get("per_run") or 20)
    texted = called = 0
    for row in reminders.due(session)["customers"]:
        if texted + called >= limit:
            break
        if row["overdue"] < float(cfg.get("min_overdue") or 0) or not row["phone"]:
            continue
        if row["last_reminded"] and _now() - row["last_reminded"] < gap:
            continue
        want_call = by_phone and (how == "call" or (how == "text_then_call" and row["level"] >= call_level and row["reminders_sent"] >= 1))
        if want_call:
            if _open_agent_call(session, row["customer_id"], "collections"):
                continue
            tasks.create_task(session, "Payment call: {} (Rs {:,.0f} overdue)".format(row["name"], row["overdue"]), kind="call", doer="pai",
                              agent="collections", due_at=_now(), instructions=_collections_brief(row), priority="HIGH" if row["level"] >= 2 else "NORMAL",
                              source="automation", customer_id=row["customer_id"])
            reminders.mark_sent(session, row["customer_id"], None, "call")
            triggers.event(session, "sales.payment_reminders", "call", "sent", "Collections agent will call {}".format(row["name"]),
                           party=("customer", row["customer_id"]))
            called += 1
        elif by_text and how in ("text", "text_then_call"):
            facts = {"customer": row["name"].split()[0], "level": row["level_name"], "overdue_total": "Rs {:,.2f}".format(row["overdue"]),
                     "invoices": [{"number": d["number"], "amount": "Rs {:,.2f}".format(d["open"]), "days_late": d["days_overdue"]} for d in row["documents"][:6]]}
            text = agent_text.write(session, "collections", "a {} payment reminder for overdue invoices; ask them to pay or say when they will".format(row["level_name"].lower()),
                                    facts, row["message"], must_keep=["{:,.2f}".format(row["overdue"])], max_chars=900)
            status, _ = triggers._send(session, data, row["phone"], None, text, customer_id=row["customer_id"])
            if status in ("sent", "held"):
                reminders.mark_sent(session, row["customer_id"], None, "whatsapp")
                texted += 1
            triggers.event(session, "sales.payment_reminders", "reminder", status, "{} to {}".format(row["level_name"], row["name"]),
                           party=("customer", row["customer_id"]))
    session.commit()
    return {"texted": texted, "called": called}


def record_payment_promise(session: Session, task_id: uuid.UUID, args: Dict[str, Any]) -> Dict[str, Any]:
    from . import controls, tasks

    task = session.get(Task, task_id)
    if task is None or task.customer_id is None:
        return {"error": "No customer on this call."}
    when = None
    try:
        when = date.fromisoformat(str(args.get("date") or ""))
    except ValueError:
        pass
    amount = args.get("amount")
    note = "Promised to pay{}{}{}".format(" Rs {:,.0f}".format(float(amount)) if amount not in (None, "") else "",
                                          " on {}".format(when.strftime("%d %b")) if when else "", ". " + str(args.get("note")) if args.get("note") else ".")
    controls.log(session, None, "payment_promise", "customer", str(task.customer_id), "{}: {}".format(task.customer.name, note),
                 {"date": when.isoformat() if when else None, "amount": amount})
    session.commit()
    tasks.create_task(session, "Check payment promised by {}".format(task.customer.name), notes=note,
                      due_date=when or (_now() + timedelta(days=3)).date(), priority="HIGH", source="automation", customer_id=task.customer_id)
    return {"ok": True, "say": "Thank them, repeat the date and amount, and say goodbye. Then call finish_followup with outcome done."}


def record_dispute(session: Session, task_id: uuid.UUID, reason: str) -> Dict[str, Any]:
    from . import tasks

    task = session.get(Task, task_id)
    if task is None or task.customer_id is None:
        return {"error": "No customer on this call."}
    tasks.create_task(session, "{} disputes an overdue bill".format(task.customer.name), notes=reason or "No details given.",
                      priority="HIGH", source="automation", customer_id=task.customer_id)
    return {"ok": True, "say": "Say someone from accounts will call them to sort it out. Then call finish_followup with outcome needs_person."}


# ---------------------------------------------------------------------------
# Customer care
# ---------------------------------------------------------------------------


def save_feedback(session: Session, customer: Customer, delivery_id: Optional[uuid.UUID], rating: Optional[int], comment: str,
                  complaint: bool, *, priority: str = "HIGH") -> CustomerFeedback:
    """Store a customer's feedback; a complaint becomes a task for a person."""
    from . import tasks

    delivery = session.get(CustomerDelivery, delivery_id) if delivery_id else None
    feedback = CustomerFeedback(customer_id=customer.id, delivery_id=delivery_id, sales_order_id=delivery.sales_order_id if delivery else None,
                                rating=rating, comment=(comment or "")[:2000], complaint=bool(complaint))
    session.add(feedback)
    session.commit()
    if complaint:
        task = tasks.create_task(session, "Complaint from {} about {}".format(customer.name, delivery.delivery_number if delivery else "a delivery"),
                                 notes=comment, priority=priority, source="automation", customer_id=customer.id,
                                 sales_order_id=delivery.sales_order_id if delivery else None)
        feedback.task_id = task.id
        session.commit()
    return feedback


def care_call(session: Session, delivery: CustomerDelivery, cfg: Dict[str, Any]) -> Optional[Task]:
    """Give the after-sales check-in to the Customer care agent as a call."""
    from . import tasks

    customer = delivery.customer
    if not customer.phone or _open_agent_call(session, customer.id, "care"):
        return None
    items = ", ".join("{} {}".format(triggers._qty(l.quantity), l.order_item.product.name) for l in delivery.items[:5])
    brief = ("After-sales check-in for delivery {} (order {}): {}. Ask whether everything arrived right: quantity, quality, on time, the driver. "
             "{}Record what they say with record_feedback (complaint true if anything was wrong). If there is a complaint, apologise and say "
             "someone will call them today; do not promise refunds or replacements.").format(
        delivery.delivery_number, delivery.sales_order.order_number, items, "Ask for a rating from 1 to 5. " if cfg.get("ask_rating") else "")
    return tasks.create_task(session, "Delivery check-in: {} ({})".format(customer.name, delivery.delivery_number), kind="call", doer="pai",
                             agent="care", due_at=_now(), instructions=brief, source="automation", customer_id=customer.id,
                             sales_order_id=delivery.sales_order_id)


def record_feedback(session: Session, task_id: uuid.UUID, args: Dict[str, Any]) -> Dict[str, Any]:
    task = session.get(Task, task_id)
    if task is None or task.customer is None:
        return {"error": "No customer on this call."}
    cfg = automation.step(session, "sales.after_sales")["config"]
    rating = args.get("rating")
    try:
        rating = int(rating) if rating not in (None, "") else None
    except (TypeError, ValueError):
        rating = None
    if rating is not None and not 1 <= rating <= 5:
        rating = None
    complaint = bool(args.get("complaint")) or (rating is not None and rating <= int(cfg.get("low_rating") or 2))
    delivery_id = None
    event = session.execute(select(triggers.AutomationEvent).where(
        triggers.AutomationEvent.step == "sales.after_sales", triggers.AutomationEvent.party_id == task.customer_id)
        .order_by(triggers.AutomationEvent.created_at.desc())).scalars().first()
    if event is not None:
        delivery_id = event.subject_id
        event.status = "replied"
    save_feedback(session, task.customer, delivery_id, rating, "On the call: {}".format(args.get("comment") or ""), complaint,
                  priority="HIGH" if cfg.get("complaint_priority") == "high" else "NORMAL")
    return {"ok": True, "complaint": complaint,
            "say": ("Apologise, say someone from the team will call them today. " if complaint else "Thank them warmly. ") +
                   "Then call finish_followup with outcome done."}
