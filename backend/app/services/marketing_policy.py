"""The rules every promotional message obeys, whoever sends it.

- Consent: only customers with an ``opted_in`` consent for the channel.
- Opt-out: a reply with an opt-out word records ``opted_out`` at once.
- Frequency cap: at most N promotional messages per customer per D days.
- Quiet hours: nothing goes out at night; sending waits for the morning.

Agents never bypass these: the executor checks them for every message.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import NotFoundError, ValidationError
from ..models import Customer, MarketingConsent, MarketingSend
from . import integration_settings as settings_service

CHANNELS = ("whatsapp", "email", "sms")
SOURCES = ("manual", "portal", "whatsapp_keyword", "whatsapp_reply", "import", "enquiry", "order", "form")
COUNTED = ("sending", "sent", "delivered", "read", "replied")
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def validate(config: Dict[str, Any]) -> None:
    """Check and tidy the marketing settings (called when they are saved)."""
    for key in ("quiet_start", "quiet_end"):
        if not _TIME.match(str(config.get(key) or "")):
            raise ValidationError("Quiet hours must look like 21:00.")
    try:
        ZoneInfo(str(config.get("timezone") or ""))
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError("Unknown time zone '{}'.".format(config.get("timezone")))
    for key, low, high in (("frequency_max", 0, 50), ("frequency_days", 1, 90), ("send_per_minute", 1, 1000),
                           ("attribution_days", 1, 90), ("auto_max_audience", 0, 100000), ("scan_hours", 1, 720),
                           ("analyst_weekday", 0, 6)):
        try:
            number = int(config.get(key))
        except (TypeError, ValueError):
            raise ValidationError("{} must be a whole number.".format(key.replace("_", " ").capitalize()))
        if not low <= number <= high:
            raise ValidationError("{} must be between {} and {}.".format(key.replace("_", " ").capitalize(), low, high))
        config[key] = number
    if config.get("approval") not in ("approval", "auto"):
        raise ValidationError("Approval must be approval or auto.")
    try:
        config["message_cost"] = max(0.0, float(config.get("message_cost") or 0))
    except (TypeError, ValueError):
        raise ValidationError("Message cost must be a number.")
    colors = [str(c).strip() for c in config.get("brand_colors") or [] if str(c).strip()]
    for color in colors:
        if not re.match(r"^#[0-9a-fA-F]{6}$", color):
            raise ValidationError("Brand colours must look like #0B1220.")
    config["brand_colors"] = colors[:5] or ["#0B1220", "#38BDF8", "#FFFFFF"]
    config["brand_hashtags"] = [("#" + str(t).strip().lstrip("#")) for t in config.get("brand_hashtags") or [] if str(t).strip().lstrip("#")][:15]
    config["opt_out_words"] = [str(w).strip() for w in config.get("opt_out_words") or [] if str(w).strip()] or ["STOP"]
    url = str(config.get("public_url") or "").strip().rstrip("/")
    if url and not url.startswith("https://"):
        raise ValidationError("The public address must start with https:// (Instagram only fetches images over https).")
    config["public_url"] = url
    occasions = []
    for item in config.get("occasions") or []:
        name = str((item or {}).get("name") or "").strip()
        when = str((item or {}).get("date") or "").strip()
        if not name and not when:
            continue
        try:
            datetime.strptime(when, "%Y-%m-%d")
        except ValueError:
            raise ValidationError("Give {} a date like 2027-01-14.".format(name or "each occasion"))
        try:
            lead = int((item or {}).get("lead_days") or 7)
        except (TypeError, ValueError):
            lead = 7
        occasions.append({"name": name or "Occasion", "date": when, "lead_days": max(1, min(lead, 60))})
    config["occasions"] = occasions


def config(session: Session) -> Dict[str, Any]:
    return dict(settings_service.get(session, settings_service.MARKETING).config)


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------


def consent_of(session: Session, customer_id: uuid.UUID) -> Dict[str, Dict[str, Any]]:
    rows = session.execute(select(MarketingConsent).where(MarketingConsent.customer_id == customer_id)).scalars().all()
    return {r.channel: {"status": r.status, "source": r.source, "evidence": r.evidence, "at": r.at, "by": r.recorded_by} for r in rows}


def opted_in(session: Session, channel: str, customer_ids: Optional[Iterable[uuid.UUID]] = None) -> Set[uuid.UUID]:
    stmt = select(MarketingConsent.customer_id).where(MarketingConsent.channel == channel, MarketingConsent.status == "opted_in")
    if customer_ids is not None:
        ids = list(customer_ids)
        if not ids:
            return set()
        stmt = stmt.where(MarketingConsent.customer_id.in_(ids))
    return set(session.execute(stmt).scalars().all())


def set_consent(session: Session, customer_id: uuid.UUID, channel: str, status: str, source: str = "manual",
                evidence: Optional[str] = None, by: Optional[str] = None) -> Dict[str, Any]:
    """Record a customer's choice. The latest choice wins; the audit log keeps the history."""
    from . import controls

    if channel not in CHANNELS:
        raise ValidationError("Channel must be one of {}.".format(", ".join(CHANNELS)))
    if status not in ("opted_in", "opted_out"):
        raise ValidationError("Status must be opted_in or opted_out.")
    if source not in SOURCES:
        raise ValidationError("Unknown consent source '{}'.".format(source))
    if status == "opted_in" and source == "manual" and not (evidence or "").strip():
        raise ValidationError("Say how the customer agreed (for example: asked in the shop on 12 Nov, signed form).")
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError("Customer not found.")
    row = session.execute(select(MarketingConsent).where(MarketingConsent.customer_id == customer_id, MarketingConsent.channel == channel)).scalar_one_or_none()
    if row is None:
        row = MarketingConsent(customer_id=customer_id, channel=channel, status=status)
        session.add(row)
    row.status, row.source, row.evidence, row.recorded_by, row.at = status, source, (evidence or "").strip() or None, by, _now()
    session.flush()
    controls.log(session, None, "marketing_consent", "customer", str(customer_id), "{} {} on {} ({})".format(customer.name, status.replace("_", " "), channel, source))
    session.commit()
    return consent_of(session, customer_id)


