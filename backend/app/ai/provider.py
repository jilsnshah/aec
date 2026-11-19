"""Which model the assistant talks to.

Gemini is the only provider. Credentials come from Settings (an API key,
stored encrypted) or, failing that, from the server's Vertex AI environment.
Nothing here ever returns or logs a key.

Development mode (``AI_DEV_MODE=scripted``, only when no credentials are set)
swaps in :class:`ScriptedModel`: a fixed, clearly labelled script that calls
real tools so the interface can be built and tested without an API key. It is
never presented as AI.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy.orm import Session

from ..services import integration_settings as settings_service

logger = logging.getLogger(__name__)


class NotConfigured(Exception):
    """No Gemini credentials: neither a key in Settings nor server credentials."""


def dev_mode() -> bool:
    return os.environ.get("AI_DEV_MODE", "").strip().lower() == "scripted"


def status(session: Session) -> Dict[str, Any]:
    """What the browser may know: whether the assistant can run, and how."""
    row = settings_service.get(session, settings_service.AI)
    creds = settings_service.ai_credentials(session)
    mode = "live" if creds else ("development" if dev_mode() else "not_configured")
    return {
        "mode": mode,
        "assistant_enabled": bool(row.config.get("assistant", True)),
        "model": row.config.get("model") or settings_service.default_model(),
        "credential_source": creds["source"] if creds else None,
        "change_policy": row.config.get("change_policy", "confirm_all"),
    }


def chat_model(session: Session, model: Optional[str] = None, temperature: Optional[float] = None) -> BaseChatModel:
    """The configured Gemini model, ready for tool calling."""
    row = settings_service.get(session, settings_service.AI)
    name = (model or row.config.get("model") or settings_service.default_model()).replace("models/", "", 1)
    temp = float(row.config.get("temperature", 0.2) if temperature is None else temperature)
    creds = settings_service.ai_credentials(session)
    if creds is None:
        if dev_mode():
            return ScriptedModel()
        raise NotConfigured("Gemini is not connected. Add an API key in Settings → AI.")
    return gemini(name, creds, temp)


def gemini(model: str, creds: Dict[str, str], temperature: float = 0.2) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    common: Dict[str, Any] = {"model": model, "temperature": temperature, "max_retries": 2, "timeout": 180}
    if creds["mode"] == "api_key":
        return ChatGoogleGenerativeAI(google_api_key=creds["api_key"], **common)
    if creds["mode"] == "vertex_key":
        return ChatGoogleGenerativeAI(vertexai=True, google_api_key=creds["api_key"], **common)
    return ChatGoogleGenerativeAI(vertexai=True, project=creds["project"], location=creds["location"], **common)


def list_models(session: Session) -> List[Dict[str, str]]:
    """Gemini models the saved key can use for chat, newest first; the static
    list when Google cannot be asked."""
    creds = settings_service.ai_credentials(session)
    fallback = settings_service.available_models()
    if not creds or creds["mode"] != "api_key":
        return fallback
    try:
        from google import genai

        client = genai.Client(api_key=creds["api_key"])
        found = []
        for item in client.models.list():
            name = (item.name or "").replace("models/", "", 1)
            actions = getattr(item, "supported_actions", None) or []
            if not name.startswith("gemini") or "generateContent" not in actions:
                continue
            if any(word in name for word in ("embedding", "tts", "image", "audio", "live")):
                continue
            known = settings_service.model_info(name)
            found.append({
                "id": name,
                "provider": "gemini",
                "label": (item.display_name or name),
                "hint": known["hint"] if known else (item.description or "")[:120],
            })
        found.sort(key=lambda model: model["id"], reverse=True)
        return found or fallback
    except Exception as exc:  # network or key problems: keep the static list
        logger.info("Could not list Gemini models: %s", type(exc).__name__)
        return fallback


def explain_error(exc: Exception) -> str:
    """A short, user-facing reason for a failed model call. Never includes a key."""
    text = str(exc)
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    lowered = text.lower()
    if code in (401, 403) or "api key not valid" in lowered or "permission" in lowered or "unauthenticated" in lowered:
        return "Gemini rejected the API key. Check it in Settings → AI."
    if code == 404 or "not found" in lowered:
        return "That Gemini model is not available to this key. Choose another in Settings → AI."
    if code == 429 or "quota" in lowered or "resource exhausted" in lowered or "rate" in lowered:
        return "Gemini is rate limiting this key or its quota is used up. Try again shortly."
    if "timeout" in lowered or "timed out" in lowered or "deadline" in lowered:
        return "Gemini took too long to answer. Try again, or ask for less at once."
    if "connect" in lowered or "network" in lowered or "dns" in lowered:
        return "Could not reach Gemini. Check the server's internet connection."
    cleaned = re.sub(r"(key=|api[_-]?key[\"':= ]+)[A-Za-z0-9_\-\.]+", r"\1•••", text)
    return "Gemini returned an error: {}".format(cleaned[:240])


# ---------------------------------------------------------------------------
# Development mode
# ---------------------------------------------------------------------------

DEV_NOTICE = (
    "**Development mode** — no Gemini key is connected, so this reply is scripted, not AI. "
    "It ran the real `{tool}` tool on your data{table}. Connect a key in Settings → AI for real answers."
)

_ROUTES = [
    (r"reorder|stock|inventory|capital|dead|slow|ageing|aging", "inventory_health", {}),
    (r"enquir|lead|quote|conversion|funnel", "enquiry_funnel", {}),
    (r"supplier|vendor|procure", "supplier_performance", {}),
    (r"customer|client|buyer", "customer_ranking", {}),
    (r"follow|task|remind", "list_follow_ups", {"status": "OPEN"}),
    (r"compare|month|sales|revenue|profit|perform", "business_overview", {"period": "month"}),
]


class ScriptedModel(BaseChatModel):
    """Plays a fixed script against real tools: pick a data tool from keywords,
    show its result as a table, then say plainly that this is development mode.
    Asking to "create a follow-up" demonstrates the confirmation card."""

    @property
    def _llm_type(self) -> str:
        return "scripted-development"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages: List[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    def _next(self, messages: List[BaseMessage]) -> AIMessage:
        last = messages[-1]
        if isinstance(last, HumanMessage):
            text = _text(last).lower()
            if "[event, from the system" in text:
                ok = "succeeded" in text
                return AIMessage(content="**Development mode** — the change you confirmed {}. (Scripted reply; the result "
                                         "above comes from the application.)".format("was made" if ok else "failed; nothing was changed"))
            if re.search(r"(create|add|make|schedule).{0,20}follow", text):
                return _call("create_follow_up", {
                    "title": "Call back about the latest quote",
                    "summary": "Create a follow-up to call a customer back tomorrow.",
                })
            for pattern, tool, args in _ROUTES:
                if re.search(pattern, text):
                    return _call(tool, args)
            return _call("daily_briefing", {})
        if isinstance(last, ToolMessage):
            calls = [m for m in messages if isinstance(m, AIMessage) and m.tool_calls]
            tool = calls[-1].tool_calls[0]["name"] if calls else "a"
            try:
                result = json.loads(last.content)
            except (TypeError, ValueError):
                result = {}
            if tool not in ("show_table", "create_follow_up") and isinstance(result, dict) and result.get("dataset_id"):
                return _call("show_table", {"dataset_id": result["dataset_id"], "title": "Result of {}".format(tool)})
            data_tool = calls[-2].tool_calls[0]["name"] if tool == "show_table" and len(calls) > 1 else tool
            if tool == "create_follow_up":
                return AIMessage(content="**Development mode** — no Gemini key is connected. I proposed a follow-up "
                                         "for you to confirm or cancel above; nothing has been saved yet.")
            return AIMessage(content=DEV_NOTICE.format(tool=data_tool, table="; the table above is the actual result" if tool == "show_table" else ""))
        return AIMessage(content=DEV_NOTICE.format(tool="no", table=""))


def _call(name: str, args: Dict[str, Any]) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "call_" + uuid.uuid4().hex[:8]}])


def _text(message: BaseMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return " ".join(part.get("text", "") for part in message.content if isinstance(part, dict))
