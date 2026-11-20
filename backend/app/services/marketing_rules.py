"""Marketing automations: when something happens in the business, do something.

A rule = trigger (+ its settings) -> action, with an approval policy and a
cooldown. Triggers reuse the Strategist's detectors, so a rule and the
opportunities on the marketing home see the business the same way.

Actions:
- ``suggest``: add the opportunity to the marketing home;
- ``draft_campaign``: also build a draft campaign with content, ready to approve;
- ``auto_campaign``: build it and approve it automatically, but only when
  Settings → Marketing allows automatic approval and the audience is small
  enough; otherwise it waits for approval like a draft;
- ``create_task``: a follow-up for a person (e.g. call the quiet customers).

Per-customer triggers (quiet customers, birthdays, open quotes) skip anyone
this rule already reached within its cooldown.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import NotFoundError, ValidationError
from ..models import MarketingCampaign, MarketingOpportunity, MarketingRule, MarketingSend
from . import marketing
from . import marketing_agents as agents
from . import marketing_audiences as audiences
from . import marketing_policy as policy

logger = logging.getLogger(__name__)

#: Every trigger: label, help, settings (key, label, type, default).
TRIGGERS: Dict[str, Dict[str, Any]] = {
    "new_product": {"label": "A new product is added", "detector": "new_product",
                    "fields": [{"key": "days", "label": "Added in the last (days)", "type": "number", "default": 14}]},
    "back_in_stock": {"label": "A product comes back in stock", "detector": "back_in_stock",
                      "fields": [{"key": "days", "label": "Received in the last (days)", "type": "number", "default": 7}]},
    "excess_stock": {"label": "Stock is slow or not selling", "detector": "excess_stock",
                     "fields": [{"key": "min_value", "label": "Stock worth at least (₹)", "type": "number", "default": 5000},
                                {"key": "min_days", "label": "Oldest stock at least (days)", "type": "number", "default": 45}]},
    "near_expiry": {"label": "Batches are near expiry", "detector": "near_expiry",
                    "fields": [{"key": "days", "label": "Expiring within (days)", "type": "number", "default": 45}]},
    "new_category": {"label": "A new category is introduced", "detector": "new_category",
                     "fields": [{"key": "days", "label": "First product added in the last (days)", "type": "number", "default": 30}]},
    "occasion": {"label": "A festival or season is coming", "detector": "occasion", "fields": []},
    "inactive_customers": {"label": "Customers stop ordering", "detector": "inactive_customers", "per_customer": True,
                           "fields": [{"key": "days", "label": "No order for (days)", "type": "number", "default": 90},
                                      {"key": "min_orders", "label": "Who ordered at least (times)", "type": "number", "default": 2}]},
    "birthday": {"label": "Birthdays and anniversaries", "detector": "birthday", "per_customer": True,
                 "fields": [{"key": "days", "label": "Coming up within (days)", "type": "number", "default": 7}]},
    "open_enquiries": {"label": "A quote is not turned into an order", "detector": "open_enquiries", "per_customer": True,
                       "fields": [{"key": "days", "label": "Quote older than (days)", "type": "number", "default": 7}]},
    "falling_sales": {"label": "A product's sales are falling", "detector": "falling_sales",
                      "fields": [{"key": "drop_percent", "label": "Drop of at least (%)", "type": "number", "default": 40}]},
    "rising_interest": {"label": "More enquiries for a category", "detector": "rising_interest",
                        "fields": [{"key": "rise_percent", "label": "Rise of at least (%)", "type": "number", "default": 50},
                                   {"key": "days", "label": "Compared over (days)", "type": "number", "default": 14}]},
    "purchase_made": {"label": "A customer made a purchase", "per_customer": True,
                      "fields": [{"key": "after_days", "label": "Days after the order", "type": "number", "default": 7}]},
    "schedule": {"label": "On a schedule", "fields": [
        {"key": "weekday", "label": "Day", "type": "choice", "choices": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "default": "mon"},
        {"key": "hour", "label": "Hour (0-23)", "type": "number", "default": 10}]},
}
ACTIONS = {
    "suggest": "Suggest it on the marketing home",
    "draft_campaign": "Prepare a draft campaign for approval",
    "auto_campaign": "Prepare and run the campaign (within the automatic approval policy)",
    "create_task": "Create a follow-up for a person",
}
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

DEFAULT_RULES = [
    {"name": "Win back quiet customers", "trigger": "inactive_customers", "conditions": {"days": 90, "min_orders": 2}, "action": "draft_campaign",
     "action_config": {"channels": ["whatsapp"]}, "cooldown_days": 30},
    {"name": "Launch new products", "trigger": "new_product", "conditions": {"days": 14}, "action": "draft_campaign",
     "action_config": {"channels": ["instagram", "whatsapp"], "image": "card"}, "cooldown_days": 60},
    {"name": "Clear stock near expiry", "trigger": "near_expiry", "conditions": {"days": 45}, "action": "draft_campaign",
     "action_config": {"channels": ["whatsapp", "instagram"]}, "cooldown_days": 14},
    {"name": "Move slow stock", "trigger": "excess_stock", "conditions": {"min_value": 10000, "min_days": 60}, "action": "suggest", "cooldown_days": 21},
    {"name": "Festival greetings and offers", "trigger": "occasion", "conditions": {}, "action": "draft_campaign",
     "action_config": {"channels": ["instagram", "whatsapp"]}, "cooldown_days": 7},
    {"name": "Birthday wishes", "trigger": "birthday", "conditions": {"days": 3}, "action": "draft_campaign",
     "action_config": {"channels": ["whatsapp"]}, "cooldown_days": 300},
    {"name": "Thank and cross-sell after a purchase", "trigger": "purchase_made", "conditions": {"after_days": 7}, "action": "suggest", "cooldown_days": 30},
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def catalogue() -> Dict[str, Any]:
    return {"triggers": [{"key": k, "label": v["label"], "fields": v["fields"], "per_customer": bool(v.get("per_customer"))} for k, v in TRIGGERS.items()],
            "actions": [{"key": k, "label": v} for k, v in ACTIONS.items()]}


def ensure_defaults(session: Session) -> None:
    if session.execute(select(MarketingRule.id).limit(1)).first():
        return
    for item in DEFAULT_RULES:
        session.add(MarketingRule(**{"approval": "approval", "is_active": True, "action_config": {}, **item}))
    session.commit()


def view(session: Session, r: MarketingRule) -> Dict[str, Any]:
    t = TRIGGERS.get(r.trigger, {})
    return {"id": r.id, "name": r.name, "trigger": r.trigger, "trigger_label": t.get("label", r.trigger), "conditions": r.conditions or {},
            "action": r.action, "action_label": ACTIONS.get(r.action, r.action), "action_config": r.action_config or {},
            "approval": r.approval, "cooldown_days": r.cooldown_days, "is_active": r.is_active, "last_run_at": r.last_run_at,
            "last_result": r.last_result, "runs": r.runs, "updated_at": r.updated_at}


def list_rules(session: Session) -> List[Dict[str, Any]]:
    ensure_defaults(session)
    return [view(session, r) for r in session.execute(select(MarketingRule).order_by(MarketingRule.created_at)).scalars()]


def _clean(data: Dict[str, Any]) -> Dict[str, Any]:
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValidationError("Give the automation a name.")
    trigger = data.get("trigger")
    if trigger not in TRIGGERS:
        raise ValidationError("Choose what starts the automation.")
    action = data.get("action") or "draft_campaign"
    if action not in ACTIONS:
        raise ValidationError("Choose what the automation does.")
    conditions: Dict[str, Any] = {}
    for field in TRIGGERS[trigger]["fields"]:
        value = (data.get("conditions") or {}).get(field["key"], field["default"])
        if field["type"] == "number":
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValidationError("{} must be a number.".format(field["label"]))
            if value < 0:
                raise ValidationError("{} cannot be negative.".format(field["label"]))
            value = int(value) if value == int(value) else value
        elif field["type"] == "choice" and value not in field["choices"]:
            raise ValidationError("Choose a value for {}.".format(field["label"]))
        conditions[field["key"]] = value
    config = dict(data.get("action_config") or {})
    channels = [c for c in config.get("channels") or ["whatsapp"] if c in marketing.CHANNELS]
    config["channels"] = channels or ["whatsapp"]
    config["image"] = config.get("image") if config.get("image") in ("card", "ai", "none") else "card"
    if config.get("audience_id"):
        config["audience_id"] = str(uuid.UUID(str(config["audience_id"])))
    config["offer"] = (config.get("offer") or "").strip() or None
    try:
        cooldown = int(data.get("cooldown_days", 30))
    except (TypeError, ValueError):
        raise ValidationError("Cooldown must be a whole number of days.")
    return {"name": name[:120], "trigger": trigger, "action": action, "conditions": conditions, "action_config": config,
            "approval": "auto" if action == "auto_campaign" else "approval", "cooldown_days": max(0, min(cooldown, 365)),
            "is_active": bool(data.get("is_active", True))}


def save(session: Session, data: Dict[str, Any], rule_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    clean = _clean(data)
    row = session.get(MarketingRule, rule_id) if rule_id else MarketingRule()
    if row is None:
        raise NotFoundError("Automation not found.")
    for k, v in clean.items():
        setattr(row, k, v)
    if rule_id is None:
        session.add(row)
    session.commit()
    return view(session, row)


def delete(session: Session, rule_id: uuid.UUID) -> None:
    row = session.get(MarketingRule, rule_id)
    if row is None:
        raise NotFoundError("Automation not found.")
    session.delete(row)
    session.commit()


# ---------------------------------------------------------------------------
# Running rules
# ---------------------------------------------------------------------------


def _reached_recently(session: Session, rule: MarketingRule) -> set:
    """Customers this rule's campaigns messaged within its cooldown."""
    since = _now() - timedelta(days=rule.cooldown_days or 0)
    return set(session.execute(select(MarketingSend.customer_id).join(MarketingCampaign, MarketingCampaign.id == MarketingSend.campaign_id)
                               .where(MarketingCampaign.created_by == "rule:{}".format(rule.id), MarketingSend.queued_at >= since)).scalars())