def is_opt_out(session: Session, text: str) -> bool:
    words = [w.strip().lower() for w in config(session).get("opt_out_words") or []]
    clean = re.sub(r"[^\w\sऀ-૿]", "", (text or "").strip().lower()).strip()
    return bool(clean) and clean in words


# ---------------------------------------------------------------------------
# Frequency cap and quiet hours
# ---------------------------------------------------------------------------


def recent_counts(session: Session, customer_ids: Iterable[uuid.UUID], days: int) -> Dict[uuid.UUID, int]:
    ids = list(customer_ids)
    if not ids:
        return {}
    since = _now() - timedelta(days=days)
    rows = session.execute(
        select(MarketingSend.customer_id, func.count()).where(
            MarketingSend.customer_id.in_(ids), MarketingSend.status.in_(COUNTED), MarketingSend.sent_at >= since
        ).group_by(MarketingSend.customer_id)
    ).all()
    return {cid: n for cid, n in rows}


def over_cap(session: Session, customer_ids: Iterable[uuid.UUID], cfg: Optional[Dict[str, Any]] = None) -> Set[uuid.UUID]:
    cfg = cfg or config(session)
    cap = int(cfg.get("frequency_max") or 0)
    if cap <= 0:
        return set()
    counts = recent_counts(session, customer_ids, int(cfg.get("frequency_days") or 7))
    return {cid for cid, n in counts.items() if n >= cap}


def _clock(text: str) -> time:
    h, m = str(text).split(":")
    return time(int(h), int(m))


def quiet_now(cfg: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    try:
        zone = ZoneInfo(cfg.get("timezone") or "Asia/Kolkata")
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("Asia/Kolkata")
    local = (now or _now()).astimezone(zone).time()
    start, end = _clock(cfg.get("quiet_start") or "21:00"), _clock(cfg.get("quiet_end") or "09:00")
    if start == end:
        return False
    return (local >= start or local < end) if start > end else (start <= local < end)


def eligibility(session: Session, channel: str, customer_ids: List[uuid.UUID]) -> Dict[uuid.UUID, Optional[str]]:
    """For each customer: None if they may receive a promotion now on this
    channel, else the reason they may not."""
    cfg = config(session)
    customers = {c.id: c for c in session.execute(select(Customer).where(Customer.id.in_(customer_ids))).scalars()} if customer_ids else {}
    consenting = opted_in(session, channel, customer_ids)
    outs = set(session.execute(select(MarketingConsent.customer_id).where(
        MarketingConsent.customer_id.in_(customer_ids or [uuid.uuid4()]), MarketingConsent.channel == channel, MarketingConsent.status == "opted_out"
    )).scalars().all())
    capped = over_cap(session, customer_ids, cfg)
    out: Dict[uuid.UUID, Optional[str]] = {}
    for cid in customer_ids:
        c = customers.get(cid)
        if c is None or not c.is_active:
            out[cid] = "Not an active customer"
        elif cid in outs:
            out[cid] = "Opted out"
        elif cid not in consenting:
            out[cid] = "No marketing consent"
        elif channel == "whatsapp" and not (c.phone or "").strip():
            out[cid] = "No phone number"
        elif channel == "email" and not (c.email or "").strip():
            out[cid] = "No email"
        elif cid in capped:
            out[cid] = "Already got {} messages in {} days".format(cfg.get("frequency_max"), cfg.get("frequency_days"))
        else:
            out[cid] = None
    return out
