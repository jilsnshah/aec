"""The AI agents: who does which job.

Each agent has one job, its own instructions and its own tools. TAI and PAI
are not agents but the two mediums an agent works through: text (WhatsApp,
email) and phone (voice). The Sales agent, for example, answers on WhatsApp
and on the phone; the Purchasing agent asks suppliers for prices by WhatsApp
or by calling them.

Every automation step names the agent that carries it out. The owner can give
each agent a name, a voice and extra instructions (Settings → Automation →
Agents).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..errors import ValidationError
from . import integration_settings as settings_service

#: key -> what the agent is for. ``mediums``: what is built today.
AGENTS: Dict[str, Dict[str, Any]] = {
    "sales": {
        "label": "Sales agent", "default_name": "Asha",
        "job": "Answers customers who write or call: prices, stock, their orders and balance; takes enquiries, sends quotes and books orders when allowed.",
        "steps": ["sales.trigger_incoming", "sales.understand", "sales.price", "sales.send_quote", "sales.confirm_order"],
        "mediums": ["text", "phone"],
    },
    "outreach": {
        "label": "Outreach agent", "default_name": "Asha",
        "job": "Contacts customers who are due to reorder, have gone quiet or left a quote open; pitches what is in stock.",
        "steps": ["sales.trigger_outreach"], "mediums": ["text", "phone"],
    },
    "care": {
        "label": "Customer care agent", "default_name": "Asha",
        "job": "After-sales check-ins by WhatsApp or a call: asks how the delivery went, records a rating and feedback, raises complaints for a person.",
        "steps": ["sales.order_confirmation", "sales.after_sales"], "mediums": ["text", "phone"],
    },
    "collections": {
        "label": "Collections agent", "default_name": "Asha",
        "job": "Reminds customers of overdue bills (friendly, then firm, then final) by WhatsApp or a call; records when they promise to pay or dispute a bill, and checks again on the promised date.",
        "steps": ["sales.payment_reminders"], "mediums": ["text", "phone"],
    },
    "purchasing": {
        "label": "Purchasing agent", "default_name": "Ravi",
        "job": "Sends purchase enquiries to the chosen suppliers by WhatsApp or a call, records each offer (asking for the last price paid when it is higher), and chases deliveries. It never places orders.",
        "steps": ["purchase.ask_supplier", "purchase.chase_delivery"],
        "mediums": ["text", "phone"],
    },
    "logistics": {
        "label": "Logistics agent", "default_name": "Ravi",
        "job": "Books vehicles with transporters. Parked: transport is booked by hand for now.",
        "steps": ["sales.book_transport", "purchase.book_transport"], "mediums": [], "parked": True,
    },
    "followup": {
        "label": "Follow-up agent", "default_name": "Asha",
        "job": "Makes the follow-up calls you give it, at the exact time, following your instructions, and reports back on the follow-up.",
        "steps": [], "mediums": ["phone"],
    },
}
#: Agents that work inside the app rather than with customers or suppliers.
OTHER_AGENTS = [
    {"key": "assistant", "label": "Assistant", "job": "Answers questions about the business and makes changes you confirm (Assistant page)."},
    {"key": "strategist", "label": "Marketing strategist", "job": "Finds what to promote and to whom (Marketing)."},
    {"key": "creative", "label": "Marketing creative", "job": "Writes posts and messages, draws cards and pictures (Marketing)."},
    {"key": "engagement", "label": "Marketing engagement", "job": "Sorts Instagram comments and drafts replies (Marketing)."},
    {"key": "analyst", "label": "Marketing analyst", "job": "Weekly review of what worked (Marketing)."},
]
STEP_AGENT = {step: key for key, agent in AGENTS.items() for step in agent["steps"]}
VOICES = ["Aoede", "Kore", "Leda", "Zephyr", "Puck", "Charon", "Fenrir", "Orus"]


def agent_for(step_key: str) -> Optional[str]:
    return STEP_AGENT.get(step_key)


def profile(session: Session, key: str) -> Dict[str, Any]:
    """The agent's name, voice and extra instructions as the owner set them."""
    base = AGENTS.get(key, {})
    saved = (settings_service.get(session, settings_service.AGENTS).config.get("profiles") or {}).get(key) or {}
    ai = settings_service.get(session, settings_service.AI).config
    return {
        "key": key, "label": base.get("label", key),
        "name": (saved.get("name") or "").strip() or (ai.get("agent_name") if key in ("sales", "outreach", "care", "collections", "followup") else None) or base.get("default_name", "Asha"),
        "voice": saved.get("voice") or None,
        "instructions": (saved.get("instructions") or "").strip(),
    }


def catalogue(session: Session) -> Dict[str, Any]:
    from . import automation

    labels = {s["key"]: s["label"] for s in automation.LIBRARY}
    items = []
    for key, agent in AGENTS.items():
        p = profile(session, key)
        items.append({**p, "job": agent["job"], "mediums": agent["mediums"], "parked": bool(agent.get("parked")),
                      "steps": [{"key": s, "label": labels.get(s, s)} for s in agent["steps"]]})
    return {"agents": items, "others": OTHER_AGENTS, "voices": VOICES}


def save_profiles(session: Session, profiles: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    clean: Dict[str, Dict[str, Any]] = {}
    for key, data in (profiles or {}).items():
        if key not in AGENTS:
            raise ValidationError("Unknown agent '{}'.".format(key))
        name = str((data or {}).get("name") or "").strip()[:40]
        voice = (data or {}).get("voice") or ""
        if voice and voice not in VOICES:
            raise ValidationError("Unknown voice '{}'.".format(voice))
        clean[key] = {"name": name, "voice": voice, "instructions": str((data or {}).get("instructions") or "").strip()[:4000]}
    settings_service.update(session, settings_service.AGENTS, config={"profiles": clean})
    return catalogue(session)