def _purchase_made(session: Session, cond: Dict[str, Any]) -> List[Dict[str, Any]]:
    from ..models import OrderStatus, SalesOrder

    after = int(cond.get("after_days") or 7)
    day_start = _now() - timedelta(days=after + 1)
    rows = session.execute(select(SalesOrder.customer_id).where(SalesOrder.created_at >= day_start, SalesOrder.created_at < day_start + timedelta(days=1),
                                                                SalesOrder.status != OrderStatus.CANCELLED).distinct()).scalars().all()
    if not rows:
        return []
    return [{"kind": "cross_sell", "key": "purchase_made:{}".format(day_start.date().isoformat()),
             "title": "Thank {} customer{} who bought {} days ago".format(len(rows), "s" if len(rows) != 1 else "", after),
             "why": "{} customer{} ordered on {}. A thank-you with related products brings repeat orders.".format(
                 len(rows), "s" if len(rows) != 1 else "", day_start.strftime("%d %b")),
             "product_ids": [], "audience": {"only": [str(c) for c in rows]},
             "objective": "loyalty", "channels": ["whatsapp"], "score": 40, "value": None, "data": {"customers": len(rows)},
             "customer_ids": [str(c) for c in rows]}]


def _schedule_due(rule: MarketingRule, cond: Dict[str, Any]) -> List[Dict[str, Any]]:
    from zoneinfo import ZoneInfo

    local = _now().astimezone(ZoneInfo("Asia/Kolkata"))
    if WEEKDAYS[local.weekday()] != cond.get("weekday") or local.hour < int(cond.get("hour") or 0):
        return []
    key = "schedule:{}:{}".format(rule.id, local.date().isoformat())
    return [{"kind": "occasion", "key": key, "title": rule.name, "why": "Scheduled automation “{}”.".format(rule.name),
             "product_ids": [], "audience": {}, "objective": "sales", "channels": (rule.action_config or {}).get("channels") or ["whatsapp"],
             "score": 40, "value": None, "data": {}}]


