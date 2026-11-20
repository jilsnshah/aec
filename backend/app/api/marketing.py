"""Marketing: home, campaigns, content, audiences, consent, channels,
automations, analytics and the agents."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ValidationError
from ..models import Customer, MarketingConsent, User
from ..services import integration_settings as settings_service
from ..services import (
    instagram, marketing, marketing_agents, marketing_audiences, marketing_channels, marketing_media, marketing_policy, marketing_rules,
)
from .auth import require_user

router = APIRouter(prefix="/api/marketing", tags=["marketing"])


# ---------------------------------------------------------------------------
# Home, opportunities and the agents
# ---------------------------------------------------------------------------


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    """KPIs for 30 days, live campaigns, opportunities, upcoming content, connections and problems."""
    return marketing.dashboard(db)


@router.get("/opportunities")
def opportunities(status: Optional[str] = "new", db: Session = Depends(get_db)):
    return {"items": marketing_agents.opportunities(db, status or None)}


@router.post("/opportunities/scan")
def scan(db: Session = Depends(get_db)):
    """Ask the Strategist to look for opportunities now."""
    return marketing_agents.scan(db, force=True)


class AcceptIn(BaseModel):
    image: str = Field(default="card", pattern="^(card|ai|none)$")


@router.post("/opportunities/{opportunity_id}/accept")
def accept(opportunity_id: uuid.UUID, payload: AcceptIn = AcceptIn(), db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Turn an opportunity into a draft campaign with content."""
    return marketing_agents.accept(db, opportunity_id, by=user.username, image=payload.image)


@router.post("/opportunities/{opportunity_id}/dismiss")
def dismiss(opportunity_id: uuid.UUID, db: Session = Depends(get_db)):
    return marketing_agents.dismiss(db, opportunity_id)


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=500)


@router.post("/ask")
def ask(payload: AskIn, db: Session = Depends(get_db)):
    """Ask the Strategist: what to promote, to whom, when."""
    return marketing_agents.ask(db, payload.question)


@router.post("/analyse")
def analyse(db: Session = Depends(get_db)):
    """The Analyst's review, now."""
    return marketing_agents.analyse(db, force=True)


@router.get("/events")
def events(campaign_id: Optional[uuid.UUID] = None, level: Optional[str] = None, limit: int = Query(100, le=500), db: Session = Depends(get_db)):
    return {"items": marketing.events(db, campaign_id, limit, level)}


@router.post("/tick")
def run_tick(db: Session = Depends(get_db)):
    """Run the executor now (publish and send whatever is due)."""
    return marketing.tick(db)


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


class CampaignIn(BaseModel):
    name: Optional[str] = None
    objective: Optional[str] = None
    channels: Optional[List[str]] = None
    audience_id: Optional[uuid.UUID] = None
    audience: Optional[Dict[str, Any]] = None
    product_ids: Optional[List[uuid.UUID]] = None
    offer: Optional[str] = None
    brief: Optional[str] = None
    notes: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    budget: Optional[float] = None
    spend: Optional[float] = None


def _data(payload: BaseModel) -> Dict[str, Any]:
    data = payload.model_dump(exclude_unset=True)
    for key in ("audience_id",):
        if key in data and data[key] is not None:
            data[key] = str(data[key])
    if data.get("product_ids") is not None:
        data["product_ids"] = [str(i) for i in data["product_ids"]]
    return data


@router.get("/campaigns")
def campaigns(status: Optional[str] = None, channel: Optional[str] = None, objective: Optional[str] = None, q: Optional[str] = None,
              db: Session = Depends(get_db)):
    return {"items": marketing.list_campaigns(db, status, channel, q, objective), "objectives": marketing.OBJECTIVES}


