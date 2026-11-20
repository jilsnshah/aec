"""Images for posts and messages.

Three sources:
- ``upload``: a photo the user adds (converted to JPEG, which Instagram needs);
- ``card``: a designed promotional card drawn here from the product, price,
  offer and brand kit -- always available, no AI needed;
- ``ai``: an image made by a Gemini image model from a prompt, when Gemini is
  connected.

Images live in the database and are served at ``/api/public/media/<token>.jpg``
(an unguessable address) so Instagram and WhatsApp can fetch them.
"""
from __future__ import annotations

import io
import logging
import secrets
import textwrap
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session

from ..errors import NotFoundError, ValidationError
from ..models import MarketingMedia, Product
from . import integration_settings as settings_service

logger = logging.getLogger(__name__)

FONT = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "PlusJakartaSans.ttf"
MAX_UPLOAD = 8 * 1024 * 1024
#: Instagram feed images: aspect ratio between 4:5 and 1.91:1.
SIZES = {"portrait": (1080, 1350), "square": (1080, 1080), "landscape": (1080, 566)}
#: Image model used when none is set in Settings → Marketing.
DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image"


def _font(size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT), size)
    try:
        font.set_variation_by_name(weight)
    except (OSError, ValueError):
        pass
    return font


def _jpeg(image: Image.Image, max_side: int = 1440) -> Tuple[bytes, int, int]:
    image = ImageOps.exif_transpose(image).convert("RGB")
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side))
    w, h = image.size
    ratio = w / h
    if ratio < 0.8:  # taller than 4:5 -> crop to 4:5
        new_h = int(w / 0.8)
        top = (h - new_h) // 2
        image = image.crop((0, top, w, top + new_h))
    elif ratio > 1.91:
        new_w = int(h * 1.91)
        left = (w - new_w) // 2
        image = image.crop((left, 0, left + new_w, h))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue(), image.size[0], image.size[1]


def _store(session: Session, data: bytes, width: int, height: int, source: str, *, name: Optional[str] = None,
           prompt: Optional[str] = None, product_id: Optional[uuid.UUID] = None, campaign_id: Optional[uuid.UUID] = None) -> MarketingMedia:
    row = MarketingMedia(token=secrets.token_urlsafe(24), data=data, width=width, height=height, size=len(data),
                         mime="image/jpeg", source=source, name=name, prompt=prompt, product_id=product_id, campaign_id=campaign_id)
    session.add(row)
    session.flush()
    return row