def detect(session: Session, rule: MarketingRule) -> List[Dict[str, Any]]:
    cond = dict(rule.conditions or {})
    if rule.trigger == "purchase_made":
        return _purchase_made(session, cond)
    if rule.trigger == "schedule":
        return _schedule_due(rule, cond)
    detector = agents.DETECTORS[TRIGGERS[rule.trigger]["detector"]]
    import inspect

    accepted = set(inspect.signature(detector).parameters) - {"session"}
    return detector(session, **{k: v for k, v in cond.items() if k in accepted})


def run_rule(session: Session, rule: MarketingRule, force: bool = False) -> Dict[str, Any]:
    if not force and rule.last_run_at and _now() - rule.last_run_at < timedelta(hours=6):
        return {"skipped": "ran recently"}
    found = detect(session, rule)
    cfg = rule.action_config or {}
    per_customer = bool(TRIGGERS.get(rule.trigger, {}).get("per_customer"))
    done: List[str] = []
    for item in found:
        base_key = item["key"][:160]
        key = "rule:{}:{}".format(rule.id, item["key"])[:160]
        item = {**item, "key": key, "channels": cfg.get("channels") or item.get("channels")}
        if per_customer:
            reached = _reached_recently(session, rule)
            ids = [uuid.UUID(c) for c in item.get("customer_ids") or []] or audiences.resolve(session, item.get("audience"))
            fresh = [str(c) for c in ids if c not in reached]
            if not fresh:
                continue
            item["audience"] = {"only": fresh}
        if cfg.get("audience_id"):
            item["audience_id"] = cfg["audience_id"]
        # This automation already handled it: nothing to do.
        if session.execute(select(MarketingOpportunity.id).where(MarketingOpportunity.dedupe_key == key)).first():
            continue
        # If the Strategist already listed this and nobody acted yet, the automation takes it over.
        opp = session.execute(select(MarketingOpportunity).where(MarketingOpportunity.dedupe_key == base_key,
                                                                MarketingOpportunity.status == "new")).scalar_one_or_none()
        if opp is not None:
            opp.source, opp.audience, opp.channels = "rule:{}".format(rule.name)[:40], item.get("audience") or opp.audience, item["channels"]
            session.flush()
        else:
            opp = agents.record(session, item, source="rule:{}".format(rule.name)[:40])
        if opp is None:
            continue
        session.commit()
        if rule.action == "suggest":
            done.append("suggested “{}”".format(opp.title))
        elif rule.action == "create_task":
            from . import tasks

            tasks.create_task(session, title=opp.title[:200], notes="{}\n\nAudience: {}".format(opp.why, audiences.describe(session, opp.audience)))
            opp.status = "accepted"
            session.commit()
            done.append("follow-up “{}”".format(opp.title))
        else:
            campaign = agents.accept(session, opp.id, by="rule:{}".format(rule.id), image=cfg.get("image") or "card")
            row = session.get(MarketingCampaign, campaign["id"])
            row.created_by = "rule:{}".format(rule.id)
            if cfg.get("offer"):
                row.offer = cfg["offer"]
            if cfg.get("audience_id"):
                row.audience_id = uuid.UUID(cfg["audience_id"])
            session.commit()
            done.append(_maybe_auto(session, rule, row))
    rule.last_run_at, rule.runs = _now(), rule.runs + 1
    rule.last_result = "; ".join(done) if done else "Nothing new."
    if done:
        marketing.log(session, "rule", "rule_ran", "Automation “{}”: {}.".format(rule.name, rule.last_result))
    session.commit()
    return {"rule": rule.name, "done": done}


