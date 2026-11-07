"""Signing in: password hashing, sessions and the first admin.

Passwords are hashed with scrypt (Python's standard library), each with its
own random salt. A session is a signed token in an HttpOnly cookie: the user
id, an expiry and the user's session version, signed with ``SECRET_KEY``.
Changing a password raises the session version, which signs that user out
everywhere. Repeated wrong passwords lock the username for a few minutes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import begin_write
from ..errors import DomainError, ValidationError
from ..models import User

logger = logging.getLogger(__name__)

COOKIE = "aec_session"
MIN_PASSWORD = 10
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}

#: Wrong passwords per username before a short lock-out.
MAX_FAILURES = 5
LOCK_SECONDS = 300
_failures: Dict[str, Tuple[int, float]] = {}
_failures_lock = threading.Lock()


class NotSignedIn(DomainError):
    status_code = 401
    code = "not_signed_in"


class TooManyAttempts(DomainError):
    status_code = 429
    code = "too_many_attempts"


# --- passwords ---------------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=32, **_SCRYPT)
    return "scrypt${n}${r}${p}${salt}${digest}".format(
        salt=base64.b64encode(salt).decode(), digest=base64.b64encode(digest).decode(), **_SCRYPT
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=base64.b64decode(salt), dklen=len(expected),
            n=int(n), r=int(r), p=int(p),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _check_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise ValidationError("Use at least {} characters.".format(MIN_PASSWORD))


# --- sessions ------------------------------------------------------------------------


def _sign(payload: str) -> str:
    key = hashlib.sha256(("session:" + get_settings().secret_key).encode()).digest()
    return base64.urlsafe_b64encode(hmac.new(key, payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")


def issue_token(user: User) -> str:
    expires = int(time.time()) + get_settings().session_days * 86400
    payload = "{}.{}.{}".format(user.id, expires, user.session_version)
    return payload + "." + _sign(payload)


def user_for_token(session: Session, token: Optional[str]) -> User:
    if not token or token.count(".") != 3:
        raise NotSignedIn("Please sign in.")
    user_id, expires, version, signature = token.split(".")
    if not hmac.compare_digest(signature, _sign("{}.{}.{}".format(user_id, expires, version))):
        raise NotSignedIn("Please sign in.")
    if not expires.isdigit() or int(expires) < time.time():
        raise NotSignedIn("Your session has expired. Please sign in again.")
    try:
        user = session.get(User, uuid.UUID(user_id))
    except ValueError:
        user = None
    if user is None or str(user.session_version) != version:
        raise NotSignedIn("Please sign in again.")
    return user


# --- signing in ----------------------------------------------------------------------


def _locked(username: str) -> bool:
    with _failures_lock:
        count, until = _failures.get(username, (0, 0.0))
        return count >= MAX_FAILURES and until > time.time()


def _record_failure(username: str) -> None:
    with _failures_lock:
        count, until = _failures.get(username, (0, 0.0))
        if until and until < time.time():
            count = 0
        _failures[username] = (count + 1, time.time() + LOCK_SECONDS)


def sign_in(session: Session, username: str, password: str) -> User:
    username = (username or "").strip().lower()
    if _locked(username):
        raise TooManyAttempts("Too many wrong passwords. Try again in a few minutes.")
    user = session.execute(select(User).where(User.username == username)).scalar_one_or_none()
    # Hash even for an unknown name, so timing does not reveal which names exist.
    valid = verify_password(password or "", user.password_hash if user else hash_password("x" * 12))
    if user is None or not valid:
        _record_failure(username)
        logger.warning("Failed sign-in for %r", username)
        raise NotSignedIn("Wrong username or password.")
    with _failures_lock:
        _failures.pop(username, None)
    begin_write(session)
    user.last_login_at = datetime.now(timezone.utc)
    session.commit()
    logger.info("%s signed in", user.username)
    return user


def change_password(session: Session, user: User, current: str, new: str) -> User:
    if not verify_password(current or "", user.password_hash):
        raise ValidationError("The current password is wrong.")
    _check_strength(new or "")
    begin_write(session)
    user.password_hash = hash_password(new)
    user.session_version += 1
    session.commit()
    logger.info("%s changed their password", user.username)
    return user


def create_user(session: Session, username: str, password: str, is_admin: bool = False) -> User:
    username = (username or "").strip().lower()
    if not username:
        raise ValidationError("Choose a username.")
    _check_strength(password or "")
    begin_write(session)
    user = User(username=username, password_hash=hash_password(password), is_admin=is_admin)
    session.add(user)
    session.commit()
    return user


def ensure_admin(session: Session) -> None:
    """Create the first admin from ADMIN_USERNAME / ADMIN_PASSWORD if nobody exists."""
    settings = get_settings()
    if session.execute(select(func.count()).select_from(User)).scalar_one():
        return
    if not (settings.admin_username and settings.admin_password):
        logger.error("No users exist and ADMIN_USERNAME / ADMIN_PASSWORD are not set: nobody can sign in.")
        return
    create_user(session, settings.admin_username, settings.admin_password, is_admin=True)
    logger.info("Created the first admin, %s", settings.admin_username)