def view(session: Session, row: Optional[MarketingMedia]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {"id": row.id, "url": "/api/public/media/{}.jpg".format(row.token), "public_url": public_url(session, row),
            "width": row.width, "height": row.height, "size": row.size, "source": row.source, "name": row.name,
            "prompt": row.prompt, "product_id": row.product_id, "campaign_id": row.campaign_id, "created_at": row.created_at}


def public_url(session: Session, row: MarketingMedia) -> Optional[str]:
    base = settings_service.get(session, settings_service.MARKETING).config.get("public_url") or ""
    return "{}/api/public/media/{}.jpg".format(base, row.token) if base else None


def get(session: Session, media_id: uuid.UUID) -> MarketingMedia:
    row = session.get(MarketingMedia, media_id)
    if row is None:
        raise NotFoundError("Image not found.")
    return row


def by_token(session: Session, token: str) -> MarketingMedia:
    from sqlalchemy import select

    row = session.execute(select(MarketingMedia).where(MarketingMedia.token == token)).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Image not found.")
    return row


def upload(session: Session, raw: bytes, name: Optional[str] = None, campaign_id: Optional[uuid.UUID] = None,
           product_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    if not raw:
        raise ValidationError("The file is empty.")
    if len(raw) > MAX_UPLOAD:
        raise ValidationError("Images must be under 8 MB.")
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError):
        raise ValidationError("That file is not an image we can read (use JPEG or PNG).")
    data, w, h = _jpeg(image)
    row = _store(session, data, w, h, "upload", name=name, campaign_id=campaign_id, product_id=product_id)
    session.commit()
    return view(session, row)


def library(session: Session, campaign_id: Optional[uuid.UUID] = None, limit: int = 60) -> List[Dict[str, Any]]:
    from sqlalchemy import select

    stmt = select(MarketingMedia).order_by(MarketingMedia.created_at.desc()).limit(limit)
    if campaign_id:
        stmt = stmt.where(MarketingMedia.campaign_id == campaign_id)
    return [view(session, r) for r in session.execute(stmt).scalars()]


# ---------------------------------------------------------------------------
# Designed product cards
# ---------------------------------------------------------------------------


def _hex(color: str) -> Tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _luma(rgb: Tuple[int, int, int]) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int, max_lines: int) -> List[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = (line + " " + word).strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
        if len(lines) == max_lines:
            break
    if line and len(lines) < max_lines:
        lines.append(line)
    if len(lines) == max_lines and " ".join(lines) != text.strip():
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def render_card(brand: Dict[str, Any], *, headline: str, subline: Optional[str] = None, price: Optional[str] = None,
                badge: Optional[str] = None, points: Optional[List[str]] = None, cta: Optional[str] = None,
                size: str = "portrait") -> Image.Image:
    """A clean promotional card in the brand colours."""
    w, h = SIZES.get(size, SIZES["portrait"])
    colors = [_hex(c) for c in (brand.get("brand_colors") or ["#0B1220", "#38BDF8", "#FFFFFF"])]
    bg = colors[0]
    accent = colors[1] if len(colors) > 1 else (56, 189, 248)
    ink = (255, 255, 255) if _luma(bg) < 140 else (12, 18, 32)
    soft = tuple(int(c * 0.72 + (255 if _luma(bg) < 140 else 0) * 0.28) for c in ink)
    image = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(image)
    # Soft decorative shapes.
    r = int(w * 0.55)
    glow = Image.new("RGB", (w, h), bg)
    gd = ImageDraw.Draw(glow)
    gd.ellipse((w - r, -r // 2, w + r // 2, r), fill=tuple(int(a * 0.35 + b * 0.65) for a, b in zip(accent, bg)))
    gd.ellipse((-r // 2, h - r // 2, r // 2, h + r // 2), fill=tuple(int(a * 0.18 + b * 0.82) for a, b in zip(accent, bg)))
    image = Image.blend(image, glow, 0.9)
    draw = ImageDraw.Draw(image)
    pad = 84
    y = pad
    name = (brand.get("brand_name") or "").strip()
    if name:
        draw.text((pad, y), name.upper(), font=_font(30, "Bold"), fill=soft)
        y += 70
    else:
        y += 20
    if badge:
        f = _font(30, "Bold")
        tw = draw.textlength(badge.upper(), font=f)
        draw.rounded_rectangle((pad, y, pad + tw + 44, y + 58), radius=29, fill=accent)
        draw.text((pad + 22, y + 11), badge.upper(), font=f, fill=bg if _luma(accent) > 140 else (255, 255, 255))
        y += 96
    big = _font(92 if len(headline) < 28 else 76, "ExtraBold")
    for line in _wrap(draw, headline, big, w - 2 * pad, 4):
        draw.text((pad, y), line, font=big, fill=ink)
        y += int(big.size * 1.12)
    if subline:
        y += 14
        f = _font(38, "Medium")
        for line in _wrap(draw, subline, f, w - 2 * pad, 3):
            draw.text((pad, y), line, font=f, fill=soft)
            y += 52
    if points:
        y += 26
        f = _font(34, "SemiBold")
        for point in points[:4]:
            draw.ellipse((pad, y + 14, pad + 14, y + 28), fill=accent)
            line = _wrap(draw, point, f, w - 2 * pad - 36, 1)
            draw.text((pad + 34, y), line[0] if line else point, font=f, fill=ink)
            y += 56
    bottom = h - pad
    if cta:
        f = _font(36, "Bold")
        tw = draw.textlength(cta, font=f)
        draw.rounded_rectangle((pad, bottom - 76, pad + tw + 64, bottom), radius=38, fill=ink)
        draw.text((pad + 32, bottom - 60), cta, font=f, fill=bg)
    if price:
        f = _font(64, "ExtraBold")
        tw = draw.textlength(price, font=f)
        draw.text((w - pad - tw, bottom - 78), price, font=f, fill=accent)
    return image


def make_card(session: Session, *, headline: str, subline: Optional[str] = None, price: Optional[str] = None,
              badge: Optional[str] = None, points: Optional[List[str]] = None, cta: Optional[str] = None,
              size: str = "portrait", product_id: Optional[uuid.UUID] = None, campaign_id: Optional[uuid.UUID] = None,
              commit: bool = True) -> Dict[str, Any]:
    if not (headline or "").strip():
        raise ValidationError("The card needs a headline.")
    brand = settings_service.get(session, settings_service.MARKETING).config
    image = render_card(brand, headline=headline.strip(), subline=subline, price=price, badge=badge, points=points, cta=cta, size=size)
    data, w, h = _jpeg(image)
    row = _store(session, data, w, h, "card", name=headline[:160], product_id=product_id, campaign_id=campaign_id,
                 prompt=" | ".join(x for x in [headline, subline or "", price or "", badge or ""] if x))
    if commit:
        session.commit()
    return view(session, row)


def product_card(session: Session, product: Product, *, offer: Optional[str] = None, price: Optional[float] = None,
                 campaign_id: Optional[uuid.UUID] = None, commit: bool = True) -> Dict[str, Any]:
    """A card for one product: its name, brand, key details and price."""
    points: List[str] = []
    if product.brand:
        points.append("Brand: " + product.brand)
    for spec in (product.specs or [])[:3]:
        if isinstance(spec, dict) and spec.get("name") and spec.get("value"):
            points.append("{}: {}".format(spec["name"], spec["value"]))
    amount = price if price is not None else (float(product.mrp) if product.mrp else None)
    price_text = "₹{:,.0f}/{}".format(amount, product.unit_of_measure) if amount else None
    return make_card(session, headline=product.name, subline=offer or (product.description or "")[:120] or None,
                     price=price_text, badge="Offer" if offer else ("In stock" if float(product.physical_stock or 0) > 0 else None),
                     points=points, cta="Order on WhatsApp", product_id=product.id, campaign_id=campaign_id, commit=commit)


# ---------------------------------------------------------------------------
# AI images (Gemini)
# ---------------------------------------------------------------------------


class ImageUnavailable(Exception):
    """No Gemini image model is reachable; callers fall back to a card."""


def _genai_client(session: Session):
    from google import genai

    creds = settings_service.ai_credentials(session)
    if creds is None:
        raise ImageUnavailable("Gemini is not connected (Settings → AI).")
    if creds["mode"] == "api_key":
        return genai.Client(api_key=creds["api_key"])
    if creds["mode"] == "vertex_key":
        return genai.Client(vertexai=True, api_key=creds["api_key"])
    return genai.Client(vertexai=True, project=creds["project"], location=creds["location"])


#: Tests replace this with a function returning image bytes.
image_generator = None


def generate_image(session: Session, prompt: str, *, campaign_id: Optional[uuid.UUID] = None,
                   product_id: Optional[uuid.UUID] = None, commit: bool = True) -> Dict[str, Any]:
    """An image from a prompt, styled with the brand kit. Raises ImageUnavailable
    when Gemini cannot be used."""
    prompt = (prompt or "").strip()
    if len(prompt) < 8:
        raise ValidationError("Describe the image in a few words.")
    brand = settings_service.get(session, settings_service.MARKETING).config
    styled = ("{}\n\nStyle: clean professional product marketing photo for Instagram, portrait 4:5, natural light, "
              "no text, no logos, no watermarks. Brand colours to echo: {}. Tone: {}.").format(
        prompt, ", ".join(brand.get("brand_colors") or []), brand.get("brand_tone") or "")
    if image_generator is not None:
        raw = image_generator(styled)
    else:
        model = brand.get("image_model") or DEFAULT_IMAGE_MODEL
        try:
            client = _genai_client(session)
            result = client.models.generate_content(model=model, contents=[styled])
        except ImageUnavailable:
            raise
        except Exception as exc:  # network, quota, model not enabled
            logger.warning("Image generation failed: %s", exc)
            raise ImageUnavailable("Gemini could not make the image: {}".format(str(exc)[:200]))
        raw = None
        for candidate in getattr(result, "candidates", None) or []:
            for part in getattr(candidate.content, "parts", None) or []:
                inline = getattr(part, "inline_data", None)
                if inline is not None and getattr(inline, "data", None):
                    raw = inline.data
                    break
            if raw:
                break
        if not raw:
            raise ImageUnavailable("Gemini returned no image for that prompt.")
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError):
        raise ImageUnavailable("Gemini returned something that is not an image.")
    data, w, h = _jpeg(image)
    row = _store(session, data, w, h, "ai", name=textwrap.shorten(prompt, 150), prompt=prompt, campaign_id=campaign_id, product_id=product_id)
    if commit:
        session.commit()
    return view(session, row)
