"""Campaigns: plan, content, approval, execution and results.

Lifecycle: draft -> review -> approved -> running -> completed (or paused /
cancelled). Content is edited while draft or in review; editing approved
content needs the campaign paused first, and sends it back for review.

The executor (``tick``) is deterministic and is the only thing that talks to
Instagram and WhatsApp for marketing. It only touches approved campaigns,
checks consent, opt-outs, the frequency cap and quiet hours for every
message, publishes each Instagram post once (the container id is stored
first), sends each customer at most one message per broadcast (a unique row
per broadcast and customer), retries what may succeed later and logs
everything to ``marketing_events``.
"""
from __future__ import annotations

import logging
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from ..database import begin_write
from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import (
    Customer, CustomerEnquiry, InstagramComment, MarketingAudience, MarketingCampaign, MarketingContent, MarketingConversion,
    MarketingEvent, MarketingMedia, MarketingOpportunity, MarketingSend, OrderStatus, Product, SalesOrder, WhatsappTemplate,
)
from . import integration_settings as settings_service
from . import marketing_audiences as audiences
from . import marketing_media as media
from . import marketing_policy as policy

logger = logging.getLogger(__name__)

OBJECTIVES = {
    "sales": "Sell more", "launch": "New product launch", "clearance": "Clear stock", "reactivation": "Win back customers",
    "festival": "Festival / season", "loyalty": "Thank loyal customers", "awareness": "Brand awareness", "greeting": "Greeting",
}
STATUSES = ("draft", "review", "approved", "running", "completed", "paused", "cancelled")
CHANNELS = ("instagram", "whatsapp")
EDITABLE = ("draft", "review")
TERMINAL_CONTENT = ("published", "sent", "failed", "cancelled")
#: WhatsApp errors that will not succeed on retry for this person.
NO_RETRY_CODES = {131049, 131050, 131026, 131047, 132000, 132001, 132005, 132007, 132012, 132015, 132016, 470}
STATUS_ORDER = {"queued": 0, "sending": 1, "sent": 2, "delivered": 3, "read": 4, "replied": 5}
SEND_TRIES = 3
PUBLISH_TRIES = 5
PLACEHOLDERS = ("name", "first_name", "product", "offer", "link", "business", "city")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _code(session: Session) -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(20):
        code = "C" + "".join(secrets.choice(alphabet) for _ in range(5))
        if session.execute(select(MarketingCampaign.id).where(MarketingCampaign.code == code)).first() is None:
            return code
    raise ConflictError("Could not make a campaign code; try again.")


def log(session: Session, actor: str, kind: str, message: str, *, level: str = "info", campaign_id: Optional[uuid.UUID] = None,
        content_id: Optional[uuid.UUID] = None, data: Optional[Dict[str, Any]] = None) -> None:
    session.add(MarketingEvent(actor=actor, kind=kind, message=message, level=level, campaign_id=campaign_id,
                               content_id=content_id, data=data or {}))
    session.flush()


def events(session: Session, campaign_id: Optional[uuid.UUID] = None, limit: int = 100, level: Optional[str] = None) -> List[Dict[str, Any]]:
    stmt = select(MarketingEvent).order_by(MarketingEvent.at.desc()).limit(limit)
    if campaign_id:
        stmt = stmt.where(MarketingEvent.campaign_id == campaign_id)
    if level:
        stmt = stmt.where(MarketingEvent.level == level)
    names = dict(session.execute(select(MarketingCampaign.id, MarketingCampaign.name)).all())
    return [{"id": e.id, "at": e.at, "actor": e.actor, "kind": e.kind, "level": e.level, "message": e.message, "data": e.data,
             "campaign_id": e.campaign_id, "campaign": names.get(e.campaign_id), "content_id": e.content_id}
            for e in session.execute(stmt).scalars()]


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def _send_counts(session: Session, campaign_ids: Iterable[uuid.UUID]) -> Dict[uuid.UUID, Dict[str, int]]:
    ids = list(campaign_ids)
    out: Dict[uuid.UUID, Dict[str, int]] = {}
    if not ids:
        return out
    for cid, status, n in session.execute(select(MarketingSend.campaign_id, MarketingSend.status, func.count())
                                          .where(MarketingSend.campaign_id.in_(ids)).group_by(MarketingSend.campaign_id, MarketingSend.status)).all():
        out.setdefault(cid, {})[status] = n
    return out


def _funnel(counts: Dict[str, int]) -> Dict[str, int]:
    reached = lambda keys: sum(counts.get(k, 0) for k in keys)  # noqa: E731
    return {
        "audience": sum(counts.values()),
        "skipped": counts.get("skipped", 0),
        "failed": counts.get("failed", 0),
        "queued": counts.get("queued", 0) + counts.get("sending", 0),
        "sent": reached(("sent", "delivered", "read", "replied")),
        "delivered": reached(("delivered", "read", "replied")),
        "read": reached(("read", "replied")),
        "replied": counts.get("replied", 0),
    }


def _conversions(session: Session, campaign_ids: Iterable[uuid.UUID]) -> Dict[uuid.UUID, Dict[str, Any]]:
    ids = list(campaign_ids)
    out: Dict[uuid.UUID, Dict[str, Any]] = {}
    if not ids:
        return out
    for cid, orders, enquiries, value in session.execute(
        select(MarketingConversion.campaign_id, func.count(MarketingConversion.sales_order_id), func.count(MarketingConversion.enquiry_id),
               func.coalesce(func.sum(MarketingConversion.value), 0)).where(MarketingConversion.campaign_id.in_(ids)).group_by(MarketingConversion.campaign_id)
    ).all():
        out[cid] = {"orders": orders, "enquiries": enquiries, "revenue": float(value or 0)}
    return out


def content_view(session: Session, c: MarketingContent, with_preview: bool = False) -> Dict[str, Any]:
    out = {
        "id": c.id, "campaign_id": c.campaign_id, "channel": c.channel, "caption": c.caption, "hashtags": c.hashtags or [],
        "template_name": c.template_name, "template_language": c.template_language, "variables": c.variables or [],
        "media": media.view(session, c.media), "scheduled_at": c.scheduled_at, "status": c.status, "ai_generated": c.ai_generated,
        "version": c.version, "attempts": c.attempts, "error": c.error, "external_id": c.external_id, "permalink": c.permalink,
        "published_at": c.published_at, "metrics": c.metrics or {}, "synced_at": c.synced_at, "updated_at": c.updated_at,
    }
    if with_preview and c.channel == "whatsapp":
        out["preview"] = render_whatsapp(session, c, None)
    return out


