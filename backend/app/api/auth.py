"""Signing in and out, and the ``require_user`` guard every other route uses."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import User
from ..services import auth as auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignIn(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class Me(BaseModel):
    username: str
    is_admin: bool


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    """The signed-in user, or 401. Guards every route except sign-in and webhooks."""
    return auth_service.user_for_token(db, request.cookies.get(auth_service.COOKIE))


def _set_cookie(response: Response, user: User) -> None:
    settings = get_settings()
    response.set_cookie(
        auth_service.COOKIE,
        auth_service.issue_token(user),
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=Me)
def login(payload: SignIn, response: Response, db: Session = Depends(get_db)):
    user = auth_service.sign_in(db, payload.username, payload.password)
    _set_cookie(response, user)
    return {"username": user.username, "is_admin": user.is_admin}


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(auth_service.COOKIE, path="/")


@router.get("/me", response_model=Me)
def me(user: User = Depends(require_user)):
    return {"username": user.username, "is_admin": user.is_admin}


@router.post("/password", response_model=Me)
def password(payload: PasswordChange, response: Response, user: User = Depends(require_user),
             db: Session = Depends(get_db)):
    """Change your password. Every other session is signed out; this one stays."""
    user = auth_service.change_password(db, user, payload.current_password, payload.new_password)
    _set_cookie(response, user)
    return {"username": user.username, "is_admin": user.is_admin}
