"""Follow-ups: things someone has to do by a date.

A task can point at the customer, enquiry, sales order, supplier or purchase
order it is about. Due dates are calendar days in the business's time zone; a
task is overdue once its day has passed and it is still open.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..database import begin_write
from ..errors import NotFoundError, ValidationError
from ..models import (
    Customer,
    CustomerEnquiry,
    PurchaseOrder,
    SalesOrder,
    Supplier,
    Task,
    TaskPriority,
    TaskStatus,
    User,
    utcnow,
)
from .common import count_matching, windowed

LINKS = {
    "customer_id": Customer,
    "enquiry_id": CustomerEnquiry,
    "sales_order_id": SalesOrder,
    "supplier_id": Supplier,
    "purchase_order_id": PurchaseOrder,
}


def _zone() -> ZoneInfo:
    return ZoneInfo(get_settings().business_timezone)


def today() -> date:
    return datetime.now(_zone()).date()


def due_at(day: Optional[date]) -> Optional[datetime]:
    """A due day, stored as local midnight of that day."""
    if day is None:
        return None
    return datetime.combine(day, time.min, tzinfo=_zone())


def due_day(value: Optional[datetime]) -> Optional[date]:
    return value.astimezone(_zone()).date() if value is not None else None


def _with_relations(stmt):
    return stmt.options(
        joinedload(Task.assignee),
        joinedload(Task.customer),
        joinedload(Task.enquiry),
        joinedload(Task.sales_order),
        joinedload(Task.supplier),
        joinedload(Task.purchase_order),
    )


def _filtered(
    stmt,
    status: Optional[str] = None,
    assignee_id: Optional[uuid.UUID] = None,
    search: Optional[str] = None,
    due: Optional[str] = None,
    **links: Optional[uuid.UUID],
):
    if status:
        wanted = [part.strip().upper() for part in status.split(",") if part.strip()]
        stmt = stmt.where(Task.status.in_([TaskStatus(value) for value in wanted]))
    if assignee_id:
        stmt = stmt.where(Task.assignee_id == assignee_id)
    for name, value in links.items():
        if value is not None:
            stmt = stmt.where(getattr(Task, name) == value)
    if search:
        pattern = "%{}%".format(search.strip())
        stmt = stmt.where(or_(Task.title.ilike(pattern), Task.notes.ilike(pattern)))
    if due:
        start = due_at(today())
        if due == "overdue":
            stmt = stmt.where(Task.status == TaskStatus.OPEN, Task.due_date < start)
        elif due == "today":
            stmt = stmt.where(Task.due_date >= start, Task.due_date < start + timedelta(days=1))
        elif due == "week":
            stmt = stmt.where(Task.due_date < start + timedelta(days=7))
        else:
            raise ValidationError("due must be overdue, today or week.")
    return stmt


def list_tasks(session: Session, limit: int = 50, offset: int = 0, **filters: Any) -> List[Task]:
    stmt = _with_relations(_filtered(select(Task), **filters)).order_by(
        Task.status, Task.due_date.asc().nulls_last(), Task.created_at.desc()
    )
    return list(session.execute(windowed(stmt, limit, offset)).unique().scalars().all())


def count_tasks(session: Session, **filters: Any) -> int:
    return count_matching(session, _filtered(select(Task), **filters))


def get_task(session: Session, task_id: uuid.UUID) -> Task:
    task = session.execute(_with_relations(select(Task).where(Task.id == task_id))).unique().scalar_one_or_none()
    if task is None:
        raise NotFoundError("Follow-up not found.", {"task_id": str(task_id)})
    return task


def _check_links(session: Session, values: Dict[str, Any]) -> None:
    for name, model in LINKS.items():
        value = values.get(name)
        if value is not None and session.get(model, value) is None:
            raise NotFoundError("The {} this follow-up points at does not exist.".format(name.replace("_id", "").replace("_", " ")))
    assignee = values.get("assignee_id")
    if assignee is not None and session.get(User, assignee) is None:
        raise NotFoundError("That user does not exist.")


def create_task(
    session: Session,
    title: str,
    notes: Optional[str] = None,
    due_date: Optional[date] = None,
    priority: str = "NORMAL",
    assignee_id: Optional[uuid.UUID] = None,
    created_by_id: Optional[uuid.UUID] = None,
    source: str = "manual",
    **links: Optional[uuid.UUID],
) -> Task:
    title = (title or "").strip()
    if not title:
        raise ValidationError("A follow-up needs a title.")
    begin_write(session)
    values = {name: links.get(name) for name in LINKS}
    values["assignee_id"] = assignee_id
    _check_links(session, values)
    task = Task(
        title=title[:255],
        notes=(notes or "").strip() or None,
        due_date=due_at(due_date),
        priority=TaskPriority(priority.upper()),
        assignee_id=assignee_id,
        created_by_id=created_by_id,
        source=source,
        **{name: value for name, value in values.items() if name in LINKS},
    )
    session.add(task)
    session.commit()
    return get_task(session, task.id)


def update_task(session: Session, task_id: uuid.UUID, changes: Dict[str, Any]) -> Task:
    begin_write(session)
    task = get_task(session, task_id)
    if "title" in changes:
        title = (changes["title"] or "").strip()
        if not title:
            raise ValidationError("A follow-up needs a title.")
        task.title = title[:255]
    if "notes" in changes:
        task.notes = (changes["notes"] or "").strip() or None
    if "due_date" in changes:
        task.due_date = due_at(changes["due_date"])
    if "priority" in changes and changes["priority"]:
        task.priority = TaskPriority(str(changes["priority"]).upper())
    link_changes = {name: changes[name] for name in list(LINKS) + ["assignee_id"] if name in changes}
    _check_links(session, link_changes)
    for name, value in link_changes.items():
        setattr(task, name, value)
    if "status" in changes and changes["status"]:
        status = TaskStatus(str(changes["status"]).upper())
        if status != task.status:
            task.status = status
            task.completed_at = utcnow() if status == TaskStatus.DONE else None
    session.commit()
    return get_task(session, task.id)


def to_view(task: Task) -> Dict[str, Any]:
    day = due_day(task.due_date)
    overdue = task.status == TaskStatus.OPEN and day is not None and day < today()
    return {
        "id": task.id,
        "title": task.title,
        "notes": task.notes,
        "due_date": day,
        "overdue": overdue,
        "status": task.status,
        "priority": task.priority,
        "source": task.source,
        "assignee_id": task.assignee_id,
        "assignee": task.assignee.username if task.assignee else None,
        "customer_id": task.customer_id,
        "customer_name": task.customer.name if task.customer else None,
        "enquiry_id": task.enquiry_id,
        "enquiry_number": task.enquiry.enquiry_number if task.enquiry else None,
        "sales_order_id": task.sales_order_id,
        "order_number": task.sales_order.order_number if task.sales_order else None,
        "supplier_id": task.supplier_id,
        "supplier_name": task.supplier.name if task.supplier else None,
        "purchase_order_id": task.purchase_order_id,
        "po_number": task.purchase_order.po_number if task.purchase_order else None,
        "created_at": task.created_at,
        "completed_at": task.completed_at,
    }


def open_counts(session: Session) -> Dict[str, int]:
    start = due_at(today())
    open_q = select(func.count()).select_from(Task).where(Task.status == TaskStatus.OPEN)
    return {
        "open": session.execute(open_q).scalar_one(),
        "overdue": session.execute(open_q.where(Task.due_date < start)).scalar_one(),
        "due_today": session.execute(
            open_q.where(Task.due_date >= start, Task.due_date < start + timedelta(days=1))
        ).scalar_one(),
    }


def users(session: Session) -> List[Dict[str, Any]]:
    return [{"id": user.id, "username": user.username} for user in session.execute(select(User).order_by(User.username)).scalars()]