def view(session: Session, campaign: MarketingCampaign, full: bool = False) -> Dict[str, Any]:
    counts = _send_counts(session, [campaign.id]).get(campaign.id, {})
    conv = _conversions(session, [campaign.id]).get(campaign.id, {"orders": 0, "enquiries": 0, "revenue": 0.0})
    funnel = _funnel(counts)
    cost = cost_of(session, campaign, funnel)
    ig = [c.metrics or {} for c in campaign.contents if c.channel == "instagram"]
    out = {
        "id": campaign.id, "code": campaign.code, "name": campaign.name, "objective": campaign.objective,
        "objective_label": OBJECTIVES.get(campaign.objective, campaign.objective), "status": campaign.status,
        "channels": campaign.channels or [], "audience_id": campaign.audience_id, "audience": campaign.audience or {},
        "product_ids": campaign.product_ids or [], "offer": campaign.offer, "brief": campaign.brief,
        "starts_at": campaign.starts_at, "ends_at": campaign.ends_at,
        "budget": float(campaign.budget) if campaign.budget is not None else None,
        "spend": float(campaign.spend) if campaign.spend is not None else None,
        "created_by": campaign.created_by, "opportunity_id": campaign.opportunity_id, "submitted_at": campaign.submitted_at,
        "approved_by": campaign.approved_by, "approved_at": campaign.approved_at, "completed_at": campaign.completed_at,
        "notes": campaign.notes, "created_at": campaign.created_at, "updated_at": campaign.updated_at,
        "funnel": funnel, "conversions": conv, "cost": cost,
        "roi": round((conv["revenue"] - cost) / cost, 2) if cost > 0 else None,
        "instagram": {k: sum(int(m.get(k) or 0) for m in ig) for k in ("reach", "views", "likes", "comments", "saved", "shares")},
        "content_count": len(campaign.contents),
        "next_at": min([c.scheduled_at for c in campaign.contents if c.scheduled_at and c.status in ("draft", "scheduled")], default=None),
        "health": health(campaign, funnel),
    }
    if full:
        aud = _definition(session, campaign)
        out["audience_summary"] = audiences.describe(session, aud)
        out["audience_count"] = len(audiences.resolve(session, aud))
        out["audience_name"] = session.get(MarketingAudience, campaign.audience_id).name if campaign.audience_id and session.get(MarketingAudience, campaign.audience_id) else None
        out["contents"] = [content_view(session, c, with_preview=True) for c in campaign.contents]
        out["products"] = [{"id": p.id, "name": p.name, "sku": p.sku, "unit": p.unit_of_measure, "stock": float(p.physical_stock or 0),
                            "mrp": float(p.mrp) if p.mrp is not None else None}
                           for p in session.execute(select(Product).where(Product.id.in_([uuid.UUID(i) for i in campaign.product_ids or []]))).scalars()]
        out["checks"] = readiness(session, campaign)
    return out


def health(campaign: MarketingCampaign, funnel: Dict[str, int]) -> Dict[str, str]:
    """A one-word health signal with its reason."""
    failed = [c for c in campaign.contents if c.status == "failed"]
    if failed:
        return {"level": "bad", "label": "Needs attention", "why": "{} item(s) failed: {}".format(len(failed), (failed[0].error or "")[:120])}
    if campaign.status == "review":
        return {"level": "warn", "label": "Waiting for approval", "why": "Approve it to schedule the content."}
    if campaign.status in ("running", "completed") and funnel["sent"] >= 10:
        read_rate = funnel["read"] / max(funnel["delivered"], 1)
        if funnel["delivered"] / max(funnel["sent"], 1) < 0.7:
            return {"level": "warn", "label": "Low delivery", "why": "Under 70% of messages were delivered; check numbers and WhatsApp limits."}
        if read_rate < 0.3:
            return {"level": "warn", "label": "Low reads", "why": "Fewer than 30% read the message; try another time or opening line."}
        return {"level": "ok", "label": "Healthy", "why": "{:.0%} of delivered messages were read.".format(read_rate)}
    if campaign.status == "running":
        return {"level": "ok", "label": "Running", "why": "Going out on schedule."}
    return {"level": "muted", "label": campaign.status.capitalize(), "why": ""}


def cost_of(session: Session, campaign: MarketingCampaign, funnel: Optional[Dict[str, int]] = None) -> float:
    per = float(policy.config(session).get("message_cost") or 0)
    funnel = funnel or _funnel(_send_counts(session, [campaign.id]).get(campaign.id, {}))
    return round(float(campaign.spend or 0) + per * funnel["delivered"], 2)


def _get(session: Session, campaign_id: uuid.UUID, lock: bool = False) -> MarketingCampaign:
    if lock:
        row = session.execute(select(MarketingCampaign).where(MarketingCampaign.id == campaign_id).with_for_update()).scalar_one_or_none()
    else:
        row = session.get(MarketingCampaign, campaign_id)
    if row is None:
        raise NotFoundError("Campaign not found.")
    return row


def get(session: Session, campaign_id: uuid.UUID) -> Dict[str, Any]:
    return view(session, _get(session, campaign_id), full=True)


