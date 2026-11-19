"""Follow-up endpoints."""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..models import User
from ..services import tasks as task_service
from .auth import require_user
from .pagination import PageParams, page_params

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=schemas.Page[schemas.TaskOut])
def list_tasks(
    status: Optional[str] = Query(default=None, description="OPEN, DONE or CANCELLED; comma-separated for several."),
    due: Optional[str] = Query(default=None, description="overdue, today or week."),
    assignee_id: Optional[uuid.UUID] = Query(default=None),
    customer_id: Optional[uuid.UUID] = Query(default=None),
    enquiry_id: Optional[uuid.UUID] = Query(default=None),
    sales_order_id: Optional[uuid.UUID] = Query(default=None),
    supplier_id: Optional[uuid.UUID] = Query(default=None),
    purchase_order_id: Optional[uuid.UUID] = Query(default=None),
    search: Optional[str] = Query(default=None, description="Matches title or notes."),
    paging: PageParams = Depends(page_params),
    db: Session = Depends(get_db),
):
    filters = dict(
        status=status, due=due, assignee_id=assignee_id, search=search, customer_id=customer_id,
        enquiry_id=enquiry_id, sales_order_id=sales_order_id, supplier_id=supplier_id,
        purchase_order_id=purchase_order_id,
    )
    items = task_service.list_tasks(db, paging.limit, paging.offset, **filters)
    return paging.page([task_service.to_view(task) for task in items], task_service.count_tasks(db, **filters))


@router.get("/counts", response_model=schemas.TaskCounts)
def task_counts(db: Session = Depends(get_db)):
    return task_service.open_counts(db)


@router.get("/assignees", response_model=List[schemas.UserRef])
def assignees(db: Session = Depends(get_db)):
    """Everyone a follow-up can be assigned to."""
    return task_service.users(db)


@router.post("", response_model=schemas.TaskOut, status_code=201)
def create_task(
    payload: schemas.TaskCreate, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)
):
    # The assistant calls this same route; it marks itself so the follow-up
    # says where it came from. The label is informational only.
    source = "assistant" if request.headers.get("x-aec-actor") == "assistant" else "manual"
    task = task_service.create_task(db, created_by_id=user.id, source=source, **payload.model_dump())
    return task_service.to_view(task)


@router.get("/{task_id}", response_model=schemas.TaskOut)
def get_task(task_id: uuid.UUID, db: Session = Depends(get_db)):
    return task_service.to_view(task_service.get_task(db, task_id))


@router.patch("/{task_id}", response_model=schemas.TaskOut)
def update_task(task_id: uuid.UUID, payload: schemas.TaskUpdate, db: Session = Depends(get_db)):
    return task_service.to_view(task_service.update_task(db, task_id, payload.model_dump(exclude_unset=True)))
