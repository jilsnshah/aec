"""The text side of the agents: writing messages and reading replies with AI.

Every agent writes in its own role (``agents.profile``): the Purchasing agent
writes as a buyer, the Collections agent as a polite accounts person. Facts
(amounts, quantities, numbers, dates) come only from what the caller passes
in, and are checked: a message that drops a fact it was given is not used.

When Gemini is not connected (or fails), callers fall back to their fixed
wording, so nothing stops working.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from . import agents
from . import integration_settings as settings_service

logger = logging.getLogger(__name__)

#: Tests replace this: (session, system, prompt) -> dict or None.
llm_json: Optional[Callable[[Session, str, str], Optional[Dict[str, Any]]]] = None


def available(session: Session) -> bool:
    return llm_json is not None or settings_service.ai_credentials(session) is not None


def ask_json(session: Session, system: str, prompt: str) -> Optional[Dict[str, Any]]:
    """One JSON answer from Gemini, or None."""
    if llm_json is not None:
        return llm_json(session, system, prompt)
    creds = settings_service.ai_credentials(session)
    if creds is None:
        return None
    from langchain_core.messages import HumanMessage, SystemMessage

    from ..ai import provider

    model = (settings_service.get(session, settings_service.AI).config.get("model") or settings_service.default_model()).replace("models/", "", 1)
    try:
        reply = provider.gemini(model, creds, temperature=0.3).invoke([SystemMessage(content=system), HumanMessage(content=prompt)])
    except Exception as exc:  # network, quota, model
        logger.warning("Agent text call failed: %s", exc)
        return None
    text = reply.content if isinstance(reply.content, str) else "".join(
        p.get("text", "") if isinstance(p, dict) else str(p) for p in reply.content)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except ValueError:
        return None


def _seller(session: Session) -> str:
    return settings_service.get(session, settings_service.TALLY).config.get("seller_name") or "our business"


def _numbers(value: Any) -> List[str]:
    """The figures in a fact, as digits without separators."""
    return [n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", json.dumps(value, default=str))]


def write(session: Session, agent: str, purpose: str, facts: Dict[str, Any], fallback: str, *,
          must_keep: Optional[List[str]] = None, max_chars: int = 700, language_hint: Optional[str] = None) -> str:
    """A WhatsApp message written by the agent, or ``fallback``.

    ``must_keep``: strings (numbers, document numbers) the message must
    contain; if the AI leaves one out, the fixed wording is used instead."""
    if not available(session):
        return fallback
    profile = agents.profile(session, agent)
    system = (
        "You are {name}, the {label} of {seller}, an Indian building materials trader. Write ONE WhatsApp message for this purpose: {purpose}. "
        "Use only the facts given; never invent prices, dates, discounts or promises. Keep every number, amount and document number exactly as given. "
        "Short and natural (2-5 sentences), warm but businesslike, no hashtags, no markdown, at most one emoji. "
        "Write in {language}. {extra}Answer with JSON only: {{\"message\": \"...\"}}."
    ).format(name=profile["name"], label=profile["label"].lower(), seller=_seller(session), purpose=purpose,
             language=language_hint or "simple English (a little Hindi or Gujarati greeting is fine)",
             extra=("Owner's instructions: " + profile["instructions"] + " ") if profile["instructions"] else "")
    answer = ask_json(session, system, json.dumps({"facts": facts, "fixed_wording_for_reference": fallback}, default=str))
    message = str((answer or {}).get("message") or "").strip()
    if not message or len(message) > max_chars:
        return fallback
    flat = message.replace(",", "")
    for keep in must_keep or []:
        if str(keep).replace(",", "") not in flat:
            logger.info("AI message dropped %r; using the fixed wording", keep)
            return fallback
    return message


# ---------------------------------------------------------------------------
# Reading replies
# ---------------------------------------------------------------------------


def read_supplier_reply(session: Session, items: List[Dict[str, Any]], text: str, known: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """What a supplier's WhatsApp reply says about a price request.

    ``items``: [{item, product, quantity, unit, last_price}]. Returns
    {kind: quote|decline|question|other, lines: [{item, price, available_quantity}],
    delivery_days, freight, gst_included, valid_days, missing: [...], ask_back: "..."}
    or None when AI is not available."""
    if not available(session):
        return None
    profile = agents.profile(session, "purchasing")
    system = (
        "You read a supplier's WhatsApp reply to our price request for the {label} of {seller} (India). Extract only what the supplier actually said. "
        "Prices are per the unit named for each item; if they quote per a different unit (e.g. per tonne when we asked per bag) convert using the item's "
        "unit only if the conversion is certain, otherwise leave the price out and put the item in missing. Hindi, Gujarati and Hinglish are common "
        "(\"rate 365\", \"GST alag\" = GST extra, \"parso\" = in 2 days). "
        "kind: quote (at least one price), decline (cannot supply), question (they ask us something), other. "
        "missing: important facts not given (price for an item, GST, delivery). ask_back: a short polite WhatsApp question to get what is missing "
        "or to answer their question, in their language; empty if nothing to ask. "
        "JSON only: {{\"kind\": \"\", \"lines\": [{{\"item\": 1, \"price\": 0, \"available_quantity\": null}}], \"delivery_days\": null, "
        "\"freight\": null, \"gst_included\": null, \"valid_days\": null, \"missing\": [], \"ask_back\": \"\"}}"
    ).format(label=profile["label"].lower(), seller=_seller(session))
    answer = ask_json(session, system, json.dumps({"items": items, "already_known": known or {}, "reply": text}, default=str))
    if not isinstance(answer, dict) or answer.get("kind") not in ("quote", "decline", "question", "other"):
        return None
    lines = []
    for row in answer.get("lines") or []:
        try:
            item, price = int(row.get("item")), float(row.get("price"))
        except (TypeError, ValueError, AttributeError):
            continue
        if price > 0 and any(i["item"] == item for i in items):
            lines.append({"item": item, "price": price, "available_quantity": row.get("available_quantity")})
    answer["lines"] = lines
    return answer


def read_date_reply(session: Session, text: str, today: str) -> Optional[Dict[str, Any]]:
    """A supplier's answer about when goods will arrive: {date: YYYY-MM-DD|null, problem: str|null}."""
    if not available(session):
        return None
    answer = ask_json(session, (
        "A supplier replied on WhatsApp about when our order will be delivered. Today is {}. Turn words like kal, parso, Monday, next week "
        "into a date. problem: anything that means they cannot deliver as ordered (short, out of stock, price change), else null. "
        "JSON only: {{\"date\": \"YYYY-MM-DD or null\", \"problem\": null}}").format(today), json.dumps({"reply": text}))
    return answer if isinstance(answer, dict) else None


def read_feedback(session: Session, text: str) -> Optional[Dict[str, Any]]:
    """A customer's answer to the after-sales question: {answer: bool, rating: 1-5|null, complaint: bool, summary}."""
    if not available(session):
        return None
    answer = ask_json(session, (
        "A customer replied on WhatsApp to our question about how their delivery went. answer: is this a reply to that question at all? "
        "rating: 1-5 if they gave one (or clearly implied very good=5 / very bad=1), else null. complaint: anything wrong (damaged, short, late, "
        "wrong item, quality, rude driver), in any language. summary: one line in English. "
        "JSON only: {\"answer\": true, \"rating\": null, \"complaint\": false, \"summary\": \"\"}"), json.dumps({"reply": text}))
    return answer if isinstance(answer, dict) else None
