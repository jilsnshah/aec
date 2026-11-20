"""Keeping channels in step: WhatsApp templates, Instagram post metrics and
comments, and replying to comments."""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import InstagramComment, MarketingContent, WhatsappTemplate
from . import instagram
from . import integration_settings as settings_service
from . import marketing

logger = logging.getLogger(__name__)

NAME = re.compile(r"^[a-z0-9_]{1,512}$")
VARIABLE = re.compile(r"\{\{(\d+)\}\}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# WhatsApp templates
# ---------------------------------------------------------------------------


def template_view(t: WhatsappTemplate) -> Dict[str, Any]:
    return {"id": t.id, "name": t.name, "language": t.language, "category": t.category, "status": t.status, "body": t.body,
            "header": t.header, "footer": t.footer, "variable_count": t.variable_count, "examples": t.examples or [],
            "reason": t.reason, "synced_at": t.synced_at}


def templates(session: Session, category: Optional[str] = None) -> List[Dict[str, Any]]:
    stmt = select(WhatsappTemplate).order_by(WhatsappTemplate.status, WhatsappTemplate.name)
    if category:
        stmt = stmt.where(WhatsappTemplate.category == category)
    return [template_view(t) for t in session.execute(stmt).scalars()]


def _wa(session: Session):
    row = settings_service.get(session, settings_service.WHATSAPP)
    token = settings_service.credentials(row).get("access_token")
    if not token:
        raise ValidationError("Add the WhatsApp access token in Settings → WhatsApp first.")
    return row.config, token


def sync_templates(session: Session) -> Dict[str, Any]:
    from . import whatsapp

    config, token = _wa(session)
    try:
        remote = whatsapp.list_templates(config, token)
    except whatsapp.SendError as exc:
        raise ValidationError(str(exc))
    seen = 0
    for item in remote:
        name, language = item.get("name"), item.get("language") or "en"
        if not name:
            continue
        row = session.execute(select(WhatsappTemplate).where(WhatsappTemplate.name == name, WhatsappTemplate.language == language)).scalar_one_or_none()
        if row is None:
            row = WhatsappTemplate(name=name, language=language)
            session.add(row)
        body, header, footer = "", None, None
        for comp in item.get("components") or []:
            kind = (comp.get("type") or "").upper()
            if kind == "BODY":
                body = comp.get("text") or ""
            elif kind == "HEADER":
                header = (comp.get("format") or "TEXT").upper()
            elif kind == "FOOTER":
                footer = (comp.get("text") or "")[:60]
        row.body, row.header, row.footer = body, header, footer
        row.category = (item.get("category") or "MARKETING").upper()
        row.status = (item.get("status") or "PENDING").upper()
        row.external_id = str(item.get("id") or "") or None
        row.reason = item.get("rejected_reason") if row.status == "REJECTED" else None
        row.variable_count = len(set(VARIABLE.findall(body)))
        row.synced_at = _now()
        seen += 1
    session.commit()
    marketing.log(session, "executor", "templates_synced", "Synced {} WhatsApp templates from Meta.".format(seen))
    session.commit()
    return {"synced": seen, "items": templates(session)}


def create_template(session: Session, data: Dict[str, Any]) -> Dict[str, Any]:
    """Submit a marketing template to Meta for approval."""
    from . import whatsapp

    name = str(data.get("name") or "").strip().lower().replace(" ", "_")
    if not NAME.match(name):
        raise ValidationError("Template names use lowercase letters, numbers and underscores.")
    body = str(data.get("body") or "").strip()
    if not body or len(body) > 1024:
        raise ValidationError("The message must be 1 to 1,024 characters.")
    numbers = sorted({int(n) for n in VARIABLE.findall(body)})
    if numbers and numbers != list(range(1, len(numbers) + 1)):
        raise ValidationError("Number the blanks {{1}}, {{2}}… in order.")
    if body.strip().startswith("{{") or body.strip().endswith("}}"):
        raise ValidationError("Meta does not accept a message that starts or ends with a blank.")
    examples = [str(e).strip() for e in data.get("examples") or []]
    if len(examples) != len(numbers) or any(not e for e in examples):
        raise ValidationError("Give an example value for each blank (Meta needs them to review the template).")
    language = (data.get("language") or "en").strip()
    footer = (data.get("footer") or "").strip()[:60] or None
    header_text = (data.get("header_text") or "").strip()[:60] or None
    components: List[Dict[str, Any]] = []
    if header_text:
        components.append({"type": "HEADER", "format": "TEXT", "text": header_text})
    body_comp: Dict[str, Any] = {"type": "BODY", "text": body}
    if examples:
        body_comp["example"] = {"body_text": [examples]}
    components.append(body_comp)
    if footer:
        components.append({"type": "FOOTER", "text": footer})
    components.append({"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Stop promotions"}]})
    if session.execute(select(WhatsappTemplate.id).where(WhatsappTemplate.name == name, WhatsappTemplate.language == language)).first():
        raise ConflictError("A template called {} ({}) already exists.".format(name, language))
    config, token = _wa(session)
    try:
        result = whatsapp.create_template(config, token, {"name": name, "language": language, "category": "MARKETING", "components": components})
    except whatsapp.SendError as exc:
        raise ValidationError(str(exc))
    row = WhatsappTemplate(name=name, language=language, category=(result.get("category") or "MARKETING").upper(),
                           status=(result.get("status") or "PENDING").upper(), body=body, header="TEXT" if header_text else None,
                           footer=footer, variable_count=len(numbers), examples=examples, external_id=str(result.get("id") or "") or None,
                           synced_at=_now())
    session.add(row)
    marketing.log(session, "person", "template_created", "Template {} sent to Meta for approval ({}).".format(name, row.status.lower()))
    session.commit()
    return template_view(row)