def list_campaigns(session: Session, status: Optional[str] = None, channel: Optional[str] = None, q: Optional[str] = None,
                   objective: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    stmt = select(MarketingCampaign).order_by(MarketingCampaign.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(MarketingCampaign.status.in_(status.split(",")))
    if objective:
        stmt = stmt.where(MarketingCampaign.objective == objective)
    if q:
        stmt = stmt.where(or_(MarketingCampaign.name.ilike("%{}%".format(q)), MarketingCampaign.code.ilike("%{}%".format(q))))
    rows = session.execute(stmt).scalars().all()
    if channel:
        rows = [r for r in rows if channel in (r.channels or [])]
    return [view(session, r) for r in rows]


# ---------------------------------------------------------------------------
# Create and edit
# ---------------------------------------------------------------------------


def _definition(session: Session, campaign: MarketingCampaign) -> Dict[str, Any]:
    if campaign.audience_id:
        saved = session.get(MarketingAudience, campaign.audience_id)
        if saved is not None:
            return saved.definition or {}
    return campaign.audience or {}


def _dt(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError("'{}' is not a date and time.".format(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _apply(session: Session, campaign: MarketingCampaign, data: Dict[str, Any]) -> None:
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValidationError("Give the campaign a name.")
        campaign.name = name[:160]
    if "objective" in data:
        if data["objective"] not in OBJECTIVES:
            raise ValidationError("Unknown objective.")
        campaign.objective = data["objective"]
    if "channels" in data:
        channels = [c for c in data.get("channels") or [] if c in CHANNELS]
        if not channels:
            raise ValidationError("Choose at least one channel: Instagram or WhatsApp.")
        campaign.channels = channels
    if "audience_id" in data:
        if data["audience_id"]:
            audiences.get(session, uuid.UUID(str(data["audience_id"])))
            campaign.audience_id = uuid.UUID(str(data["audience_id"]))
        else:
            campaign.audience_id = None
    if "audience" in data:
        campaign.audience = audiences.clean(data.get("audience"))
    if "product_ids" in data:
        ids = [str(uuid.UUID(str(i))) for i in data.get("product_ids") or []]
        found = set(str(i) for i in session.execute(select(Product.id).where(Product.id.in_([uuid.UUID(i) for i in ids]))).scalars()) if ids else set()
        if set(ids) - found:
            raise ValidationError("Some products were not found.")
        campaign.product_ids = ids
    for key in ("offer", "brief", "notes"):
        if key in data:
            setattr(campaign, key, (data.get(key) or "").strip() or None)
    for key in ("starts_at", "ends_at"):
        if key in data:
            setattr(campaign, key, _dt(data.get(key)))
    if campaign.starts_at and campaign.ends_at and campaign.ends_at < campaign.starts_at:
        raise ValidationError("The campaign must end after it starts.")
    for key in ("budget", "spend"):
        if key in data:
            value = data.get(key)
            if value in (None, ""):
                setattr(campaign, key, None)
            else:
                try:
                    number = Decimal(str(value))
                except Exception:
                    raise ValidationError("{} must be a number.".format(key.capitalize()))
                if number < 0:
                    raise ValidationError("{} cannot be negative.".format(key.capitalize()))
                setattr(campaign, key, number)


def create(session: Session, data: Dict[str, Any], by: Optional[str] = None, commit: bool = True) -> MarketingCampaign:
    campaign = MarketingCampaign(code=_code(session), name="Campaign", objective="sales", status="draft", channels=["whatsapp"],
                                 audience={}, product_ids=[], created_by=by)
    _apply(session, campaign, {"name": data.get("name") or "New campaign", **data})
    if data.get("opportunity_id"):
        campaign.opportunity_id = uuid.UUID(str(data["opportunity_id"]))
    session.add(campaign)
    session.flush()
    log(session, "person" if by and not by.startswith(("agent", "rule")) else "strategist", "created",
        "Campaign created by {}.".format(by or "someone"), campaign_id=campaign.id)
    if commit:
        session.commit()
    return campaign


def update(session: Session, campaign_id: uuid.UUID, data: Dict[str, Any], by: Optional[str] = None) -> Dict[str, Any]:
    try:
        begin_write(session)
        campaign = _get(session, campaign_id, lock=True)
        if campaign.status not in EDITABLE + ("paused",):
            raise ConflictError("Pause the campaign before changing it.")
        _apply(session, campaign, data)
        if campaign.status == "review":
            campaign.status = "draft"
            log(session, "person", "edited", "Changed by {} after it was sent for approval; it needs approving again.".format(by or "someone"), campaign_id=campaign.id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get(session, campaign_id)


def delete(session: Session, campaign_id: uuid.UUID) -> None:
    campaign = _get(session, campaign_id)
    if campaign.status not in ("draft", "cancelled"):
        raise ConflictError("Only draft or cancelled campaigns can be deleted.")
    if session.execute(select(MarketingSend.id).where(MarketingSend.campaign_id == campaign_id).limit(1)).first():
        raise ConflictError("Messages were sent for this campaign; cancel it instead to keep the record.")
    session.execute(sa_update(MarketingOpportunity).where(MarketingOpportunity.campaign_id == campaign_id).values(campaign_id=None, status="new"))
    session.delete(campaign)
    session.commit()


def _content(session: Session, content_id: uuid.UUID, lock: bool = False) -> MarketingContent:
    stmt = select(MarketingContent).where(MarketingContent.id == content_id)
    if lock:
        stmt = stmt.with_for_update()
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Content not found.")
    return row


def _apply_content(session: Session, c: MarketingContent, data: Dict[str, Any]) -> None:
    if "caption" in data:
        caption = (data.get("caption") or "").strip()
        if c.channel == "instagram" and len(caption) > 2200:
            raise ValidationError("Instagram captions can be at most 2,200 characters.")
        c.caption = caption or None
    if "hashtags" in data:
        tags = ["#" + str(t).strip().lstrip("#").replace(" ", "") for t in data.get("hashtags") or [] if str(t).strip().lstrip("#")]
        if len(tags) > 30:
            raise ValidationError("Instagram allows at most 30 hashtags.")
        c.hashtags = list(dict.fromkeys(tags))
    if "template_name" in data:
        c.template_name = (data.get("template_name") or "").strip() or None
    if "template_language" in data:
        c.template_language = (data.get("template_language") or "").strip() or None
    if "variables" in data:
        c.variables = [str(v) for v in data.get("variables") or []]
    if "media_id" in data:
        c.media_id = media.get(session, uuid.UUID(str(data["media_id"]))).id if data.get("media_id") else None
    if "scheduled_at" in data:
        c.scheduled_at = _dt(data.get("scheduled_at"))


def add_content(session: Session, campaign_id: uuid.UUID, data: Dict[str, Any], *, ai: bool = False, commit: bool = True) -> MarketingContent:
    campaign = _get(session, campaign_id)
    if campaign.status not in EDITABLE + ("paused",):
        raise ConflictError("Pause the campaign before adding content.")
    channel = data.get("channel")
    if channel not in CHANNELS:
        raise ValidationError("Content is for Instagram or WhatsApp.")
    c = MarketingContent(campaign_id=campaign.id, channel=channel, hashtags=[], variables=[], metrics={}, ai_generated=ai, status="draft")
    _apply_content(session, c, data)
    session.add(c)
    if channel not in (campaign.channels or []):
        campaign.channels = list(campaign.channels or []) + [channel]
    session.flush()
    if commit:
        session.commit()
    return c


def update_content(session: Session, content_id: uuid.UUID, data: Dict[str, Any], by: Optional[str] = None) -> Dict[str, Any]:
    try:
        begin_write(session)
        c = _content(session, content_id, lock=True)
        campaign = _get(session, c.campaign_id)
        if c.status not in ("draft", "scheduled", "failed") or campaign.status not in EDITABLE + ("paused",):
            raise ConflictError("Pause the campaign before changing its content." if c.status in ("draft", "scheduled") else "This has already gone out.")
        _apply_content(session, c, data)
        c.version += 1
        if c.status == "failed":
            c.status, c.error, c.attempts = "draft", None, 0
        if campaign.status == "review":
            campaign.status = "draft"
        session.commit()
    except Exception:
        session.rollback()
        raise
    return content_view(session, c, with_preview=True)


def remove_content(session: Session, content_id: uuid.UUID) -> None:
    c = _content(session, content_id)
    if c.status not in ("draft", "failed", "cancelled"):
        raise ConflictError("Only content that has not gone out can be removed.")
    session.delete(c)
    session.commit()


# ---------------------------------------------------------------------------
# Readiness, approval and control
# ---------------------------------------------------------------------------


def _template(session: Session, name: Optional[str], language: Optional[str]) -> Optional[WhatsappTemplate]:
    if not name:
        return None
    stmt = select(WhatsappTemplate).where(WhatsappTemplate.name == name)
    if language:
        stmt = stmt.where(WhatsappTemplate.language == language)
    return session.execute(stmt.limit(1)).scalar_one_or_none()


def readiness(session: Session, campaign: MarketingCampaign) -> List[Dict[str, Any]]:
    """What must be fixed before approval (``block``) and what to know (``warn``)."""
    out: List[Dict[str, Any]] = []
    add = lambda level, text: out.append({"level": level, "text": text})  # noqa: E731
    if not campaign.contents:
        add("block", "Add at least one Instagram post or WhatsApp message.")
    ig_conn = settings_service.get(session, settings_service.INSTAGRAM)
    cfg = policy.config(session)
    for c in campaign.contents:
        if c.status not in ("draft", "scheduled", "failed"):
            continue
        if c.channel == "instagram":
            if c.media_id is None:
                add("block", "The Instagram post needs an image.")
            if not ig_conn.enabled:
                add("block", "Connect Instagram in Marketing → Channels before this post can go out.")
            if not cfg.get("public_url"):
                add("block", "Set the public address (Settings → Marketing) so Instagram can fetch the image.")
            if not (c.caption or "").strip():
                add("warn", "The Instagram post has no caption.")
        if c.channel == "whatsapp":
            tpl = _template(session, c.template_name, c.template_language)
            if not c.template_name:
                add("block", "Choose an approved WhatsApp template for the broadcast.")
            elif tpl is None:
                add("warn", "Template {} is not in the synced list; sync templates to check it is approved.".format(c.template_name))
            else:
                if tpl.status != "APPROVED":
                    add("block", "Template {} is {} at Meta; only approved templates can be sent.".format(tpl.name, tpl.status.lower()))
                if tpl.category != "MARKETING":
                    add("warn", "Template {} is a {} template; promotions should use a marketing template.".format(tpl.name, tpl.category.lower()))
                if tpl.variable_count != len(c.variables or []):
                    add("block", "Template {} needs {} value(s); {} given.".format(tpl.name, tpl.variable_count, len(c.variables or [])))
                if tpl.header == "IMAGE" and c.media_id is None:
                    add("block", "Template {} has an image header; add an image.".format(tpl.name))
            if not settings_service.get(session, settings_service.WHATSAPP).enabled:
                add("block", "WhatsApp is not switched on (Settings → WhatsApp).")
    if "whatsapp" in (campaign.channels or []):
        ids = audiences.resolve(session, _definition(session, campaign))
        reach = sum(1 for v in policy.eligibility(session, "whatsapp", ids).values() if v is None)
        if not ids:
            add("block", "The audience is empty.")
        elif reach == 0:
            add("block", "Nobody in the audience has agreed to WhatsApp marketing yet.")
        elif reach < len(ids):
            add("warn", "{} of {} can be messaged; the rest have no consent, opted out, or got enough messages lately.".format(reach, len(ids)))
    if campaign.budget is not None and cost_of(session, campaign) > float(campaign.budget):
        add("warn", "Spend is over the budget.")
    return out


def submit(session: Session, campaign_id: uuid.UUID, by: Optional[str] = None) -> Dict[str, Any]:
    """Ask for approval (or approve straight away when the policy allows it)."""
    campaign = _get(session, campaign_id, lock=True)
    if campaign.status not in ("draft", "paused"):
        raise ConflictError("Only a draft can be sent for approval.")
    blocks = [c["text"] for c in readiness(session, campaign) if c["level"] == "block"]
    if blocks:
        raise ValidationError(" ".join(blocks))
    campaign.status, campaign.submitted_at = "review", _now()
    log(session, "person", "submitted", "Sent for approval by {}.".format(by or "someone"), campaign_id=campaign.id)
    session.commit()
    return get(session, campaign_id)


def approve(session: Session, campaign_id: uuid.UUID, by: str, auto: bool = False) -> Dict[str, Any]:
    """Approve: every piece of content is scheduled (now, if it has no time)."""
    try:
        begin_write(session)
        campaign = _get(session, campaign_id, lock=True)
        if campaign.status not in ("review",) and not (auto and campaign.status == "draft"):
            raise ConflictError("Only a campaign waiting for approval can be approved.")
        blocks = [c["text"] for c in readiness(session, campaign) if c["level"] == "block"]
        if blocks:
            raise ValidationError(" ".join(blocks))
        now = _now()
        for c in campaign.contents:
            if c.status in ("draft", "failed"):
                c.status = "scheduled"
                c.scheduled_at = c.scheduled_at or campaign.starts_at or now
                c.error, c.attempts = None, 0
        campaign.status, campaign.approved_by, campaign.approved_at = "approved", by, now
        log(session, "rule" if auto else "person", "approved", "Approved by {}{}.".format(by, " (automatic approval policy)" if auto else ""),
            level="success", campaign_id=campaign.id)
        from . import controls

        controls.log(session, None, "marketing_approve", "campaign", str(campaign.id), "Campaign {} approved by {}".format(campaign.name, by))
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get(session, campaign_id)


def reject(session: Session, campaign_id: uuid.UUID, by: str, reason: Optional[str]) -> Dict[str, Any]:
    campaign = _get(session, campaign_id, lock=True)
    if campaign.status != "review":
        raise ConflictError("Only a campaign waiting for approval can be sent back.")
    campaign.status = "draft"
    log(session, "person", "rejected", "Sent back by {}: {}".format(by, reason or "no reason given"), level="warning", campaign_id=campaign.id)
    session.commit()
    return get(session, campaign_id)


def pause(session: Session, campaign_id: uuid.UUID, by: Optional[str] = None) -> Dict[str, Any]:
    campaign = _get(session, campaign_id, lock=True)
    if campaign.status not in ("approved", "running"):
        raise ConflictError("Only an approved or running campaign can be paused.")
    campaign.status = "paused"
    log(session, "person", "paused", "Paused by {}. Nothing more goes out until it is approved again.".format(by or "someone"),
        level="warning", campaign_id=campaign.id)
    session.commit()
    return get(session, campaign_id)


def cancel(session: Session, campaign_id: uuid.UUID, by: Optional[str] = None) -> Dict[str, Any]:
    campaign = _get(session, campaign_id, lock=True)
    if campaign.status in ("completed", "cancelled"):
        raise ConflictError("The campaign is already {}.".format(campaign.status))
    for c in campaign.contents:
        if c.status in ("draft", "scheduled", "sending"):
            c.status = "cancelled"
    session.execute(sa_update(MarketingSend).where(MarketingSend.campaign_id == campaign.id, MarketingSend.status == "queued")
                    .values(status="skipped", skip_reason="Campaign cancelled"))
    campaign.status = "cancelled"
    log(session, "person", "cancelled", "Cancelled by {}.".format(by or "someone"), level="warning", campaign_id=campaign.id)
    session.commit()
    return get(session, campaign_id)


def duplicate(session: Session, campaign_id: uuid.UUID, by: Optional[str] = None) -> Dict[str, Any]:
    src = _get(session, campaign_id)
    copy = create(session, {"name": src.name + " (copy)", "objective": src.objective, "channels": src.channels,
                            "audience_id": str(src.audience_id) if src.audience_id else None, "audience": src.audience,
                            "product_ids": src.product_ids, "offer": src.offer, "brief": src.brief}, by=by, commit=False)
    for c in src.contents:
        session.add(MarketingContent(campaign_id=copy.id, channel=c.channel, caption=c.caption, hashtags=list(c.hashtags or []),
                                     template_name=c.template_name, template_language=c.template_language,
                                     variables=list(c.variables or []), media_id=c.media_id, status="draft", metrics={}))
    session.commit()
    return get(session, copy.id)


# ---------------------------------------------------------------------------
# Rendering messages
# ---------------------------------------------------------------------------


def _link(session: Session, campaign: MarketingCampaign, customer: Optional[Customer]) -> str:
    base = policy.config(session).get("public_url") or ""
    if not base:
        return ""
    if customer is not None and customer.portal_token:
        return "{}/e/{}?c={}".format(base, customer.portal_token, campaign.code)
    return base


def _fill(session: Session, text: str, campaign: MarketingCampaign, customer: Optional[Customer]) -> str:
    products = session.execute(select(Product.name).where(Product.id.in_([uuid.UUID(i) for i in (campaign.product_ids or [])[:3]]))).scalars().all()
    name = (customer.name if customer else "Customer").strip()
    city = ""
    values = {
        "name": name, "first_name": name.split()[0] if name else "there", "product": ", ".join(products) or "our products",
        "offer": campaign.offer or "", "link": _link(session, campaign, customer),
        "business": policy.config(session).get("brand_name") or settings_service.get(session, settings_service.AI).config.get("agent_name") or "us",
        "city": city,
    }
    out = text
    for key, value in values.items():
        out = out.replace("{" + key + "}", value)
    return out.strip() or "-"


def render_whatsapp(session: Session, c: MarketingContent, customer: Optional[Customer]) -> Dict[str, Any]:
    """The template's body with this customer's values filled in."""
    campaign = c.campaign
    values = [_fill(session, v, campaign, customer) for v in (c.variables or [])]
    tpl = _template(session, c.template_name, c.template_language)
    body = tpl.body if tpl else ""
    for i, v in enumerate(values, start=1):
        body = body.replace("{{%d}}" % i, v)
    return {"values": values, "text": body, "template": c.template_name, "header": tpl.header if tpl else None,
            "footer": tpl.footer if tpl else None}


# ---------------------------------------------------------------------------
# The executor
# ---------------------------------------------------------------------------


def _start_broadcast(session: Session, c: MarketingContent) -> int:
    """Create one send row per audience member: queued, or skipped with the reason."""
    campaign = c.campaign
    ids = audiences.resolve(session, _definition(session, campaign))
    reasons = policy.eligibility(session, "whatsapp", ids)
    country = settings_service.get(session, settings_service.WHATSAPP).config.get("country_code") or "91"
    from . import whatsapp

    phones = dict(session.execute(select(Customer.id, Customer.phone).where(Customer.id.in_(ids))).all()) if ids else {}
    existing = set(session.execute(select(MarketingSend.customer_id).where(MarketingSend.content_id == c.id)).scalars())
    seen_numbers: set = set()
    queued = 0
    for cid in ids:
        if cid in existing:
            continue
        to = whatsapp.recipient(phones.get(cid), country)
        why = reasons.get(cid)
        if why is None and to in seen_numbers:
            why = "Same number as another customer in this broadcast"
        session.add(MarketingSend(campaign_id=campaign.id, content_id=c.id, customer_id=cid, to=to,
                                  status="queued" if why is None else "skipped", skip_reason=why))
        if why is None:
            seen_numbers.add(to)
            queued += 1
    c.status = "sending"
    log(session, "executor", "broadcast_started", "WhatsApp broadcast started: {} to send, {} skipped.".format(queued, len(ids) - queued),
        campaign_id=campaign.id, content_id=c.id, data={"queued": queued, "audience": len(ids)})
    return queued


def _send_batch(session: Session, limit: int) -> int:
    from . import whatsapp

    wa = settings_service.get(session, settings_service.WHATSAPP)
    token = settings_service.credentials(wa).get("access_token")
    rows = session.execute(
        select(MarketingSend).join(MarketingContent, MarketingContent.id == MarketingSend.content_id)
        .join(MarketingCampaign, MarketingCampaign.id == MarketingSend.campaign_id)
        .where(MarketingSend.status == "queued", MarketingContent.status == "sending", MarketingCampaign.status.in_(("approved", "running")))
        .order_by(MarketingSend.queued_at).limit(limit).with_for_update(skip_locked=True, of=MarketingSend)
    ).scalars().all()
    if not rows:
        return 0
    if not (wa.enabled and token and wa.config.get("phone_number_id")):
        return 0
    cap = policy.over_cap(session, [r.customer_id for r in rows])
    outs = {r.customer_id for r in rows} - policy.opted_in(session, "whatsapp", [r.customer_id for r in rows])
    sent = 0
    for send in rows:
        if send.customer_id in outs:
            send.status, send.skip_reason = "skipped", "Opted out or consent withdrawn before sending"
            continue
        if send.customer_id in cap:
            send.status, send.skip_reason = "skipped", "Frequency cap reached before sending"
            continue
        content = session.get(MarketingContent, send.content_id)
        customer = session.get(Customer, send.customer_id)
        rendered = render_whatsapp(session, content, customer)
        image = media.public_url(session, content.media) if content.media is not None else None
        send.attempts += 1
        send.status = "sending"
        session.flush()
        try:
            send.wamid = whatsapp.send_template(wa.config, token, send.to, content.template_name, rendered["values"],
                                                language=content.template_language, header_image=image if rendered["header"] == "IMAGE" else None) or None
            send.status, send.sent_at, send.error = "sent", _now(), None
            sent += 1
        except whatsapp.SendError as exc:
            code = getattr(exc, "code", None)
            if code in NO_RETRY_CODES or send.attempts >= SEND_TRIES:
                send.status, send.failed_at, send.error = "failed", _now(), str(exc)[:500]
            else:
                send.status, send.error = "queued", str(exc)[:500]
            if code in (190, 10, 200):  # token or permission problem: stop this round
                log(session, "executor", "whatsapp_auth", "WhatsApp refused the access token: {}".format(exc), level="error",
                    campaign_id=send.campaign_id, content_id=send.content_id)
                session.commit()
                return sent
        session.commit()
    return sent


def _finish_broadcasts(session: Session) -> None:
    for c in session.execute(select(MarketingContent).where(MarketingContent.status == "sending")).scalars().all():
        left = session.execute(select(func.count()).select_from(MarketingSend).where(
            MarketingSend.content_id == c.id, MarketingSend.status.in_(("queued", "sending")))).scalar_one()
        if left == 0:
            counts = dict(session.execute(select(MarketingSend.status, func.count()).where(MarketingSend.content_id == c.id).group_by(MarketingSend.status)).all())
            c.status = "sent"
            log(session, "executor", "broadcast_done", "WhatsApp broadcast finished: {} sent, {} failed, {} skipped.".format(
                sum(v for k, v in counts.items() if k in STATUS_ORDER), counts.get("failed", 0), counts.get("skipped", 0)),
                level="success", campaign_id=c.campaign_id, content_id=c.id, data=counts)
    session.commit()


def _publish_one(session: Session, c: MarketingContent) -> None:
    from . import instagram

    conn = instagram.connection(session)
    campaign = c.campaign
    if not conn["enabled"]:
        c.error = "Instagram is not connected."
        return
    row = c.media
    url = media.public_url(session, row) if row is not None else None
    if not url:
        c.status, c.error = "failed", "No image, or the public address is not set (Settings → Marketing)."
        log(session, "executor", "publish_failed", c.error, level="error", campaign_id=campaign.id, content_id=c.id)
        return
    caption = "\n\n".join(x for x in [(c.caption or "").strip(), " ".join(c.hashtags or [])] if x)
    c.status, c.attempts = "publishing", c.attempts + 1
    session.commit()  # claim it: the next tick will not pick it up again
    try:
        if not c.container_id:
            left = instagram.quota_left(session, conn)["left"]
            if left <= 0:
                c.status, c.error = "scheduled", "Instagram's daily publishing limit is used up; it will go out when the limit resets."
                c.scheduled_at = _now() + timedelta(hours=1)
                log(session, "executor", "quota", c.error, level="warning", campaign_id=campaign.id, content_id=c.id)
                return
            c.container_id = instagram.create_container(conn, url, caption)
            session.commit()
        state = instagram.container_status(conn, c.container_id)
        if state == "IN_PROGRESS":
            c.status = "scheduled"
            return
        if state in ("ERROR", "EXPIRED"):
            c.container_id = None
            raise instagram.InstagramError("Instagram could not prepare the image ({}).".format(state.lower()), transient=state == "EXPIRED")
        result = instagram.publish_container(conn, c.container_id)
        c.status, c.external_id, c.permalink, c.published_at, c.error = "published", result["id"], result.get("permalink"), _now(), None
        log(session, "executor", "published", "Posted on Instagram.", level="success", campaign_id=campaign.id, content_id=c.id,
            data={"permalink": result.get("permalink")})
    except instagram.InstagramError as exc:
        c.error = str(exc)[:500]
        if exc.token_broken:
            c.status = "scheduled"
            settings_service.record_system(session, settings_service.INSTAGRAM, last_error=str(exc))
            log(session, "executor", "instagram_auth", "Instagram access token expired or was revoked; reconnect Instagram. Publishing is paused.",
                level="error", campaign_id=campaign.id, content_id=c.id)
        elif exc.transient and c.attempts < PUBLISH_TRIES:
            c.status, c.scheduled_at = "scheduled", _now() + timedelta(minutes=5 * c.attempts)
            log(session, "executor", "retry", "Instagram failed for now ({}); trying again in {} min.".format(exc, 5 * c.attempts),
                level="warning", campaign_id=campaign.id, content_id=c.id)
        else:
            c.status = "failed"
            log(session, "executor", "publish_failed", str(exc), level="error", campaign_id=campaign.id, content_id=c.id)


def _complete_campaigns(session: Session) -> None:
    now = _now()
    for campaign in session.execute(select(MarketingCampaign).where(MarketingCampaign.status.in_(("approved", "running")))).scalars().all():
        states = [c.status for c in campaign.contents]
        if any(s in ("sending", "publishing") for s in states) or any(s == "published" or s == "sent" for s in states):
            if campaign.status == "approved":
                campaign.status = "running"
                log(session, "executor", "running", "Campaign is live.", campaign_id=campaign.id)
        if states and all(s in TERMINAL_CONTENT for s in states) and (campaign.ends_at is None or campaign.ends_at <= now):
            campaign.status, campaign.completed_at = "completed", now
            log(session, "executor", "completed", "Campaign finished.", level="success", campaign_id=campaign.id)
    session.commit()


def tick(session: Session) -> Dict[str, int]:
    """Publish and send whatever is due. Safe to run often and in parallel."""
    now = _now()
    cfg = policy.config(session)
    published = started = 0
    due = session.execute(
        select(MarketingContent).join(MarketingCampaign, MarketingCampaign.id == MarketingContent.campaign_id)
        .where(MarketingContent.status == "scheduled", MarketingContent.scheduled_at <= now, MarketingCampaign.status.in_(("approved", "running")))
        .order_by(MarketingContent.scheduled_at).limit(20).with_for_update(skip_locked=True, of=MarketingContent)
    ).scalars().all()
    for c in due:
        if c.channel == "instagram":
            _publish_one(session, c)
            published += 1 if c.status == "published" else 0
        elif c.channel == "whatsapp":
            _start_broadcast(session, c)
            started += 1
        session.commit()
    sent = 0
    if not policy.quiet_now(cfg):
        sent = _send_batch(session, int(cfg.get("send_per_minute") or 60))
    _finish_broadcasts(session)
    _complete_campaigns(session)
    return {"published": published, "broadcasts_started": started, "sent": sent}


# ---------------------------------------------------------------------------
# What comes back: delivery receipts, replies, opt-outs
# ---------------------------------------------------------------------------


def on_statuses(session: Session, statuses: List[Dict[str, Any]]) -> int:
    changed = 0
    for st in statuses:
        send = session.execute(select(MarketingSend).where(MarketingSend.wamid == st["wamid"])).scalar_one_or_none()
        if send is None:
            continue
        at = st.get("at") or _now()
        status = st["status"]
        if status == "failed":
            send.status, send.failed_at = "failed", at
            send.error = "{} (code {})".format(st.get("error") or "Not delivered", st.get("error_code")) if st.get("error_code") else (st.get("error") or "Not delivered")
        elif status in STATUS_ORDER and STATUS_ORDER[status] > STATUS_ORDER.get(send.status, -1):
            send.status = status
        if status == "delivered":
            send.delivered_at = send.delivered_at or at
        if status == "read":
            send.read_at = send.read_at or at
            send.delivered_at = send.delivered_at or at
        if (st.get("pricing") or {}).get("billable") and send.cost is None:
            send.cost = Decimal(str(policy.config(session).get("message_cost") or 0))
        changed += 1
    session.commit()
    return changed


def on_inbound(session: Session, customer: Customer, text: str) -> Optional[str]:
    """A customer wrote on WhatsApp. Records an opt-out (returns "opt_out") or
    marks their latest campaign message as replied (returns None: the message
    still goes to TAI)."""
    if policy.is_opt_out(session, text):
        policy.set_consent(session, customer.id, "whatsapp", "opted_out", source="whatsapp_keyword", evidence=text[:200])
        log(session, "engagement", "opt_out", "{} opted out of WhatsApp marketing.".format(customer.name), level="warning")
        session.commit()
        return "opt_out"
    since = _now() - timedelta(days=7)
    send = session.execute(select(MarketingSend).where(
        MarketingSend.customer_id == customer.id, MarketingSend.status.in_(("sent", "delivered", "read")), MarketingSend.sent_at >= since,
    ).order_by(MarketingSend.sent_at.desc()).limit(1)).scalar_one_or_none()
    if send is not None:
        send.status, send.replied_at = "replied", _now()
        send.read_at = send.read_at or send.replied_at
        log(session, "engagement", "reply", "{} replied to the campaign: {}".format(customer.name, text[:140]),
            campaign_id=send.campaign_id, content_id=send.content_id)
        session.commit()
    return None


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


def attribute(session: Session, days_back: int = 60) -> int:
    """Count orders and enquiries towards the latest campaign message the
    customer got before them (within the attribution window)."""
    window = int(policy.config(session).get("attribution_days") or 14)
    since = _now() - timedelta(days=days_back)
    made = 0
    sends = session.execute(select(MarketingSend).where(MarketingSend.sent_at.is_not(None), MarketingSend.sent_at >= since - timedelta(days=window),
                                                        MarketingSend.status.in_(("sent", "delivered", "read", "replied")))).scalars().all()
    by_customer: Dict[uuid.UUID, List[MarketingSend]] = {}
    for s in sends:
        by_customer.setdefault(s.customer_id, []).append(s)
    if not by_customer:
        return 0
    done_orders = set(session.execute(select(MarketingConversion.sales_order_id).where(MarketingConversion.sales_order_id.is_not(None))).scalars())
    done_enq = set(session.execute(select(MarketingConversion.enquiry_id).where(MarketingConversion.enquiry_id.is_not(None))).scalars())

    def latest(customer_id: uuid.UUID, at: datetime) -> Optional[MarketingSend]:
        hits = [s for s in by_customer.get(customer_id, []) if s.sent_at <= at <= s.sent_at + timedelta(days=window)]
        return max(hits, key=lambda s: s.sent_at) if hits else None

    for order in session.execute(select(SalesOrder).where(SalesOrder.created_at >= since, SalesOrder.status != OrderStatus.CANCELLED,
                                                          SalesOrder.customer_id.in_(list(by_customer)))).scalars():
        if order.id in done_orders:
            continue
        s = latest(order.customer_id, order.created_at)
        if s is not None:
            session.add(MarketingConversion(campaign_id=s.campaign_id, customer_id=order.customer_id, sales_order_id=order.id,
                                            value=order.total_amount or 0, reason="reply" if s.replied_at and s.replied_at <= order.created_at else "after_message",
                                            at=order.created_at))
            made += 1
    for enq in session.execute(select(CustomerEnquiry).where(CustomerEnquiry.created_at >= since, CustomerEnquiry.customer_id.in_(list(by_customer)))).scalars():
        if enq.id in done_enq:
            continue
        s = latest(enq.customer_id, enq.created_at)
        if s is not None:
            session.add(MarketingConversion(campaign_id=s.campaign_id, customer_id=enq.customer_id, enquiry_id=enq.id, value=0,
                                            reason="reply" if s.replied_at and s.replied_at <= enq.created_at else "after_message", at=enq.created_at))
            made += 1
    session.commit()
    return made


def conversions(session: Session, campaign_id: uuid.UUID) -> List[Dict[str, Any]]:
    rows = session.execute(select(MarketingConversion, Customer.name).outerjoin(Customer, Customer.id == MarketingConversion.customer_id)
                           .where(MarketingConversion.campaign_id == campaign_id).order_by(MarketingConversion.at.desc())).all()
    numbers = dict(session.execute(select(SalesOrder.id, SalesOrder.order_number).where(
        SalesOrder.id.in_([r.sales_order_id for r, _ in rows if r.sales_order_id] or [uuid.uuid4()]))).all())
    why = {"reply": "Replied to the message, then", "after_message": "Within the attribution window after the message"}
    return [{"id": r.id, "customer_id": r.customer_id, "customer": name, "order_id": r.sales_order_id, "order_number": numbers.get(r.sales_order_id),
             "enquiry_id": r.enquiry_id, "value": float(r.value or 0), "reason": r.reason, "why": why.get(r.reason, r.reason), "at": r.at}
            for r, name in rows]


def sends(session: Session, campaign_id: uuid.UUID, status: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
    stmt = (select(MarketingSend, Customer.name).join(Customer, Customer.id == MarketingSend.customer_id)
            .where(MarketingSend.campaign_id == campaign_id).order_by(MarketingSend.queued_at.desc()).limit(limit))
    if status:
        stmt = stmt.where(MarketingSend.status == status)
    return [{"id": s.id, "customer_id": s.customer_id, "customer": name, "to": s.to, "status": s.status, "skip_reason": s.skip_reason,
             "error": s.error, "sent_at": s.sent_at, "delivered_at": s.delivered_at, "read_at": s.read_at, "replied_at": s.replied_at}
            for s, name in session.execute(stmt).all()]


# ---------------------------------------------------------------------------
# Dashboard, analytics and calendar
# ---------------------------------------------------------------------------


def calendar(session: Session, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    rows = session.execute(
        select(MarketingContent, MarketingCampaign).join(MarketingCampaign, MarketingCampaign.id == MarketingContent.campaign_id)
        .where(or_(and_(MarketingContent.scheduled_at >= start, MarketingContent.scheduled_at < end),
                   and_(MarketingContent.published_at >= start, MarketingContent.published_at < end)),
               MarketingCampaign.status != "cancelled")
    ).all()
    out = []
    for c, campaign in rows:
        out.append({"id": c.id, "campaign_id": campaign.id, "campaign": campaign.name, "campaign_status": campaign.status,
                    "channel": c.channel, "status": c.status, "at": c.published_at or c.scheduled_at,
                    "title": (c.caption or c.template_name or campaign.name or "")[:80],
                    "thumb": media.view(session, c.media)["url"] if c.media is not None else None})
    out.sort(key=lambda r: r["at"])
    return out


def analytics(session: Session, days: int = 30) -> Dict[str, Any]:
    since = _now() - timedelta(days=days)
    cfg = policy.config(session)
    per = float(cfg.get("message_cost") or 0)
    counts = dict(session.execute(select(MarketingSend.status, func.count()).where(MarketingSend.queued_at >= since).group_by(MarketingSend.status)).all())
    funnel = _funnel(counts)
    conv_rows = session.execute(select(MarketingConversion).where(MarketingConversion.at >= since)).scalars().all()
    revenue = sum(float(r.value or 0) for r in conv_rows)
    orders = sum(1 for r in conv_rows if r.sales_order_id)
    enquiries = sum(1 for r in conv_rows if r.enquiry_id)
    campaigns = session.execute(select(MarketingCampaign).where(or_(MarketingCampaign.created_at >= since, MarketingCampaign.status.in_(("running", "approved"))))).scalars().all()
    spend = sum(float(c.spend or 0) for c in campaigns) + per * funnel["delivered"]
    posts = session.execute(select(MarketingContent).where(MarketingContent.channel == "instagram", MarketingContent.published_at >= since)).scalars().all()
    ig = {k: sum(int((p.metrics or {}).get(k) or 0) for p in posts) for k in ("reach", "views", "likes", "comments", "saved", "shares")}
    ig["posts"] = len(posts)
    ig["engagement_rate"] = round((ig["likes"] + ig["comments"] + ig["saved"] + ig["shares"]) / ig["reach"], 4) if ig["reach"] else None
    # Daily series: messages sent and revenue attributed.
    series: Dict[str, Dict[str, float]] = {}
    for day in range(days):
        key = (since + timedelta(days=day + 1)).date().isoformat()
        series[key] = {"sent": 0, "read": 0, "revenue": 0.0, "reach": 0}
    for sent_at, read_at in session.execute(select(MarketingSend.sent_at, MarketingSend.read_at).where(MarketingSend.sent_at >= since)).all():
        k = sent_at.date().isoformat()
        if k in series:
            series[k]["sent"] += 1
            if read_at:
                series[k]["read"] += 1
    for r in conv_rows:
        k = r.at.date().isoformat()
        if k in series:
            series[k]["revenue"] += float(r.value or 0)
    for p in posts:
        k = p.published_at.date().isoformat()
        if k in series:
            series[k]["reach"] += int((p.metrics or {}).get("reach") or 0)
    # Best hour to message: read rate by local hour sent.
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(cfg.get("timezone") or "Asia/Kolkata")
    hours: Dict[int, List[int]] = {}
    for sent_at, read_at in session.execute(select(MarketingSend.sent_at, MarketingSend.read_at).where(MarketingSend.sent_at >= since - timedelta(days=60))).all():
        h = sent_at.astimezone(zone).hour
        hours.setdefault(h, [0, 0])
        hours[h][0] += 1
        hours[h][1] += 1 if read_at else 0
    best = sorted(((h, v[1] / v[0], v[0]) for h, v in hours.items() if v[0] >= 5), key=lambda x: -x[1])
    table = []
    conv_by = _conversions(session, [c.id for c in campaigns])
    counts_by = _send_counts(session, [c.id for c in campaigns])
    for c in campaigns:
        f = _funnel(counts_by.get(c.id, {}))
        conv = conv_by.get(c.id, {"orders": 0, "enquiries": 0, "revenue": 0.0})
        cost = round(float(c.spend or 0) + per * f["delivered"], 2)
        table.append({"id": c.id, "name": c.name, "status": c.status, "channels": c.channels, "objective": c.objective, **f,
                      "orders": conv["orders"], "enquiries": conv["enquiries"], "revenue": conv["revenue"], "cost": cost,
                      "roi": round((conv["revenue"] - cost) / cost, 2) if cost > 0 else None,
                      "read_rate": round(f["read"] / f["delivered"], 3) if f["delivered"] else None})
    table.sort(key=lambda r: -r["revenue"])
    return {
        "days": days, "funnel": funnel, "orders": orders, "enquiries": enquiries, "revenue": round(revenue, 2), "spend": round(spend, 2),
        "roi": round((revenue - spend) / spend, 2) if spend > 0 else None, "instagram": ig,
        "channels": [
            {"channel": "whatsapp", "reach": funnel["delivered"], "engaged": funnel["read"], "replies": funnel["replied"], "revenue": round(revenue, 2)},
            {"channel": "instagram", "reach": ig["reach"], "engaged": ig["likes"] + ig["comments"] + ig["saved"] + ig["shares"],
             "replies": ig["comments"], "revenue": None},
        ],
        "series": [{"day": k, **v} for k, v in series.items()],
        "best_hours": [{"hour": h, "read_rate": round(rate, 3), "sent": n} for h, rate, n in best[:5]],
        "campaigns": table,
    }


def dashboard(session: Session) -> Dict[str, Any]:
    from . import instagram

    a = analytics(session, 30)
    consents = dict(session.execute(select(MarketingConsentStatus.status, func.count()).where(MarketingConsentStatus.channel == "whatsapp")
                                    .group_by(MarketingConsentStatus.status)).all())
    customers = session.execute(select(func.count()).select_from(Customer).where(Customer.is_active.is_(True))).scalar_one()
    active = session.execute(select(MarketingCampaign).where(MarketingCampaign.status.in_(("approved", "running", "review", "paused")))
                             .order_by(MarketingCampaign.updated_at.desc()).limit(12)).scalars().all()
    opps = session.execute(select(MarketingOpportunity).where(MarketingOpportunity.status == "new")
                           .order_by(MarketingOpportunity.score.desc(), MarketingOpportunity.created_at.desc()).limit(8)).scalars().all()
    from . import marketing_agents

    ig = settings_service.get(session, settings_service.INSTAGRAM)
    wa = settings_service.get(session, settings_service.WHATSAPP)
    comments_open = session.execute(select(func.count()).select_from(InstagramComment).where(
        InstagramComment.reply_status.in_(("none", "draft")), InstagramComment.hidden.is_(False))).scalar_one()
    upcoming = calendar(session, _now(), _now() + timedelta(days=14))[:8]
    return {
        "kpis": {"revenue": a["revenue"], "orders": a["orders"], "enquiries": a["enquiries"], "spend": a["spend"], "roi": a["roi"],
                 "sent": a["funnel"]["sent"], "read": a["funnel"]["read"], "replied": a["funnel"]["replied"],
                 "reach": a["instagram"]["reach"], "engagement_rate": a["instagram"]["engagement_rate"],
                 "active_campaigns": sum(1 for c in active if c.status in ("approved", "running")),
                 "waiting_approval": sum(1 for c in active if c.status == "review")},
        "series": a["series"], "channels": a["channels"],
        "consent": {"opted_in": consents.get("opted_in", 0), "opted_out": consents.get("opted_out", 0), "customers": customers},
        "campaigns": [view(session, c) for c in active],
        "opportunities": [marketing_agents.opportunity_view(session, o) for o in opps],
        "upcoming": upcoming,
        "connections": {
            "instagram": {"connected": bool(ig.enabled and settings_service.credentials(ig).get("access_token")), "username": ig.config.get("username"),
                          "error": ig.config.get("last_error") or None, "quota": ig.config.get("publish_quota"), "used": ig.config.get("publish_used")},
            "whatsapp": {"connected": bool(wa.enabled and settings_service.credentials(wa).get("access_token")),
                         "approved_templates": session.execute(select(func.count()).select_from(WhatsappTemplate).where(
                             WhatsappTemplate.status == "APPROVED", WhatsappTemplate.category == "MARKETING")).scalar_one()},
        },
        "comments_waiting": comments_open,
        "problems": events(session, limit=5, level="error"),
        "insight": marketing_agents.latest_insight(session),
    }


# Imported late to avoid a cycle in type checkers.
from ..models import MarketingConsent as MarketingConsentStatus  # noqa: E402
