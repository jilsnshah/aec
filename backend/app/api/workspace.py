"""Targets, per-user preferences and saved views."""
from __future__ import annotations

import json
import re
import uuid
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import NotFoundError, ValidationError
from ..models import SalesTarget, SavedView, User, UserPreference, utcnow
from .auth import require_user

router = APIRouter(prefix="/api", tags=["workspace"])


class TargetIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$", description="YYYY-MM")
    metric: str = Field(default="booked", pattern="^(booked|revenue)$", description="booked (orders placed) or revenue (delivered).")
    amount: Decimal = Field(ge=0)


@router.get("/targets")
def list_targets(db: Session = Depends(get_db)):
    """Monthly sales targets."""
    rows = db.execute(select(SalesTarget).order_by(SalesTarget.month.desc())).scalars().all()
    return [{"month": t.month, "metric": t.metric, "amount": t.amount} for t in rows]


@router.put("/targets")
def set_target(payload: TargetIn, db: Session = Depends(get_db)):
    """Set (or change) the target for a month. An amount of 0 removes it."""
    row = db.execute(select(SalesTarget).where(SalesTarget.month == payload.month, SalesTarget.metric == payload.metric)).scalar_one_or_none()
    if payload.amount == 0:
        if row is not None:
            db.delete(row)
            db.commit()
        return {"month": payload.month, "metric": payload.metric, "amount": 0}
    if row is None:
        row = SalesTarget(month=payload.month, metric=payload.metric, amount=payload.amount)
        db.add(row)
    else:
        row.amount = payload.amount
        row.updated_at = utcnow()
    db.commit()
    return {"month": row.month, "metric": row.metric, "amount": row.amount}


KEY = re.compile(r"^[a-z0-9_.-]{1,64}$")


@router.get("/preferences/{key}")
def get_preference(key: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    row = db.execute(select(UserPreference).where(UserPreference.user_id == user.id, UserPreference.key == key)).scalar_one_or_none()
    return {"key": key, "value": json.loads(row.value_json) if row else None}


class PreferenceIn(BaseModel):
    value: Any


@router.put("/preferences/{key}")
def set_preference(key: str, payload: PreferenceIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Save a personal setting (e.g. the Home layout)."""
    if not KEY.match(key):
        raise ValidationError("Invalid preference key.")
    text = json.dumps(payload.value)
    if len(text) > 50_000:
        raise ValidationError("That preference is too large.")
    row = db.execute(select(UserPreference).where(UserPreference.user_id == user.id, UserPreference.key == key)).scalar_one_or_none()
    if row is None:
        db.add(UserPreference(user_id=user.id, key=key, value_json=text))
    else:
        row.value_json = text
        row.updated_at = utcnow()
    db.commit()
    return {"key": key, "value": payload.value}


class ViewIn(BaseModel):
    page: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    state: Any
    shared: bool = False


def _view(row: SavedView, user: User) -> dict:
    return {"id": str(row.id), "page": row.page, "name": row.name, "state": json.loads(row.state_json),
            "shared": row.shared, "mine": row.user_id == user.id, "created_at": row.created_at}


@router.get("/views")
def list_views(page: str = Query(...), db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Saved filter sets for a page: yours and shared ones."""
    rows = db.execute(
        select(SavedView).where(SavedView.page == page, or_(SavedView.user_id == user.id, SavedView.shared.is_(True)))
        .order_by(SavedView.name)
    ).scalars().all()
    return [_view(row, user) for row in rows]


@router.post("/views", status_code=201)
def save_view(payload: ViewIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    text = json.dumps(payload.state)
    if len(text) > 50_000:
        raise ValidationError("That view is too large.")
    row = SavedView(user_id=user.id, page=payload.page, name=payload.name.strip(), state_json=text, shared=payload.shared)
    db.add(row)
    db.commit()
    return _view(row, user)


@router.delete("/views/{view_id}", status_code=204)
def delete_view(view_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_user)):
    row = db.get(SavedView, view_id)
    if row is None or row.user_id != user.id:
        raise NotFoundError("Saved view not found.")
    db.delete(row)
    db.commit()
    return Response(status_code=204)