def _maybe_auto(session: Session, rule: MarketingRule, campaign: MarketingCampaign) -> str:
    """Approve automatically only when every switch allows it; else ask for approval."""
    cfg = policy.config(session)
    title = "“{}”".format(campaign.name)
    if rule.action != "auto_campaign":
        return "drafted {} for approval".format(title)
    blocks = [c["text"] for c in marketing.readiness(session, campaign) if c["level"] == "block"]
    size = len(audiences.resolve(session, marketing._definition(session, campaign)))
    reason = None
    if cfg.get("approval") != "auto":
        reason = "automatic approval is off in Settings → Marketing"
    elif size > int(cfg.get("auto_max_audience") or 0):
        reason = "audience of {} is over the automatic limit of {}".format(size, cfg.get("auto_max_audience"))
    elif blocks:
        reason = blocks[0]
    if reason:
        try:
            if not blocks:
                marketing.submit(session, campaign.id, by="rule:{}".format(rule.name))
        except Exception:
            session.rollback()
        marketing.log(session, "rule", "needs_approval", "{} waits for approval: {}.".format(title, reason), level="warning", campaign_id=campaign.id)
        session.commit()
        return "drafted {} (needs approval: {})".format(title, reason)
    marketing.approve(session, campaign.id, by="rule:{}".format(rule.name), auto=True)
    return "started {}".format(title)