@router.post("/campaigns", status_code=201)
def create_campaign(payload: CampaignIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    campaign = marketing.create(db, _data(payload), by=user.username)
    return marketing.get(db, campaign.id)


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    return marketing.get(db, campaign_id)


@router.put("/campaigns/{campaign_id}")
def update_campaign(campaign_id: uuid.UUID, payload: CampaignIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return marketing.update(db, campaign_id, _data(payload), by=user.username)


@router.delete("/campaigns/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    marketing.delete(db, campaign_id)


@router.get("/campaigns/{campaign_id}/audience")
def campaign_audience(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    c = marketing._get(db, campaign_id)
    return marketing_audiences.preview(db, marketing._definition(db, c), [ch for ch in c.channels if ch in marketing_policy.CHANNELS] or ["whatsapp"])


class GenerateIn(BaseModel):
    channels: Optional[List[str]] = None
    instructions: Optional[str] = Field(default=None, max_length=1000)
    image: str = Field(default="card", pattern="^(card|ai|none)$")


@router.post("/campaigns/{campaign_id}/generate")
def generate(campaign_id: uuid.UUID, payload: GenerateIn, db: Session = Depends(get_db)):
    """Have the Creative agent write content (as editable drafts)."""
    return marketing_agents.generate(db, campaign_id, payload.channels, payload.instructions, payload.image)


class ReasonIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


@router.post("/campaigns/{campaign_id}/submit")
def submit(campaign_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return marketing.submit(db, campaign_id, by=user.username)


@router.post("/campaigns/{campaign_id}/approve")
def approve(campaign_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return marketing.approve(db, campaign_id, by=user.username)


@router.post("/campaigns/{campaign_id}/reject")
def reject(campaign_id: uuid.UUID, payload: ReasonIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return marketing.reject(db, campaign_id, by=user.username, reason=payload.reason)


@router.post("/campaigns/{campaign_id}/pause")
def pause(campaign_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return marketing.pause(db, campaign_id, by=user.username)


@router.post("/campaigns/{campaign_id}/cancel")
def cancel(campaign_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return marketing.cancel(db, campaign_id, by=user.username)


@router.post("/campaigns/{campaign_id}/duplicate", status_code=201)
def duplicate(campaign_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return marketing.duplicate(db, campaign_id, by=user.username)


@router.get("/campaigns/{campaign_id}/sends")
def campaign_sends(campaign_id: uuid.UUID, status: Optional[str] = None, db: Session = Depends(get_db)):
    return {"items": marketing.sends(db, campaign_id, status)}


@router.get("/campaigns/{campaign_id}/conversions")
def campaign_conversions(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    return {"items": marketing.conversions(db, campaign_id)}


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------


class ContentIn(BaseModel):
    channel: Optional[str] = None
    caption: Optional[str] = Field(default=None, max_length=4000)
    hashtags: Optional[List[str]] = None
    template_name: Optional[str] = None
    template_language: Optional[str] = None
    variables: Optional[List[str]] = None
    media_id: Optional[uuid.UUID] = None
    scheduled_at: Optional[datetime] = None


def _content_data(payload: ContentIn) -> Dict[str, Any]:
    data = payload.model_dump(exclude_unset=True)
    if "media_id" in data:
        data["media_id"] = str(data["media_id"]) if data["media_id"] else None
    return data


@router.post("/campaigns/{campaign_id}/contents", status_code=201)
def add_content(campaign_id: uuid.UUID, payload: ContentIn, db: Session = Depends(get_db)):
    c = marketing.add_content(db, campaign_id, _content_data(payload))
    return marketing.content_view(db, c, with_preview=True)


@router.put("/contents/{content_id}")
def update_content(content_id: uuid.UUID, payload: ContentIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return marketing.update_content(db, content_id, _content_data(payload), by=user.username)


@router.delete("/contents/{content_id}", status_code=204)
def remove_content(content_id: uuid.UUID, db: Session = Depends(get_db)):
    marketing.remove_content(db, content_id)


class RewriteIn(BaseModel):
    instructions: str = Field(min_length=2, max_length=500)


@router.post("/contents/{content_id}/rewrite")
def rewrite(content_id: uuid.UUID, payload: RewriteIn, db: Session = Depends(get_db)):
    return marketing_agents.rewrite(db, content_id, payload.instructions)


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


@router.get("/media")
def media_library(campaign_id: Optional[uuid.UUID] = None, db: Session = Depends(get_db)):
    return {"items": marketing_media.library(db, campaign_id)}


@router.post("/media/upload", status_code=201)
async def media_upload(file: UploadFile = File(...), campaign_id: Optional[str] = Form(None), db: Session = Depends(get_db)):
    raw = await file.read(marketing_media.MAX_UPLOAD + 1)
    return marketing_media.upload(db, raw, name=file.filename, campaign_id=uuid.UUID(campaign_id) if campaign_id else None)


class CardIn(BaseModel):
    headline: str = Field(min_length=1, max_length=80)
    subline: Optional[str] = Field(default=None, max_length=160)
    price: Optional[str] = Field(default=None, max_length=30)
    badge: Optional[str] = Field(default=None, max_length=24)
    points: Optional[List[str]] = None
    cta: Optional[str] = Field(default="Order on WhatsApp", max_length=30)
    size: str = Field(default="portrait", pattern="^(portrait|square|landscape)$")
    product_id: Optional[uuid.UUID] = None
    campaign_id: Optional[uuid.UUID] = None


@router.post("/media/card", status_code=201)
def media_card(payload: CardIn, db: Session = Depends(get_db)):
    """Draw a promotional card in the brand colours."""
    return marketing_media.make_card(db, headline=payload.headline, subline=payload.subline, price=payload.price, badge=payload.badge,
                                     points=[p for p in payload.points or [] if p.strip()][:4] or None, cta=payload.cta, size=payload.size,
                                     product_id=payload.product_id, campaign_id=payload.campaign_id)


class ProductCardIn(BaseModel):
    product_id: uuid.UUID
    offer: Optional[str] = Field(default=None, max_length=160)
    campaign_id: Optional[uuid.UUID] = None


@router.post("/media/product-card", status_code=201)
def media_product_card(payload: ProductCardIn, db: Session = Depends(get_db)):
    from ..models import Product

    product = db.get(Product, payload.product_id)
    if product is None:
        raise ValidationError("Product not found.")
    return marketing_media.product_card(db, product, offer=payload.offer, campaign_id=payload.campaign_id)


class ImageIn(BaseModel):
    prompt: str = Field(min_length=8, max_length=1000)
    campaign_id: Optional[uuid.UUID] = None


@router.post("/media/generate", status_code=201)
def media_generate(payload: ImageIn, db: Session = Depends(get_db)):
    """An AI image from a description (Gemini)."""
    try:
        return marketing_media.generate_image(db, payload.prompt, campaign_id=payload.campaign_id)
    except marketing_media.ImageUnavailable as exc:
        raise ValidationError(str(exc))


# ---------------------------------------------------------------------------
# Audiences and consent
# ---------------------------------------------------------------------------


class AudienceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = None
    definition: Dict[str, Any] = Field(default_factory=dict)
    is_active: Optional[bool] = None


class PreviewIn(BaseModel):
    definition: Dict[str, Any] = Field(default_factory=dict)
    channels: Optional[List[str]] = None


@router.get("/audiences")
def audiences_list(db: Session = Depends(get_db)):
    from ..services import groups

    return {"items": marketing_audiences.list_all(db), "fields": groups.FIELDS}


@router.post("/audiences/preview")
def audience_preview(payload: PreviewIn, db: Session = Depends(get_db)):
    out = marketing_audiences.preview(db, payload.definition, payload.channels)
    out["summary"] = marketing_audiences.describe(db, payload.definition)
    return out


@router.post("/audiences", status_code=201)
def audience_create(payload: AudienceIn, db: Session = Depends(get_db)):
    return marketing_audiences.save(db, payload.model_dump(exclude_unset=True))


@router.put("/audiences/{audience_id}")
def audience_update(audience_id: uuid.UUID, payload: AudienceIn, db: Session = Depends(get_db)):
    return marketing_audiences.save(db, payload.model_dump(exclude_unset=True), audience_id)


@router.delete("/audiences/{audience_id}", status_code=204)
def audience_delete(audience_id: uuid.UUID, db: Session = Depends(get_db)):
    marketing_audiences.delete(db, audience_id)


@router.get("/consents")
def consents(channel: str = "whatsapp", status: Optional[str] = None, q: Optional[str] = None, db: Session = Depends(get_db)):
    """Every active customer with their consent on a channel."""
    stmt = select(Customer).where(Customer.is_active.is_(True)).order_by(Customer.name)
    if q:
        stmt = stmt.where(Customer.name.ilike("%{}%".format(q)) | Customer.phone.ilike("%{}%".format(q)))
    customers = db.execute(stmt.limit(2000)).scalars().all()
    rows = {r.customer_id: r for r in db.execute(select(MarketingConsent).where(MarketingConsent.channel == channel)).scalars()}
    items = []
    for c in customers:
        r = rows.get(c.id)
        state = r.status if r else "unknown"
        if status and state != status:
            continue
        items.append({"customer_id": c.id, "name": c.name, "phone": c.phone, "email": c.email, "status": state,
                      "source": r.source if r else None, "evidence": r.evidence if r else None, "at": r.at if r else None,
                      "by": r.recorded_by if r else None, "birthday": c.birthday, "anniversary": c.anniversary})
    totals: Dict[str, int] = {}
    for c in customers:
        r = rows.get(c.id)
        totals[r.status if r else "unknown"] = totals.get(r.status if r else "unknown", 0) + 1
    return {"items": items, "totals": totals}


class ConsentIn(BaseModel):
    customer_ids: List[uuid.UUID] = Field(min_length=1, max_length=2000)
    channel: str = "whatsapp"
    status: str = Field(pattern="^(opted_in|opted_out)$")
    source: str = "manual"
    evidence: Optional[str] = Field(default=None, max_length=500)


@router.post("/consents")
def set_consents(payload: ConsentIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Record consent (or an opt-out) for one or many customers, with how it was given."""
    for cid in payload.customer_ids:
        marketing_policy.set_consent(db, cid, payload.channel, payload.status, payload.source, payload.evidence, by=user.username)
    return {"updated": len(payload.customer_ids)}


class OccasionsIn(BaseModel):
    birthday: Optional[str] = None
    anniversary: Optional[str] = None


@router.put("/customers/{customer_id}/occasions")
def set_occasions(customer_id: uuid.UUID, payload: OccasionsIn, db: Session = Depends(get_db)):
    from datetime import date

    customer = db.get(Customer, customer_id)
    if customer is None:
        raise ValidationError("Customer not found.")
    for key in ("birthday", "anniversary"):
        value = getattr(payload, key)
        if value is not None:
            try:
                setattr(customer, key, date.fromisoformat(value) if value else None)
            except ValueError:
                raise ValidationError("Use a date like 1985-03-21.")
    db.commit()
    return {"birthday": customer.birthday, "anniversary": customer.anniversary,
            "consent": marketing_policy.consent_of(db, customer_id)}


@router.get("/customers/{customer_id}")
def customer_marketing(customer_id: uuid.UUID, db: Session = Depends(get_db)):
    """A customer's consent, occasions and the campaigns that reached them."""
    from sqlalchemy import select as _select

    from ..models import MarketingCampaign, MarketingSend

    customer = db.get(Customer, customer_id)
    if customer is None:
        raise ValidationError("Customer not found.")
    rows = db.execute(_select(MarketingSend, MarketingCampaign.name).join(MarketingCampaign, MarketingCampaign.id == MarketingSend.campaign_id)
                      .where(MarketingSend.customer_id == customer_id).order_by(MarketingSend.queued_at.desc()).limit(30)).all()
    return {"consent": marketing_policy.consent_of(db, customer_id), "birthday": customer.birthday, "anniversary": customer.anniversary,
            "messages": [{"campaign_id": s.campaign_id, "campaign": name, "status": s.status, "skip_reason": s.skip_reason,
                          "sent_at": s.sent_at, "read_at": s.read_at, "replied_at": s.replied_at} for s, name in rows]}


# ---------------------------------------------------------------------------
# Calendar and analytics
# ---------------------------------------------------------------------------


@router.get("/calendar")
def calendar(start: Optional[datetime] = None, end: Optional[datetime] = None, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    start = start or (now - timedelta(days=now.day))
    end = end or (start + timedelta(days=42))
    return {"items": marketing.calendar(db, start, end)}


@router.get("/analytics")
def analytics(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    return marketing.analytics(db, days)


@router.post("/attribute")
def attribute(db: Session = Depends(get_db)):
    return {"new": marketing.attribute(db)}


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------


@router.get("/settings")
def settings(db: Session = Depends(get_db)):
    """Marketing policies and brand kit, and the Instagram connection (no tokens)."""
    return {"marketing": settings_service.view(settings_service.get(db, settings_service.MARKETING)),
            "instagram": settings_service.view(settings_service.get(db, settings_service.INSTAGRAM)),
            "ai": marketing_agents.ai_available(db)}


@router.post("/instagram/check")
def instagram_check(db: Session = Depends(get_db)):
    try:
        return instagram.check(db)
    except instagram.InstagramError as exc:
        raise ValidationError(str(exc))


@router.post("/instagram/sync")
def instagram_sync(db: Session = Depends(get_db)):
    try:
        return marketing_channels.sync_instagram(db)
    except instagram.InstagramError as exc:
        raise ValidationError(str(exc))


@router.get("/instagram/posts")
def instagram_posts(db: Session = Depends(get_db)):
    from ..models import MarketingCampaign, MarketingContent

    rows = db.execute(select(MarketingContent, MarketingCampaign.name).join(MarketingCampaign, MarketingCampaign.id == MarketingContent.campaign_id)
                      .where(MarketingContent.channel == "instagram").order_by(MarketingContent.created_at.desc()).limit(200)).all()
    return {"items": [{**marketing.content_view(db, c), "campaign": name} for c, name in rows]}


@router.get("/instagram/comments")
def instagram_comments(status: Optional[str] = None, db: Session = Depends(get_db)):
    return {"items": marketing_channels.comment_list(db, status)}


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=900)


@router.post("/instagram/comments/{comment_id}/reply")
def instagram_reply(comment_id: uuid.UUID, payload: ReplyIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return marketing_channels.reply_comment(db, comment_id, payload.text, by=user.username)


class HideIn(BaseModel):
    hidden: bool = True


@router.post("/instagram/comments/{comment_id}/hide")
def instagram_hide(comment_id: uuid.UUID, payload: HideIn, db: Session = Depends(get_db)):
    return marketing_channels.hide_comment(db, comment_id, payload.hidden)


@router.get("/whatsapp/templates")
def wa_templates(db: Session = Depends(get_db)):
    return {"items": marketing_channels.templates(db)}


@router.post("/whatsapp/templates/sync")
def wa_templates_sync(db: Session = Depends(get_db)):
    return marketing_channels.sync_templates(db)


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=1024)
    examples: List[str] = Field(default_factory=list)
    language: str = "en"
    footer: Optional[str] = Field(default=None, max_length=60)
    header_text: Optional[str] = Field(default=None, max_length=60)


@router.post("/whatsapp/templates", status_code=201)
def wa_template_create(payload: TemplateIn, db: Session = Depends(get_db)):
    """Submit a marketing template to Meta for approval."""
    return marketing_channels.create_template(db, payload.model_dump())


class TemplateIdeaIn(BaseModel):
    purpose: str = Field(min_length=2, max_length=300)


@router.post("/whatsapp/templates/suggest")
def wa_template_suggest(payload: TemplateIdeaIn, db: Session = Depends(get_db)):
    return marketing_agents.suggest_template(db, payload.purpose)


# ---------------------------------------------------------------------------
# Automations
# ---------------------------------------------------------------------------


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    trigger: str
    conditions: Dict[str, Any] = Field(default_factory=dict)
    action: str = "draft_campaign"
    action_config: Dict[str, Any] = Field(default_factory=dict)
    cooldown_days: int = Field(default=30, ge=0, le=365)
    is_active: bool = True


@router.get("/rules")
def rules(db: Session = Depends(get_db)):
    return {"items": marketing_rules.list_rules(db), **marketing_rules.catalogue()}


@router.post("/rules", status_code=201)
def rule_create(payload: RuleIn, db: Session = Depends(get_db)):
    return marketing_rules.save(db, payload.model_dump())


@router.put("/rules/{rule_id}")
def rule_update(rule_id: uuid.UUID, payload: RuleIn, db: Session = Depends(get_db)):
    return marketing_rules.save(db, payload.model_dump(), rule_id)


@router.delete("/rules/{rule_id}", status_code=204)
def rule_delete(rule_id: uuid.UUID, db: Session = Depends(get_db)):
    marketing_rules.delete(db, rule_id)


@router.post("/rules/{rule_id}/run")
def rule_run(rule_id: uuid.UUID, db: Session = Depends(get_db)):
    from ..models import MarketingRule

    rule = db.get(MarketingRule, rule_id)
    if rule is None:
        raise ValidationError("Automation not found.")
    return marketing_rules.run_rule(db, rule, force=True)
