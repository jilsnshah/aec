"""Run an operation through the application's own API, as the signed-in user.

The call goes through the full stack in-process -- sign-in check, request
validation, the route, its service, its transaction and its after-response
work (Tally sync) -- exactly as when the user clicks the button. The user's
session cookie is passed along so the same permissions apply; it never leaves
the server and is never shown to the model.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from ..models import AiToolCall
from ..services import auth as auth_service
from . import catalog

logger = logging.getLogger(__name__)


@dataclass
class ApiResult:
    ok: bool
    status: int
    data: Any
    error: Optional[str] = None


def _client(cookie: Optional[str]):
    from fastapi.testclient import TestClient

    from ..main import app

    client = TestClient(app, raise_server_exceptions=False, headers={"x-aec-actor": "assistant"})
    if cookie:
        client.cookies.set(auth_service.COOKIE, cookie)
    return client


def error_text(status: int, payload: Any) -> str:
    """The API's own error message, in the shape the screens show it."""
    if isinstance(payload, dict):
        if payload.get("message"):
            details = payload.get("details")
            return payload["message"] + (" ({})".format(json.dumps(details, default=str)[:300]) if details else "")
        detail = payload.get("detail")
        if isinstance(detail, list):
            parts = []
            for item in detail[:6]:
                where = ".".join(str(part) for part in item.get("loc", [])[1:])
                parts.append("{}: {}".format(where or "request", item.get("msg")))
            return "The request was not valid -- " + "; ".join(parts)
        if detail:
            return str(detail)
    return "The server answered {}.".format(status)


def call(
    name: str,
    args: Dict[str, Any],
    cookie: Optional[str],
    audit: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> ApiResult:
    operation = catalog.BY_NAME[name]
    clean = {key: value for key, value in args.items() if key != "summary"}
    started = time.monotonic()
    try:
        path, query, body = catalog.split_arguments(name, clean)
    except ValueError as exc:
        result = ApiResult(False, 400, None, str(exc))
    else:
        response = _client(cookie).request(operation.method, path, params=query, json=body)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code < 400:
            result = ApiResult(True, response.status_code, payload)
        else:
            result = ApiResult(False, response.status_code, payload, error_text(response.status_code, payload))
    duration = int((time.monotonic() - started) * 1000)
    if audit is not None:
        audit({
            "tool": name,
            "route": "{} {}".format(operation.method, operation.path),
            "arguments_json": json.dumps(clean, default=str)[:8000],
            "status_code": result.status,
            "ok": result.ok,
            "error": result.error,
            "duration_ms": duration,
        })
    logger.info("Assistant ran %s: %s in %d ms", name, result.status, duration)
    return result


def record_call(session_factory, user_id: Optional[uuid.UUID], conversation_id: Optional[uuid.UUID], entry: Dict[str, Any]) -> None:
    """Write one audit row in its own short transaction."""
    session: Session = session_factory()
    try:
        session.add(AiToolCall(user_id=user_id, conversation_id=conversation_id, **entry))
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Could not record an assistant tool call")
    finally:
        session.close()