# ---------------------------------------------------------------------------
# Instagram: metrics and comments
# ---------------------------------------------------------------------------


def sync_instagram(session: Session, days: int = 30) -> Dict[str, int]:
    """Refresh metrics and comments of posts published in the last N days."""
    conn = instagram.connection(session)
    if not conn["enabled"]:
        return {"posts": 0, "comments": 0}
    since = _now() - timedelta(days=days)
    posts = session.execute(select(MarketingContent).where(MarketingContent.channel == "instagram", MarketingContent.external_id.is_not(None),
                                                           MarketingContent.published_at >= since)).scalars().all()
    new_comments = 0
    for post in posts:
        try:
            post.metrics = instagram.media_metrics(conn, post.external_id)
            post.synced_at = _now()
            for item in instagram.comments(conn, post.external_id):
                if session.execute(select(InstagramComment.id).where(InstagramComment.external_id == str(item.get("id")))).first():
                    continue
                at = None
                try:
                    at = datetime.fromisoformat(str(item.get("timestamp")).replace("+0000", "+00:00"))
                except ValueError:
                    pass
                comment = InstagramComment(external_id=str(item["id"]), media_external_id=post.external_id, content_id=post.id,
                                           username=item.get("username"), text=item.get("text") or "", commented_at=at)
                session.add(comment)
                new_comments += 1
            session.commit()
        except instagram.InstagramError as exc:
            session.rollback()
            if exc.token_broken:
                settings_service.record_system(session, settings_service.INSTAGRAM, last_error=str(exc))
                marketing.log(session, "executor", "instagram_auth", "Instagram access token expired; reconnect to keep metrics updating.", level="error")
                session.commit()
                break
            logger.info("Could not sync post %s: %s", post.external_id, exc)
    if new_comments:
        from . import marketing_agents

        marketing_agents.draft_comment_replies(session)
    return {"posts": len(posts), "comments": new_comments}


def comment_view(session: Session, c: InstagramComment) -> Dict[str, Any]:
    post = session.get(MarketingContent, c.content_id) if c.content_id else None
    return {"id": c.id, "username": c.username, "text": c.text, "commented_at": c.commented_at, "reply_text": c.reply_text,
            "reply_status": c.reply_status, "replied_at": c.replied_at, "hidden": c.hidden, "intent": c.intent,
            "post": {"id": post.id, "campaign_id": post.campaign_id, "permalink": post.permalink, "caption": (post.caption or "")[:100]} if post else None}


def comment_list(session: Session, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    stmt = select(InstagramComment).order_by(InstagramComment.commented_at.desc().nullslast(), InstagramComment.created_at.desc()).limit(limit)
    if status == "open":
        stmt = stmt.where(InstagramComment.reply_status.in_(("none", "draft", "failed")), InstagramComment.hidden.is_(False))
    return [comment_view(session, c) for c in session.execute(stmt).scalars()]


def _comment(session: Session, comment_id: uuid.UUID) -> InstagramComment:
    row = session.get(InstagramComment, comment_id)
    if row is None:
        raise NotFoundError("Comment not found.")
    return row


def reply_comment(session: Session, comment_id: uuid.UUID, text: str, by: Optional[str] = None) -> Dict[str, Any]:
    c = _comment(session, comment_id)
    text = (text or "").strip()
    if not text:
        raise ValidationError("Write the reply.")
    if c.reply_status == "sent":
        raise ConflictError("This comment already has our reply.")
    try:
        c.reply_external_id = instagram.reply(instagram.connection(session), c.external_id, text)
    except instagram.InstagramError as exc:
        c.reply_status = "failed"
        session.commit()
        raise ValidationError(str(exc))
    c.reply_text, c.reply_status, c.replied_at = text, "sent", _now()
    marketing.log(session, "person", "comment_reply", "{} replied to @{}.".format(by or "Someone", c.username or "a follower"))
    session.commit()
    return comment_view(session, c)


def hide_comment(session: Session, comment_id: uuid.UUID, hidden: bool = True) -> Dict[str, Any]:
    c = _comment(session, comment_id)
    try:
        instagram.hide(instagram.connection(session), c.external_id, hidden)
    except instagram.InstagramError as exc:
        raise ValidationError(str(exc))
    c.hidden = hidden
    session.commit()
    return comment_view(session, c)
