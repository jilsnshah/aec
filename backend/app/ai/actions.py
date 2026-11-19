"""Proposed changes: confirm, run, report.

A change the assistant proposes is stored as a pending :class:`AiAction`. When
the user confirms, it runs through the same API route the screens use, as the
same user. The outcome -- success with the route's own response, or its exact
error -- is recorded on the action, shown on its card, and handed to the agent
as an event so it reports the real result. An action can run once only.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Callable, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ConflictError, NotFoundError
from ..models import AiAction, AiMessage, utcnow
from . import catalog, executor
from .describe import result_link

logger = logging.getLogger(__name__)


def _claim(session: Session, action_id: uuid.UUID, user_id: uuid.UUID) -> AiAction:
    action = session.execute(select(AiAction).where(AiAction.id == action_id).with_for_update()).scalar_one_or_none()
    if action is None or action.user_id != user_id:
        raise NotFoundError("That proposed change was not found.")
    if action.status != "pending":
        raise ConflictError("This change was already {}.".format(
            {"done": "made", "failed": "attempted", "cancelled": "cancelled", "running": "started"}.get(action.status, action.status)))
    return action


def _summarise(tool: str, data: Any) -> str:
    if not isinstance(data, dict):
        return "Done."
    for key in ("order_number", "enquiry_number", "po_number", "receipt_number", "delivery_number", "title", "name", "code", "sku"):
        if data.get(key):
            return "Done: {}.".format(data[key])
    if isinstance(data.get("order"), dict) and data["order"].get("order_number"):
        return "Done: order {}.".format(data["order"]["order_number"])
    return "Done."


def _update_card(session: Session, action: AiAction, **changes: Any) -> None:
    if action.message_id is None:
        return
    message = session.get(AiMessage, action.message_id)
    if message is None or not message.blocks_json:
        return
    blocks = json.loads(message.blocks_json)
    for block in blocks:
        if block.get("type") == "action" and block.get("action_id") == str(action.id):
            block.update({key: value for key, value in changes.items() if value is not None})
    message.blocks_json = json.dumps(blocks, default=str)


def execute(session_factory: Callable[[], Session], action_id: uuid.UUID, user_id: uuid.UUID,
            cookie: Optional[str], auto: bool = False) -> Dict[str, Any]:
    """Run a pending action once. Returns status, data, error and a link."""
    session = session_factory()
    try:
        action = _claim(session, action_id, user_id)
        action.status = "running"
        action.decided_at = utcnow()
        session.commit()
        args = json.loads(action.arguments_json)
        tool, conversation_id = action.tool, action.conversation_id
    finally:
        session.close()

    def audit(entry: Dict[str, Any]) -> None:
        executor.record_call(session_factory, user_id, conversation_id, entry)

    result = executor.call(tool, args, cookie, audit)
    link = result_link(tool, result.data) if result.ok else None
    outcome = {
        "status": "done" if result.ok else "failed",
        "data": result.data if result.ok else None,
        "error": result.error,
        "link": link,
        "result_summary": _summarise(tool, result.data) if result.ok else None,
    }
    session = session_factory()
    try:
        action = session.get(AiAction, action_id)
        action.status = outcome["status"]
        action.result_json = json.dumps(result.data, default=str)[:200000] if result.ok else None
        action.error = result.error
        if not auto:
            _update_card(session, action, status=outcome["status"], result=outcome["result_summary"],
                         error=outcome["error"], link=link)
        session.commit()
    finally:
        session.close()
    logger.info("Assistant action %s (%s): %s", action_id, tool, outcome["status"])
    return outcome


def cancel(session: Session, action_id: uuid.UUID, user_id: uuid.UUID) -> AiAction:
    action = _claim(session, action_id, user_id)
    action.status = "cancelled"
    action.decided_at = utcnow()
    _update_card(session, action, status="cancelled")
    session.add(AiMessage(conversation_id=action.conversation_id, role="event",
                          content="The user cancelled the proposed change: {} Nothing was changed.".format(action.summary)))
    session.commit()
    return action


def record_outcome(session: Session, action_id: uuid.UUID, outcome: Dict[str, Any]) -> None:
    """Tell the agent, through the conversation, what really happened."""
    action = session.get(AiAction, action_id)
    operation = catalog.BY_NAME.get(action.tool)
    label = operation.label if operation else action.tool
    if outcome["status"] == "done":
        data = json.dumps(outcome.get("data"), default=str)
        text = "The user confirmed and the change SUCCEEDED -- {} ({}). Response from the application: {}".format(
            action.summary, label, data[:6000])
    else:
        text = "The user confirmed but the change FAILED -- {} ({}). Error from the application: {}. Nothing was changed.".format(
            action.summary, label, outcome.get("error"))
    session.add(AiMessage(conversation_id=action.conversation_id, role="event", content=text))
    session.commit()
