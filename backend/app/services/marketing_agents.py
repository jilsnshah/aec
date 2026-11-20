"""The marketing agents.

- Strategist: looks across stock, sales, batches, customers and the calendar
  and records opportunities (what to promote, to whom, on which channel, why).
  The detectors are plain code over ERP figures, so every opportunity is
  explainable; Gemini only words the advice.
- Creative: writes the Instagram caption and hashtags, fills a WhatsApp
  template, draws a product card and (when asked) an AI image, following the
  brand kit.
- Engagement: sorts Instagram comments by intent and drafts replies.
- Analyst: reads results each week and writes what worked and what to change.

Agents only create drafts and records. Nothing they make is published or
sent until the campaign is approved (by a person, or by the automatic policy
a person switched on). Without Gemini they fall back to clearly labelled
templates so the module still works.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import (
    Batch, Customer, CustomerEnquiry, CustomerEnquiryItem, InstagramComment, MarketingCampaign, MarketingContent, MarketingEvent,
    MarketingOpportunity, MarketingSend, Product, WhatsappTemplate,
)
from . import integration_settings as settings_service
from . import marketing
from . import marketing_audiences as audiences
from . import marketing_media as media
from . import marketing_policy as policy

logger = logging.getLogger(__name__)

KINDS = {
    "new_product": "New product", "back_in_stock": "Back in stock", "excess_stock": "Slow or excess stock",
    "near_expiry": "Batches near expiry", "falling_sales": "Sales falling", "rising_interest": "Rising interest",
    "inactive_customers": "Customers going quiet", "occasion": "Festival or season", "birthday": "Birthdays and anniversaries",
    "new_category": "New category", "open_enquiries": "Open enquiries", "cross_sell": "Bought together",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _week() -> str:
    y, w, _ = _now().isocalendar()
    return "{}-W{:02d}".format(y, w)


# ---------------------------------------------------------------------------
# Talking to Gemini
# ---------------------------------------------------------------------------

#: Tests replace this: (session, system, prompt) -> dict or None.
llm_json: Optional[Callable[[Session, str, str], Optional[Dict[str, Any]]]] = None


def ai_available(session: Session) -> bool:
    return llm_json is not None or settings_service.ai_credentials(session) is not None


def _ask(session: Session, system: str, prompt: str) -> Optional[Dict[str, Any]]:
    """Ask Gemini for a JSON object. None when Gemini is not connected or fails."""
    if llm_json is not None:
        return llm_json(session, system, prompt)
    creds = settings_service.ai_credentials(session)
    if creds is None:
        return None
    from langchain_core.messages import HumanMessage, SystemMessage

    from ..ai import provider

    model_name = settings_service.get(session, settings_service.AI).config.get("model") or settings_service.default_model()
    try:
        model = provider.gemini(model_name.replace("models/", "", 1), creds, temperature=0.7)
        reply = model.invoke([SystemMessage(content=system), HumanMessage(content=prompt)])
    except Exception as exc:  # network, quota, model errors
        logger.warning("Marketing agent call failed: %s", exc)
        marketing.log(session, "creative", "ai_error", "Gemini could not answer: {}".format(str(exc)[:200]), level="warning")
        return None
    text = reply.content if isinstance(reply.content, str) else "".join(
        part.get("text", "") if isinstance(part, dict) else str(part) for part in reply.content)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except ValueError:
        return None


def _brand(session: Session) -> Dict[str, Any]:
    cfg = policy.config(session)
    ai = settings_service.get(session, settings_service.AI).config
    return {"name": cfg.get("brand_name") or "", "tone": cfg.get("brand_tone"), "hashtags": cfg.get("brand_hashtags") or [],
            "avoid": cfg.get("brand_avoid") or "", "signature": cfg.get("brand_signature") or "",
            "about": settings_service.company_knowledge(session)[:2500], "agent": ai.get("agent_name")}


# ---------------------------------------------------------------------------
# Strategist: opportunity detectors
# ---------------------------------------------------------------------------


def _products(session: Session, ids: List[uuid.UUID]) -> Dict[uuid.UUID, Product]:
    if not ids:
        return {}
    return {p.id: p for p in session.execute(select(Product).where(Product.id.in_(ids))).scalars()}


def _health(session: Session) -> List[Dict[str, Any]]:
    from . import insights

    return [p for p in insights.inventory_health(session)["products"] if p.get("is_active", True)]


def _buyers(product_ids: List[str], days: Optional[int] = 365) -> Dict[str, Any]:
    return {"products": {"ids": product_ids, "mode": "bought", "within_days": days}}


def detect_new_products(session: Session, days: int = 14) -> List[Dict[str, Any]]:
    since = _now() - timedelta(days=days)
    out = []
    for p in session.execute(select(Product).where(Product.is_active.is_(True), Product.created_at >= since, Product.physical_stock > 0)).scalars():
        audience = {"categories": {"names": [p.category], "mode": "bought", "within_days": 365}} if p.category else {}
        out.append({"kind": "new_product", "key": "new_product:{}".format(p.id), "title": "Launch {}".format(p.name),
                    "why": "{} was added {} days ago and {} {} are in stock. Customers who buy {} are the natural first audience.".format(
                        p.name, (_now() - p.created_at).days, _q(p.physical_stock), p.unit_of_measure, p.category or "similar products"),
                    "product_ids": [str(p.id)], "audience": audience, "objective": "launch", "channels": ["instagram", "whatsapp"],
                    "score": 70, "value": None, "data": {"stock": float(p.physical_stock)}})
    return out


def detect_back_in_stock(session: Session, days: int = 7) -> List[Dict[str, Any]]:
    out = []
    since = _now() - timedelta(days=days)
    for p in _health(session):
        last = p.get("last_received")
        if not last or last < since or p["free"] <= 0 or p.get("sold_90_days", 0) <= 0:
            continue
        out.append({"kind": "back_in_stock", "key": "back_in_stock:{}:{}".format(p["product_id"], last.date().isoformat()),
                    "title": "{} is back in stock".format(p["name"]),
                    "why": "{} {} arrived on {} and {} are free to sell. It sold {} in the last 90 days, so past buyers are likely to want it.".format(
                        _q(p["physical"]), p["unit"], last.strftime("%d %b"), _q(p["free"]), _q(p["sold_90_days"])),
                    "product_ids": [str(p["product_id"])], "audience": _buyers([str(p["product_id"])]), "objective": "sales",
                    "channels": ["whatsapp"], "score": 60, "value": None, "data": {"free": p["free"]}})
    return out


def detect_excess_stock(session: Session, min_value: float = 5000, min_days: int = 45) -> List[Dict[str, Any]]:
    out = []
    for p in _health(session):
        if not ({"dead", "slow"} & set(p["flags"])) or p["stock_value"] < min_value or (p.get("oldest_stock_days") or 0) < min_days:
            continue
        dead = "dead" in p["flags"]
        out.append({"kind": "excess_stock", "key": "excess_stock:{}:{}".format(p["product_id"], _week()),
                    "title": "Clear {} ({})".format(p["name"], "not selling" if dead else "slow"),
                    "why": "₹{:,.0f} of {} is in stock; the oldest has waited {} days and it sold {} {} in 30 days. A limited offer frees the cash.".format(
                        p["stock_value"], p["name"], p.get("oldest_stock_days") or 0, _q(p.get("sold_30_days") or 0), p["unit"]),
                    "product_ids": [str(p["product_id"])],
                    "audience": _buyers([str(p["product_id"])], 730) if (p.get("sold_90_days") or 0) > 0 else ({"categories": {"names": [p["category"]], "mode": "bought", "within_days": 365}} if p.get("category") else {}),
                    "objective": "clearance", "channels": ["instagram", "whatsapp"],
                    "score": min(95, 40 + p["stock_value"] / 2000), "value": p["stock_value"], "data": {"stock_value": p["stock_value"], "oldest_days": p.get("oldest_stock_days")}})
    return out


def detect_near_expiry(session: Session, days: int = 45) -> List[Dict[str, Any]]:
    from . import batches

    rows = [r for r in batches.stock(session, None, days) if r["quantity"] > 0 and r.get("days_left") is not None and r["days_left"] >= 0]
    by_product: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_product.setdefault(str(r["product_id"]), []).append(r)
    out = []
    for pid, items in by_product.items():
        soonest = min(items, key=lambda r: r["days_left"])
        qty = sum(r["quantity"] for r in items)
        value = sum(r.get("value") or 0 for r in items)
        out.append({"kind": "near_expiry", "key": "near_expiry:{}:{}".format(pid, soonest["batch_id"]),
                    "title": "Sell {} before it expires".format(soonest["product"]),
                    "why": "{} {} in {} batch(es) expire within {} days (first: batch {} on {}). Worth ₹{:,.0f} at cost.".format(
                        _q(qty), soonest["unit"], len(items), days, soonest["number"], soonest["expires_on"], value),
                    "product_ids": [pid], "audience": _buyers([pid], 730), "objective": "clearance", "channels": ["whatsapp", "instagram"],
                    "score": 90 - soonest["days_left"], "value": value, "data": {"quantity": qty, "days_left": soonest["days_left"]}})
    return out


def detect_falling_sales(session: Session, drop_percent: float = 40) -> List[Dict[str, Any]]:
    out = []
    for p in _health(session):
        prev, now = p.get("sold_prev_30_days") or 0, p.get("sold_30_days") or 0
        if prev <= 0 or p["free"] <= 0:
            continue
        drop = (prev - now) / prev * 100
        if drop < drop_percent:
            continue
        out.append({"kind": "falling_sales", "key": "falling_sales:{}:{}".format(p["product_id"], _week()),
                    "title": "Revive {}".format(p["name"]),
                    "why": "Sales fell {:.0f}% ({} → {} {} in the last 30 days) while {} are in stock. Remind past buyers.".format(
                        drop, _q(prev), _q(now), p["unit"], _q(p["free"])),
                    "product_ids": [str(p["product_id"])], "audience": _buyers([str(p["product_id"])]), "objective": "sales",
                    "channels": ["whatsapp"], "score": 45 + min(drop, 50) / 2, "value": None, "data": {"drop_percent": round(drop, 1)}})
    return out


def detect_rising_interest(session: Session, rise_percent: float = 50, days: int = 14) -> List[Dict[str, Any]]:
    now = _now()
    rows = session.execute(select(Product.category, CustomerEnquiry.created_at).join(CustomerEnquiryItem, CustomerEnquiryItem.enquiry_id == CustomerEnquiry.id)
                           .join(Product, Product.id == CustomerEnquiryItem.product_id)
                           .where(CustomerEnquiry.created_at >= now - timedelta(days=2 * days), Product.category.is_not(None))).all()
    counts: Dict[str, List[int]] = {}
    for category, at in rows:
        c = counts.setdefault(category, [0, 0])
        c[0 if at >= now - timedelta(days=days) else 1] += 1
    out = []
    for category, (recent, before) in counts.items():
        if recent < 3 or (before and (recent - before) / before * 100 < rise_percent):
            continue
        out.append({"kind": "rising_interest", "key": "rising_interest:{}:{}".format(category, _week()),
                    "title": "More people are asking about {}".format(category),
                    "why": "{} enquiries for {} in the last {} days against {} before. Promote it while interest is high.".format(recent, category, days, before),
                    "product_ids": [], "audience": {"categories": {"names": [category], "mode": "bought", "within_days": 730}},
                    "objective": "sales", "channels": ["instagram", "whatsapp"], "score": 55 + min(recent, 20), "value": None,
                    "data": {"recent": recent, "before": before, "category": category}})
    return out


def detect_inactive_customers(session: Session, days: int = 90, min_orders: int = 2) -> List[Dict[str, Any]]:
    from . import groups

    figures = groups.metrics(session)
    ids = [cid for cid, f in figures.items() if (f.get("days_since_last_order") or 0) >= days and f.get("orders_total", 0) >= min_orders]
    if len(ids) < 1:
        return []
    value = sum(figures[c]["spend_12m"] for c in ids)
    return [{"kind": "inactive_customers", "key": "inactive_customers:{}:{}".format(days, _week()),
             "title": "Win back {} quiet customer{}".format(len(ids), "s" if len(ids) != 1 else ""),
             "why": "{} customers who ordered at least {} times have not ordered for {}+ days. They spent ₹{:,.0f} in the last 12 months.".format(
                 len(ids), min_orders, days, value),
             "product_ids": [], "audience": {"rules": [{"field": "days_since_last_order", "op": ">=", "value": days},
                                                      {"field": "orders_total", "op": ">=", "value": min_orders}], "match": "all"},
             "objective": "reactivation", "channels": ["whatsapp"], "score": 50 + min(len(ids), 40), "value": value,
             "data": {"customers": len(ids)}, "customer_ids": [str(c) for c in ids]}]


def detect_occasions(session: Session) -> List[Dict[str, Any]]:
    today = _now().date()
    out = []
    for occ in policy.config(session).get("occasions") or []:
        try:
            day = date.fromisoformat(occ["date"])
        except (KeyError, ValueError):
            continue
        until = (day - today).days
        if 0 <= until <= int(occ.get("lead_days") or 7):
            out.append({"kind": "occasion", "key": "occasion:{}:{}".format(occ["name"], occ["date"]),
                        "title": "{} in {} day{}".format(occ["name"], until, "" if until == 1 else "s"),
                        "why": "{} is on {}. Plan greetings and a festive offer now so posts and messages go out on time.".format(
                            occ["name"], day.strftime("%d %b %Y")),
                        "product_ids": [], "audience": {}, "objective": "festival", "channels": ["instagram", "whatsapp"],
                        "score": 85 - until, "value": None, "data": {"date": occ["date"], "name": occ["name"]}})
    return out


def detect_birthdays(session: Session, days: int = 7) -> List[Dict[str, Any]]:
    out = []
    for kind in ("birthday", "anniversary"):
        ids = audiences.resolve(session, {"occasion": {"kind": kind, "within_days": days}})
        if ids:
            out.append({"kind": "birthday", "key": "{}:{}".format(kind, _week()),
                        "title": "{} {}{} this week".format(len(ids), kind, "s" if len(ids) != 1 else ""),
                        "why": "{} customer{} {} a {} in the next {} days. A personal greeting builds loyalty.".format(
                            len(ids), "s" if len(ids) != 1 else "", "have" if len(ids) != 1 else "has", kind, days),
                        "product_ids": [], "audience": {"occasion": {"kind": kind, "within_days": days}}, "objective": "greeting",
                        "channels": ["whatsapp"], "score": 50, "value": None, "data": {"customers": len(ids)}})
    return out


def detect_new_categories(session: Session, days: int = 30) -> List[Dict[str, Any]]:
    since = _now() - timedelta(days=days)
    rows = session.execute(select(Product.category, func.min(Product.created_at), func.count()).where(Product.category.is_not(None), Product.is_active.is_(True))
                           .group_by(Product.category)).all()
    return [{"kind": "new_category", "key": "new_category:{}".format(cat), "title": "Introduce the new {} range".format(cat),
             "why": "{} is a new category ({} product{} added since {}). Tell customers it is available.".format(cat, n, "s" if n != 1 else "", first.strftime("%d %b")),
             "product_ids": [str(p) for p in session.execute(select(Product.id).where(Product.category == cat).limit(5)).scalars()],
             "audience": {}, "objective": "launch", "channels": ["instagram", "whatsapp"], "score": 65, "value": None, "data": {"category": cat}}
            for cat, first, n in rows if first and first >= since]


def detect_open_enquiries(session: Session, days: int = 7) -> List[Dict[str, Any]]:
    from ..models import EnquiryStatus

    since = _now() - timedelta(days=30)
    ids = session.execute(select(CustomerEnquiry.customer_id).where(CustomerEnquiry.status == EnquiryStatus.OPEN, CustomerEnquiry.customer_id.is_not(None),
                                                                   CustomerEnquiry.created_at >= since, CustomerEnquiry.created_at <= _now() - timedelta(days=days))
                          .distinct()).scalars().all()
    if not ids:
        return []
    return [{"kind": "open_enquiries", "key": "open_enquiries:{}".format(_week()), "title": "Follow up {} open quote{}".format(len(ids), "s" if len(ids) != 1 else ""),
             "why": "{} customer{} asked for prices more than {} days ago and have not ordered. A friendly nudge converts some of them.".format(
                 len(ids), "s" if len(ids) != 1 else "", days),
             "product_ids": [], "audience": {"open_enquiry": True}, "objective": "sales", "channels": ["whatsapp"], "score": 58,
             "value": None, "data": {"customers": len(ids)}}]


DETECTORS: Dict[str, Callable[..., List[Dict[str, Any]]]] = {
    "new_product": detect_new_products, "back_in_stock": detect_back_in_stock, "excess_stock": detect_excess_stock,
    "near_expiry": detect_near_expiry, "falling_sales": detect_falling_sales, "rising_interest": detect_rising_interest,
    "inactive_customers": detect_inactive_customers, "occasion": detect_occasions, "birthday": detect_birthdays,
    "new_category": detect_new_categories, "open_enquiries": detect_open_enquiries,
}


def _q(value: Any) -> str:
    v = float(value or 0)
    return "{:,.0f}".format(v) if v == int(v) else "{:,.2f}".format(v)


def record(session: Session, found: Dict[str, Any], source: str = "strategist") -> Optional[MarketingOpportunity]:
    """Store an opportunity once (by its key)."""
    key = found["key"][:160]
    # The same subject found by the Strategist and by an automation is one opportunity.
    base = key.split(":", 2)[2] if key.startswith("rule:") and key.count(":") >= 2 else key
    if session.execute(select(MarketingOpportunity.id).where(
        (MarketingOpportunity.dedupe_key == key) | (MarketingOpportunity.dedupe_key == base)
        | (MarketingOpportunity.dedupe_key.like("rule:%:" + base.replace("%", r"\%").replace("_", r"\_"), escape="\\"))
    )).first():
        return None
    row = MarketingOpportunity(kind=found["kind"], title=found["title"][:255], why=found["why"], data=found.get("data") or {},
                               product_ids=found.get("product_ids") or [], audience=found.get("audience") or {},
                               channels=found.get("channels") or ["whatsapp"], objective=found.get("objective") or "sales",
                               score=round(float(found.get("score") or 0), 2), value_estimate=found.get("value"),
                               source=source, dedupe_key=found["key"][:160], expires_at=_now() + timedelta(days=14))
    session.add(row)
    session.flush()
    return row


def scan(session: Session, force: bool = False) -> Dict[str, Any]:
    """The Strategist's look across the business. Runs every few hours."""
    cfg = policy.config(session)
    last = cfg.get("last_scan_at")
    if not force and last:
        try:
            if _now() - datetime.fromisoformat(last) < timedelta(hours=int(cfg.get("scan_hours") or 24)):
                return {"skipped": "not due"}
        except ValueError:
            pass
    for old in session.execute(select(MarketingOpportunity).where(MarketingOpportunity.status == "new", MarketingOpportunity.expires_at < _now())).scalars():
        old.status = "expired"
    made = []
    for kind, detect in DETECTORS.items():
        try:
            for found in detect(session):
                row = record(session, found)
                if row is not None:
                    made.append(row)
        except Exception:
            session.rollback()
            logger.exception("Opportunity detector %s failed", kind)
    if made:
        marketing.log(session, "strategist", "scan", "Found {} new opportunit{}: {}.".format(
            len(made), "y" if len(made) == 1 else "ies", "; ".join(o.title for o in made[:4])), level="success")
    settings_service.record_system(session, settings_service.MARKETING, last_scan_at=_now().isoformat())
    session.commit()
    return {"found": len(made), "items": [opportunity_view(session, o) for o in made]}