def run_all(session: Session, force: bool = False) -> Dict[str, Any]:
    ensure_defaults(session)
    out = []
    for rule in session.execute(select(MarketingRule).where(MarketingRule.is_active.is_(True))).scalars().all():
        try:
            out.append(run_rule(session, rule, force=force))
        except Exception as exc:
            session.rollback()
            logger.exception("Marketing rule %s failed", rule.name)
            rule = session.get(MarketingRule, rule.id)
            rule.last_result = "Failed: {}".format(str(exc)[:300])
            rule.last_run_at = _now()
            marketing.log(session, "rule", "rule_failed", "Automation “{}” failed: {}".format(rule.name, str(exc)[:300]), level="error")
            session.commit()
    return {"rules": out}


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------


def tick() -> int:
    """Background: send/publish what is due every tick; scan, rules, sync,
    attribution and the weekly review when they are due."""
    from . import inbound, marketing_channels

    session = inbound.session_factory()
    done = 0
    try:
        jobs = [("executor", lambda: marketing.tick(session)), ("strategist", lambda: agents.scan(session)),
                ("rules", lambda: run_all(session)), ("attribution", lambda: _attribute_if_due(session)),
                ("sync", lambda: _sync_if_due(session, marketing_channels)), ("analyst", lambda: agents.analyse(session))]
        for name, job in jobs:
            try:
                result = job()
                done += 1 if result else 0
            except Exception:
                session.rollback()
                logger.exception("Marketing job %s failed", name)
    finally:
        session.close()
    return done


_last_attribution: Optional[datetime] = None


def _attribute_if_due(session: Session) -> int:
    global _last_attribution
    if _last_attribution and _now() - _last_attribution < timedelta(minutes=15):
        return 0
    _last_attribution = _now()
    return marketing.attribute(session)


def _sync_if_due(session: Session, channels) -> Dict[str, Any]:
    from . import integration_settings as settings_service

    last = policy.config(session).get("last_sync_at")
    if last:
        try:
            if _now() - datetime.fromisoformat(last) < timedelta(hours=2):
                return {}
        except ValueError:
            pass
    settings_service.record_system(session, settings_service.MARKETING, last_sync_at=_now().isoformat())
    return channels.sync_instagram(session)