def opportunity_view(session: Session, o: MarketingOpportunity) -> Dict[str, Any]:
    names = [p.name for p in _products(session, [uuid.UUID(i) for i in o.product_ids or []]).values()]
    return {"id": o.id, "kind": o.kind, "kind_label": KINDS.get(o.kind, o.kind), "title": o.title, "why": o.why, "data": o.data,
            "product_ids": o.product_ids, "products": names, "audience": o.audience, "audience_summary": audiences.describe(session, o.audience),
            "channels": o.channels, "objective": o.objective, "score": float(o.score or 0),
            "value_estimate": float(o.value_estimate) if o.value_estimate is not None else None, "status": o.status, "source": o.source,
            "campaign_id": o.campaign_id, "created_at": o.created_at, "expires_at": o.expires_at}


def opportunities(session: Session, status: Optional[str] = "new", limit: int = 50) -> List[Dict[str, Any]]:
    stmt = select(MarketingOpportunity).order_by(MarketingOpportunity.score.desc(), MarketingOpportunity.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(MarketingOpportunity.status == status)
    return [opportunity_view(session, o) for o in session.execute(stmt).scalars()]


def dismiss(session: Session, opportunity_id: uuid.UUID) -> Dict[str, Any]:
    o = session.get(MarketingOpportunity, opportunity_id)
    if o is None:
        raise NotFoundError("Opportunity not found.")
    o.status, o.decided_at = "dismissed", _now()
    session.commit()
    return opportunity_view(session, o)


def accept(session: Session, opportunity_id: uuid.UUID, by: str, image: str = "card") -> Dict[str, Any]:
    """Turn an opportunity into a draft campaign with content written by the Creative agent."""
    o = session.execute(select(MarketingOpportunity).where(MarketingOpportunity.id == opportunity_id).with_for_update()).scalar_one_or_none()
    if o is None:
        raise NotFoundError("Opportunity not found.")
    if o.campaign_id:
        return marketing.get(session, o.campaign_id)
    if o.status not in ("new", "dismissed", "expired"):
        raise ConflictError("This opportunity was already used.")
    campaign = marketing.create(session, {
        "name": o.title, "objective": o.objective if o.objective in marketing.OBJECTIVES else "sales", "channels": o.channels or ["whatsapp"],
        "audience": o.audience or {}, "product_ids": o.product_ids or [], "brief": o.why, "opportunity_id": str(o.id),
    }, by=by, commit=False)
    o.status, o.campaign_id, o.decided_at = "accepted", campaign.id, _now()
    session.commit()
    generate(session, campaign.id, image=image)
    return marketing.get(session, campaign.id)


# ---------------------------------------------------------------------------
# Creative
# ---------------------------------------------------------------------------

CREATIVE_SYSTEM = """You are the creative marketer of an Indian trading business (building materials and similar goods). \
You write short, specific, honest promotions that sell. Facts (products, prices, stock, offers) come only from the brief; \
never invent discounts, prices, dates or claims. Keep the brand's tone. Indian English; a few Hindi words are fine if the tone allows. \
Answer with one JSON object only."""


def _context(session: Session, campaign: MarketingCampaign) -> Dict[str, Any]:
    products = []
    for p in _products(session, [uuid.UUID(i) for i in campaign.product_ids or []]).values():
        products.append({"name": p.name, "brand": p.brand, "category": p.category, "unit": p.unit_of_measure,
                         "price": float(p.mrp) if p.mrp is not None else None, "in_stock": float(p.physical_stock or 0) > 0,
                         "description": (p.description or "")[:300],
                         "specs": [s for s in (p.specs or []) if isinstance(s, dict)][:6]})
    return {"campaign": campaign.name, "objective": marketing.OBJECTIVES.get(campaign.objective), "offer": campaign.offer,
            "brief": campaign.brief, "audience": audiences.describe(session, marketing._definition(session, campaign)),
            "products": products, "brand": _brand(session)}


def _approved_templates(session: Session) -> List[WhatsappTemplate]:
    return session.execute(select(WhatsappTemplate).where(WhatsappTemplate.status == "APPROVED", WhatsappTemplate.category == "MARKETING")
                           .order_by(WhatsappTemplate.name)).scalars().all()


def _fallback_copy(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Template copy used without Gemini (clearly marked as such)."""
    names = [p["name"] for p in ctx["products"]]
    product = names[0] if names else ""
    price = next((p for p in ctx["products"] if p.get("price")), None)
    offer = ctx.get("offer") or ""
    objective = ctx.get("objective") or ""
    if names:
        opener = {"New product launch": "Now available: {}.", "Clear stock": "Limited stock of {} at a special rate.",
                  "Win back customers": "We have missed you! Fresh stock of {} is ready.", "Festival / season": "Festive greetings! Stock up on {}.",
                  "Greeting": "Warm wishes from all of us.", "Thank loyal customers": "Thank you for buying from us. A little something on {}."
                  }.get(objective, "Fresh stock of {} is ready.").format(", ".join(names[:3]))
    else:
        opener = {"Win back customers": "We have missed you!", "Festival / season": "Festive greetings from all of us!",
                  "Greeting": "Warm wishes from all of us.", "Thank loyal customers": "Thank you for buying from us.",
                  "New product launch": "Something new is in stock.", "Clear stock": "A limited-time offer is on."}.get(objective, "This week's offer is here.")
    lines = [opener]
    if offer:
        lines.append(offer)
    if price:
        lines.append("₹{:,.0f} per {}.".format(price["price"], price["unit"]))
    lines.append("Message us on WhatsApp to order.")
    tags = ctx["brand"]["hashtags"][:5] + ["#" + re.sub(r"[^A-Za-z0-9]", "", w) for w in (product or "").split()[:2] if re.sub(r"[^A-Za-z0-9]", "", w)]
    return {
        "instagram": {"caption": " ".join(lines) + ("\n\n" + ctx["brand"]["signature"] if ctx["brand"]["signature"] else ""),
                      "hashtags": list(dict.fromkeys(tags))[:12],
                      "card": {"headline": product if product and objective != "Greeting" else ctx["campaign"], "subline": offer or None,
                               "badge": {"Clear stock": "Limited stock", "New product launch": "New", "Festival / season": "Festive offer"}.get(objective)},
                      "image_prompt": "{} neatly stacked in a clean, well-lit warehouse".format(product) if product else "A busy, well-organised building materials yard in warm morning light"},
        "whatsapp": {"message": " ".join(lines[:-1]) or opener, "opening": opener},
        "note": "Written from a template because Gemini is not connected. Edit freely.",
    }


def _fill_template(tpl: WhatsappTemplate, message: str, ctx: Dict[str, Any]) -> List[str]:
    """Values for a template's blanks: the first is the customer's name; the
    rest carry the message, the offer and the link."""
    n = tpl.variable_count
    values: List[str] = []
    rest = [message, ctx.get("offer") or "{link}", "{link}"]
    for i in range(n):
        values.append("{first_name}" if i == 0 and n > 1 else (rest[i - 1] if n > 1 and i - 1 < len(rest) else message))
    return values[:n]


def generate(session: Session, campaign_id: uuid.UUID, channels: Optional[List[str]] = None, instructions: Optional[str] = None,
             image: str = "card") -> Dict[str, Any]:
    """Write content for the campaign's channels: one Instagram post and/or one
    WhatsApp broadcast, as editable drafts."""
    campaign = marketing._get(session, campaign_id)
    if campaign.status not in marketing.EDITABLE + ("paused",):
        raise ConflictError("Pause the campaign before writing new content.")
    channels = [c for c in (channels or campaign.channels or ["whatsapp"]) if c in marketing.CHANNELS]
    ctx = _context(session, campaign)
    templates = _approved_templates(session)
    prompt = json.dumps({
        "brief": ctx, "extra_instructions": instructions or "",
        "whatsapp_templates": [{"name": t.name, "body": t.body, "blanks": t.variable_count, "header": t.header} for t in templates],
        "write": {
            "instagram": "caption (max 600 chars, hook in the first line, clear call to action to message on WhatsApp), "
                         "hashtags (8-15, mix of broad and local, no spaces), card {headline (max 6 words), subline (max 12 words), badge (max 3 words or null)}, "
                         "image_prompt (a photo idea without text)" if "instagram" in channels else None,
            "whatsapp": "message (max 300 chars, personal, one clear action), template (name of the best approved template or null), "
                        "values (one string per blank of that template; you may use {first_name}, {product}, {offer}, {link} which are filled per customer), "
                        "new_template_body (a marketing template body using {{1}} for the first name and {{2}} for the message, used when no template fits)"
                        if "whatsapp" in channels else None,
        },
        "format": {"instagram": {"caption": "", "hashtags": [], "card": {"headline": "", "subline": "", "badge": ""}, "image_prompt": ""},
                   "whatsapp": {"message": "", "template": "", "values": [], "new_template_body": ""}},
    }, default=str)
    answer = _ask(session, CREATIVE_SYSTEM, prompt)
    ai_written = answer is not None
    fallback = _fallback_copy(ctx)
    answer = answer or fallback
    made: List[MarketingContent] = []
    if "instagram" in channels:
        ig = answer.get("instagram") or fallback["instagram"]
        card = ig.get("card") or fallback["instagram"]["card"]
        picture = None
        if image == "ai":
            try:
                picture = media.generate_image(session, ig.get("image_prompt") or fallback["instagram"]["image_prompt"], campaign_id=campaign.id, commit=False)
            except media.ImageUnavailable as exc:
                marketing.log(session, "creative", "image_fallback", "{} A designed card was used instead.".format(exc), level="warning", campaign_id=campaign.id)
        if picture is None and image != "none":
            first = next(iter(_products(session, [uuid.UUID(i) for i in campaign.product_ids or []][:1]).values()), None)
            if first is not None and not card.get("headline"):
                picture = media.product_card(session, first, offer=campaign.offer, campaign_id=campaign.id, commit=False)
            else:
                price = next((p for p in ctx["products"] if p.get("price")), None)
                picture = media.make_card(session, headline=(card.get("headline") or campaign.name)[:60], subline=card.get("subline") or campaign.offer,
                                          badge=card.get("badge"), price="₹{:,.0f}/{}".format(price["price"], price["unit"]) if price else None,
                                          points=[p["name"] for p in ctx["products"][1:4]] or None, cta="Order on WhatsApp",
                                          campaign_id=campaign.id, commit=False)
        made.append(marketing.add_content(session, campaign.id, {
            "channel": "instagram", "caption": (ig.get("caption") or "")[:2200],
            "hashtags": (ig.get("hashtags") or [])[:30] or ctx["brand"]["hashtags"],
            "media_id": str(picture["id"]) if picture else None,
        }, ai=ai_written, commit=False))
    if "whatsapp" in channels:
        wa = answer.get("whatsapp") or fallback["whatsapp"]
        tpl = next((t for t in templates if t.name == wa.get("template")), None) or (templates[0] if templates else None)
        values = [str(v) for v in (wa.get("values") or [])] if tpl and wa.get("template") == tpl.name else []
        if tpl and len(values) != tpl.variable_count:
            values = _fill_template(tpl, wa.get("message") or fallback["whatsapp"]["message"], ctx)
        content = marketing.add_content(session, campaign.id, {
            "channel": "whatsapp", "template_name": tpl.name if tpl else None, "template_language": tpl.language if tpl else None,
            "variables": values, "caption": wa.get("message") or fallback["whatsapp"]["message"],
        }, ai=ai_written, commit=False)
        if tpl is None:
            content.error = None
            marketing.log(session, "creative", "template_needed",
                          "No approved marketing template yet. Suggested one: “{}”. Submit it from Marketing → WhatsApp.".format(
                              wa.get("new_template_body") or "Hi {{1}}, {{2}} Reply STOP to stop offers."),
                          level="warning", campaign_id=campaign.id, data={"suggested_body": wa.get("new_template_body")})
        made.append(content)
    marketing.log(session, "creative", "content_written", "{} content for {} ({}).".format(
        "Gemini wrote" if ai_written else "Template-based draft of", ", ".join(channels),
        "edit before approving" if ai_written else fallback["note"]), campaign_id=campaign.id)
    session.commit()
    return marketing.get(session, campaign.id)


def rewrite(session: Session, content_id: uuid.UUID, instructions: str) -> Dict[str, Any]:
    """Rewrite one piece following the user's instruction (shorter, Hindi, more urgent...)."""
    c = marketing._content(session, content_id)
    campaign = marketing._get(session, c.campaign_id)
    ctx = _context(session, campaign)
    current = {"caption": c.caption, "hashtags": c.hashtags, "values": c.variables, "template": c.template_name}
    answer = _ask(session, CREATIVE_SYSTEM, json.dumps({"brief": ctx, "current": current, "change": instructions,
                                                        "format": {"caption": "", "hashtags": [], "values": []}}, default=str))
    if answer is None:
        raise ValidationError("Gemini is not connected, so rewriting is not available. Edit the text directly, or connect Gemini in Settings → AI.")
    data: Dict[str, Any] = {}
    if answer.get("caption"):
        data["caption"] = str(answer["caption"])[:2200]
    if c.channel == "instagram" and answer.get("hashtags"):
        data["hashtags"] = answer["hashtags"][:30]
    if c.channel == "whatsapp" and isinstance(answer.get("values"), list) and len(answer["values"]) == len(c.variables or []):
        data["variables"] = [str(v) for v in answer["values"]]
    out = marketing.update_content(session, content_id, data)
    marketing.log(session, "creative", "rewritten", "Rewrote content: {}".format(instructions[:120]), campaign_id=campaign.id, content_id=c.id)
    session.commit()
    return out


def suggest_template(session: Session, purpose: str) -> Dict[str, Any]:
    """A marketing template body for Meta approval, with example values."""
    brand = _brand(session)
    answer = _ask(session, CREATIVE_SYSTEM, json.dumps({
        "task": "Write a WhatsApp MARKETING template body for this purpose. Use {{1}} for the customer's first name and {{2}} for the "
                "campaign-specific message. Under 500 characters. End with a short line saying they can reply STOP to stop offers. "
                "Give a lowercase_underscore name.", "purpose": purpose, "brand": brand,
        "format": {"name": "", "body": "", "examples": ["Ramesh", "Fresh OPC 53 cement at ₹385 a bag this week."], "footer": ""}}))
    if answer is None:
        return {"name": "offer_update", "body": "Hi {{1}}, {{2}}\n\nReply STOP to stop offers.", "examples": ["Ramesh", purpose or "Fresh stock is in."],
                "footer": (brand["name"] or "")[:60], "note": "Template-based suggestion (Gemini not connected)."}
    return {"name": re.sub(r"[^a-z0-9_]", "_", str(answer.get("name") or "offer_update").lower())[:60], "body": str(answer.get("body") or ""),
            "examples": [str(e) for e in answer.get("examples") or []], "footer": str(answer.get("footer") or "")[:60]}


# ---------------------------------------------------------------------------
# Engagement: Instagram comments
# ---------------------------------------------------------------------------

_BUY = re.compile(r"\b(price|rate|cost|kitna|kitne|bhav|available|stock|order|buy|deliver|delivery|dm|whatsapp|quote|how much)\b", re.I)
_PRAISE = re.compile(r"(nice|great|good|awesome|super|👍|🔥|❤|thanks|thank you|best)", re.I)
_COMPLAINT = re.compile(r"\b(bad|worst|late|broken|damaged|fraud|cheat|complaint|refund|not received|poor)\b", re.I)
_SPAM = re.compile(r"(http|www\.|follow me|check my|promo code|earn \$|crypto)", re.I)


def classify(text: str) -> str:
    if _SPAM.search(text or ""):
        return "spam"
    if _COMPLAINT.search(text or ""):
        return "complaint"
    if _BUY.search(text or "") or "?" in (text or ""):
        return "buying" if _BUY.search(text or "") else "question"
    if _PRAISE.search(text or ""):
        return "praise"
    return "other"


def draft_comment_replies(session: Session) -> int:
    rows = session.execute(select(InstagramComment).where(InstagramComment.reply_status == "none", InstagramComment.hidden.is_(False))
                           .limit(30)).scalars().all()
    brand = _brand(session)
    wa_number = policy.config(session).get("whatsapp_number") or ""
    for c in rows:
        c.intent = classify(c.text)
        if c.intent == "spam":
            continue
        answer = _ask(session, "You reply to Instagram comments for an Indian trading business. Short (max 2 sentences), warm, no prices "
                               "unless given, never argue; invite buyers to message on WhatsApp. JSON only: {\"reply\": \"\"}.",
                      json.dumps({"comment": c.text, "username": c.username, "intent": c.intent, "brand": brand}))
        reply = (answer or {}).get("reply") or {
            "buying": "Thanks for asking, @{u}! Please message us on WhatsApp{n} and we'll share today's price and delivery.",
            "question": "Thanks @{u}! Message us on WhatsApp{n} and we'll help right away.",
            "praise": "Thank you so much, @{u}! 🙏",
            "complaint": "Sorry to hear this, @{u}. Please message us on WhatsApp{n} so we can sort it out today.",
        }.get(c.intent, "Thanks for your comment, @{u}!").format(u=c.username or "there", n=(" at " + wa_number) if wa_number else "")
        c.reply_text, c.reply_status = reply[:900], "draft"
    session.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Analyst
# ---------------------------------------------------------------------------


def analyse(session: Session, force: bool = False) -> Dict[str, Any]:
    """Weekly: what worked, what did not, and what to do next."""
    cfg = policy.config(session)
    last = cfg.get("last_analysis_at")
    if not force:
        if _now().weekday() != int(cfg.get("analyst_weekday") or 0):
            return {"skipped": "not the day"}
        if last:
            try:
                if _now() - datetime.fromisoformat(last) < timedelta(days=6):
                    return {"skipped": "done this week"}
            except ValueError:
                pass
    a = marketing.analytics(session, 30)
    camps = [c for c in a["campaigns"] if c["sent"] >= 5 or c["revenue"] > 0]
    best = max(camps, key=lambda c: (c["revenue"], c["read_rate"] or 0), default=None)
    worst = min([c for c in camps if c["delivered"] >= 10], key=lambda c: c["read_rate"] or 0, default=None)
    open_opps = opportunities(session, "new", 5)
    facts = {"last_30_days": {k: a[k] for k in ("funnel", "orders", "enquiries", "revenue", "spend", "roi")}, "instagram": a["instagram"],
             "best_campaign": best, "weakest_campaign": worst, "best_hours": a["best_hours"], "open_opportunities": [o["title"] for o in open_opps]}
    answer = _ask(session, "You are a marketing analyst for an Indian trading business. Be concrete and brief; use only the numbers given. "
                           "JSON only: {\"headline\": \"\", \"points\": [\"\"], \"recommendations\": [\"\"]}.", json.dumps(facts, default=str))
    if answer is None:
        points = ["{} messages delivered, {} read, {} replies.".format(a["funnel"]["delivered"], a["funnel"]["read"], a["funnel"]["replied"]),
                  "{} orders (₹{:,.0f}) and {} enquiries came after campaign messages.".format(a["orders"], a["revenue"], a["enquiries"])]
        if a["instagram"]["posts"]:
            points.append("{} Instagram posts reached {} people.".format(a["instagram"]["posts"], a["instagram"]["reach"]))
        recs = []
        if best:
            recs.append("Repeat what worked in “{}”.".format(best["name"]))
        if worst:
            recs.append("“{}” was read by few; try a different time or first line.".format(worst["name"]))
        if a["best_hours"]:
            recs.append("Messages sent around {}:00 are read most.".format(a["best_hours"][0]["hour"]))
        if open_opps:
            recs.append("Act on: {}.".format(open_opps[0]["title"]))
        answer = {"headline": "Last 30 days: ₹{:,.0f} from campaigns{}".format(a["revenue"], " (ROI {:.1f}×)".format(a["roi"]) if a["roi"] is not None else ""),
                  "points": points, "recommendations": recs or ["Start with one of the opportunities on the marketing home."]}
    marketing.log(session, "analyst", "insight", answer.get("headline") or "Weekly marketing review", level="info",
                  data={"points": answer.get("points") or [], "recommendations": answer.get("recommendations") or [], "ai": ai_available(session)})
    settings_service.record_system(session, settings_service.MARKETING, last_analysis_at=_now().isoformat())
    session.commit()
    return latest_insight(session) or {}


def latest_insight(session: Session) -> Optional[Dict[str, Any]]:
    row = session.execute(select(MarketingEvent).where(MarketingEvent.kind == "insight").order_by(MarketingEvent.at.desc()).limit(1)).scalar_one_or_none()
    if row is None:
        return None
    return {"headline": row.message, "points": (row.data or {}).get("points") or [], "recommendations": (row.data or {}).get("recommendations") or [], "at": row.at}


def ask(session: Session, question: str) -> Dict[str, Any]:
    """Answer a marketing question from the business's own figures."""
    question = (question or "").strip()
    if not question:
        raise ValidationError("Ask a question.")
    opps = opportunities(session, "new", 10)
    a = marketing.analytics(session, 30)
    from . import insights

    health = insights.inventory_health(session)["products"]
    facts = {
        "opportunities": [{"title": o["title"], "why": o["why"], "channels": o["channels"], "audience": o["audience_summary"]} for o in opps],
        "results_30_days": {k: a[k] for k in ("funnel", "orders", "enquiries", "revenue", "spend", "roi")}, "instagram": a["instagram"],
        "best_hours": a["best_hours"], "top_campaigns": a["campaigns"][:5],
        "stock": [{"name": p["name"], "flags": p["flags"], "free": p["free"], "unit": p["unit"], "trend": p.get("demand_trend")}
                  for p in sorted(health, key=lambda p: -p["stock_value"])[:25]],
    }
    answer = _ask(session, "You are the marketing strategist of an Indian trading business. Answer the owner's question in at most 6 short "
                           "bullet points using only these facts. Name products, customer groups, channels and timing. "
                           "JSON only: {\"answer\": \"\", \"actions\": [{\"label\": \"\", \"opportunity\": \"title of an opportunity or empty\"}]}.",
                  json.dumps({"question": question, "facts": facts}, default=str))
    if answer is None:
        lines = ["- {} — {}".format(o["title"], o["why"]) for o in opps[:5]] or ["- No opportunities right now. Run a scan from the marketing home."]
        if a["best_hours"]:
            lines.append("- Best time to message: around {}:00.".format(a["best_hours"][0]["hour"]))
        answer = {"answer": "From your figures (Gemini is not connected, so this is the plain list):\n" + "\n".join(lines),
                  "actions": [{"label": "Create: " + o["title"], "opportunity": o["title"]} for o in opps[:3]]}
    by_title = {o["title"]: o["id"] for o in opps}
    actions = [{"label": x.get("label"), "opportunity_id": by_title.get(x.get("opportunity") or "")} for x in answer.get("actions") or [] if x.get("label")]
    return {"answer": answer.get("answer") or "", "actions": actions, "ai": ai_available(session)}
