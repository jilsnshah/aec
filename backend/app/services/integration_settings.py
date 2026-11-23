"""Settings for the AI, WhatsApp and email integrations.

Each integration is one row: an on/off switch, plain settings, and encrypted
credentials. Credentials are encrypted with a key derived from ``SECRET_KEY``
and are never sent back to the browser -- the API only says whether each one is
set, with the last four characters as a hint.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import begin_write
from ..errors import ValidationError
from ..models import IntegrationSetting

logger = logging.getLogger(__name__)

AI = "ai"
WHATSAPP = "whatsapp"
EMAIL = "email"
TALLY = "tally"
CONTROLS = "controls"
INSTAGRAM = "instagram"
MARKETING = "marketing"
AGENTS = "agents"
CREDIT_MODES = ("off", "warn", "block")

TAX_MODES = ("none", "cgst_sgst", "igst")

#: Gemini models offered in Settings. Any other Gemini model id can be typed
#: in; when an API key is saved the list is refreshed from Google (see
#: app.ai.provider.list_models).
AI_MODELS: List[Dict[str, str]] = [
    {"id": "gemini-3.1-flash-lite", "provider": "gemini", "label": "Gemini 3.1 Flash-Lite",
     "hint": "Default. Lowest cost and fastest; handles everyday questions and changes."},
    {"id": "gemini-3.5-flash-lite", "provider": "gemini", "label": "Gemini 3.5 Flash-Lite",
     "hint": "Low cost, newer."},
    {"id": "gemini-3.8-flash", "provider": "gemini", "label": "Gemini 3.8 Flash",
     "hint": "Stronger at long analysis and many-step work; costs more."},
]
PROVIDER_LABELS = {"gemini": "Google Gemini"}
CHANGE_POLICIES = ("confirm_all", "confirm_significant")
VOICE_PROVIDERS = ("gemini", "sarvam")
#: Languages the Sarvam voice speaks; the caller's language is still detected.
SARVAM_LANGUAGES = ("hi-IN", "gu-IN", "en-IN", "mr-IN", "bn-IN", "ta-IN", "te-IN", "kn-IN", "ml-IN", "pa-IN", "od-IN")
MODEL_PATTERN = re.compile(r"^(models/)?gemini[a-z0-9.\-]*$")


def ai_credentials(session: Optional[Session] = None) -> Optional[Dict[str, str]]:
    """How to reach Gemini, or None. A key saved in Settings wins; otherwise the
    server's own Vertex AI credentials (environment), if any."""
    if session is not None:
        row = session.get(IntegrationSetting, AI)
        key = credentials(row).get("api_key") if row is not None else None
        if key:
            return {"mode": "api_key", "api_key": key, "source": "settings"}
    settings = get_settings()
    if settings.vertex_api_key:
        return {"mode": "vertex_key", "api_key": settings.vertex_api_key, "source": "server"}
    if settings.vertex_project:
        return {"mode": "vertex_adc", "project": settings.vertex_project,
                "location": settings.vertex_location, "source": "server"}
    return None


def sarvam_key(session: Optional[Session] = None) -> Optional[str]:
    """The Sarvam API key: saved in Settings, else SARVAM_API_KEY in the environment or backend/.env.voice."""
    if session is not None:
        row = session.get(IntegrationSetting, AI)
        key = credentials(row).get("sarvam_api_key") if row is not None else None
        if key:
            return key
    if os.environ.get("SARVAM_API_KEY"):
        return os.environ["SARVAM_API_KEY"]
    from pathlib import Path

    env = Path(__file__).resolve().parents[2] / ".env.voice"  # the voice server's own settings file
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("SARVAM_API_KEY="):
                return line.split("=", 1)[1].strip() or None
    return None


def voice_llm_key(session: Session) -> Optional[str]:
    """The key for an outside chat model on calls (never sent to the browser)."""
    return credentials(get(session, AI)).get("voice_llm_api_key") or None


def voice_settings(session: Session) -> Dict[str, Any]:
    """Which engine runs phone calls, and its settings (no secrets)."""
    row = get(session, AI)
    config = row.config
    base = (config.get("voice_llm_base_url") or "").rstrip("/")
    return {"provider": config.get("voice_provider") or "gemini", "chat_model": config.get("sarvam_chat_model") or "deepseekv4.1-flash-1017-interactive",
            "llm_base_url": base, "chat": config.get("voice_chat") or "gemini", "gemini_model": config.get("voice_gemini_model") or "gemini-3.5-flash-lite", "llm_ready": not base or bool(credentials(row).get("voice_llm_api_key")),
            "tts_model": config.get("sarvam_tts_model") or "bulbul:v4-flash", "voice": config.get("sarvam_voice") or "",
            "language": config.get("sarvam_language") or "hi-IN", "sarvam_ready": bool(sarvam_key(session))}


def automation_paused(session: Session) -> bool:
    return bool(get(session, CONTROLS).config.get("automation_paused"))


def provider_configured(session: Optional[Session] = None) -> bool:
    return ai_credentials(session) is not None


def available_models() -> List[Dict[str, str]]:
    return list(AI_MODELS)


def model_info(model_id: str) -> Optional[Dict[str, str]]:
    return next((model for model in AI_MODELS if model["id"] == model_id), None)


def default_model() -> str:
    return "gemini-3.1-flash-lite"

#: Per integration: default plain settings, and the names of its credentials.
DEFINITIONS: Dict[str, Dict[str, Any]] = {
    # Business controls checked when an order is placed. "block" stops the
    # order unless an admin overrides it with a reason; "warn" only reports.
    CONTROLS: {
        "config": {
            "credit_check": "warn",
            "block_on_overdue": True,
            "overdue_grace_days": 0,
            "max_discount_percent": 0,
            "min_margin_percent": 0,
            "block_below_cost": False,
            # Master switch: while on, no automation runs on its own -- no
            # purchase, sales or marketing steps, no agents, no AI messages.
            "automation_paused": True,
        },
        "secrets": [],
    },
    # "enabled" switches on reading WhatsApp and email into enquiries; the
    # assistant is available whenever Gemini is reachable and "assistant" is on.
    AI: {
        "config": {
            "model": "",
            "assistant": True,
            # confirm_all: every change waits for the user's OK.
            # confirm_significant: routine edits (contacts, notes, follow-ups)
            # go straight through; money, stock and cancellations still wait.
            "change_policy": "confirm_all",
            "temperature": 0.2,
            # What the agents know about the business, written by the owner.
            "company_profile": "",
            "company_hours": "",
            "company_delivery": "",
            "company_payment": "",
            "company_policies": "",
            "agent_name": "Asha",
            # TAI/PAI reply in this tone; English, Hindi or Gujarati follow the customer.
            "agent_tone": "warm and brief",
            # Who runs phone calls: "gemini" (Gemini Live, on Google Cloud) or
            # "sarvam" (Sarvam speech-to-text, Sarvam chat model, Bulbul voice).
            "voice_provider": "gemini",
            # The model that decides what to say. On Sarvam's own API unless
            # voice_llm_base_url points at another OpenAI-compatible API.
            # "gemini" (text Gemini decides, Sarvam listens and speaks), or
            # "sarvam" (a model on Sarvam's API, or voice_llm_base_url's).
            "voice_chat": "gemini",
            "voice_gemini_model": "gemini-3.5-flash-lite",
            "sarvam_chat_model": "deepseekv4.1-flash-1017-interactive",
            "voice_llm_base_url": "",
            "sarvam_tts_model": "bulbul:v4-flash",
            # Empty: a Hinglish voice that suits the agent (male or female name).
            "sarvam_voice": "",
            "sarvam_language": "hi-IN",
        },
        "secrets": ["api_key", "sarvam_api_key", "voice_llm_api_key"],
    },
    WHATSAPP: {
        "config": {
            "phone_number_id": "",
            "business_account_id": "",
            "verify_token": "",
            # Sending invoices to customers (business-initiated, so Meta
            # requires an approved template with a document header).
            "send_invoices": False,
            "invoice_template": "",
            # An approved text template sent when an order is placed: body
            # variables are customer name, order number, total, items.
            # A utility template with one variable ({{1}}): carries messages we
            # start (supplier requests, reminders, follow-ups) outside the
            # 24-hour window.
            "message_template": "",
            "send_order_confirmations": False,
            "order_template": "",
            "template_language": "en",
            "country_code": "91",
            "graph_version": "v23.0",
        },
        "secrets": ["app_secret", "access_token"],
    },
    # Each AI agent's name, voice and extra instructions (see services/agents.py).
    AGENTS: {"config": {"profiles": {}}, "secrets": []},
    # An Instagram Business (or Creator) account, through Meta's Graph API.
    INSTAGRAM: {
        "config": {
            "ig_user_id": "",
            # graph.facebook.com (Facebook Login) or graph.instagram.com (Instagram Login).
            "api_host": "graph.facebook.com",
            "graph_version": "v23.0",
            # Filled by "Check connection".
            "username": "",
            "account_name": "",
            "followers": 0,
            "publish_quota": 0,
            "publish_used": 0,
            "last_checked_at": "",
            "last_error": "",
        },
        "secrets": ["access_token"],
    },
    # Marketing policies and the brand kit the agents follow.
    MARKETING: {
        "config": {
            "brand_name": "",
            "brand_tone": "friendly, clear and trustworthy; no hype",
            "brand_colors": ["#0B1220", "#38BDF8", "#FFFFFF"],
            "brand_hashtags": [],
            "brand_avoid": "",
            "brand_signature": "",
            # Shown in replies and captions ("message us on WhatsApp at ...").
            "whatsapp_number": "",
            "logo_media_id": "",
            # Who may publish. approval: a person approves every campaign.
            # auto: campaigns made by rules marked auto go out without waiting,
            # if their audience is no bigger than auto_max_audience.
            "approval": "approval",
            "auto_max_audience": 50,
            # Frequency cap: at most N promotional messages per customer per D days.
            "frequency_max": 2,
            "frequency_days": 7,
            # No promotional messages between these hours (local time).
            "quiet_start": "21:00",
            "quiet_end": "09:00",
            "timezone": "Asia/Kolkata",
            # WhatsApp messages sent per minute by the executor.
            "send_per_minute": 60,
            # Orders/enquiries within this many days of a message count for the campaign.
            "attribution_days": 14,
            # Replies that opt a customer out of marketing.
            "opt_out_words": ["STOP", "UNSUBSCRIBE", "STOP PROMOTIONS", "BAND", "बंद", "બંધ"],
            # Rough cost of one marketing message, for ROI (₹).
            "message_cost": 0.95,
            # The address the internet reaches this app at (for images Instagram fetches).
            "public_url": "",
            # Gemini model that draws images (cards are drawn without AI).
            "image_model": "gemini-3.1-flash-image",
            # Agents: how often the Strategist looks for opportunities.
            "scan_hours": 24,
            "analyst_weekday": 0,
            # Festivals and seasons the Strategist plans for (edit the dates each year).
            "occasions": [
                {"name": "Makar Sankranti", "date": "2027-01-14", "lead_days": 10},
                {"name": "Republic Day", "date": "2027-01-26", "lead_days": 7},
                {"name": "Holi", "date": "2027-03-22", "lead_days": 10},
                {"name": "Independence Day", "date": "2027-08-15", "lead_days": 7},
            ],
            "last_scan_at": "",
            "last_sync_at": "",
            "last_analysis_at": "",
        },
        "secrets": [],
    },
    TALLY: {
        "config": {
            # TallyPrime's HTTP server, e.g. http://tally.example.com:9000
            "server_url": "",
            "company": "",
            "sync_sales_orders": True,
            "create_invoices": True,
            # "order": one invoice for the whole order when it is placed.
            # "delivery": an invoice for what each delivery carries.
            "invoice_on": "order",
            "sync_purchase_orders": True,
            # Received transfers between warehouses become Stock Journals.
            "sync_transfers": True,
            "customer_group": "Sundry Debtors",
            "supplier_group": "Sundry Creditors",
            "godown": "Main Location",
            "sales_ledger": "Sales",
            "purchase_ledger": "Purchase",
            "sales_order_type": "Sales Order",
            "sales_invoice_type": "Sales",
            "purchase_order_type": "Purchase Order",
            "debit_note_type": "Debit Note",
            "tax_mode": "none",
            "gst_rate": 0,
            "cgst_ledger": "Output CGST",
            "sgst_ledger": "Output SGST",
            "igst_ledger": "Output IGST",
            # Printed on the invoice PDF sent to customers.
            "seller_name": "",
            "seller_address": "",
            "seller_gstin": "",
            "seller_phone": "",
        },
        # Sent as a bearer token, for a gateway or tunnel in front of Tally.
        "secrets": ["auth_token"],
    },
    EMAIL: {
        "config": {
            "imap_host": "",
            "imap_port": 993,
            # For replies: the same mailbox's outgoing server.
            "smtp_host": "",
            "smtp_port": 587,
            "username": "",
            "folder": "INBOX",
            "poll_minutes": 5,
            "last_checked_at": None,
            "last_error": None,
        },
        "secrets": ["password"],
    },
}
#: Settings the system writes itself; a client cannot set them.
SYSTEM_FIELDS = {"last_checked_at", "last_error"}
#: Values an integration tracks itself, per integration (never set from the browser).
SYSTEM_BY_NAME = {
    "instagram": {"username", "account_name", "followers", "publish_quota", "publish_used"},
    "marketing": {"last_scan_at", "last_sync_at", "last_analysis_at"},
}


def _fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt(values: Dict[str, str]) -> Optional[str]:
    if not values:
        return None
    return _fernet().encrypt(json.dumps(values).encode("utf-8")).decode("ascii")


def _decrypt(token: Optional[str]) -> Dict[str, str]:
    if not token:
        return {}
    try:
        return json.loads(_fernet().decrypt(token.encode("ascii")))
    except InvalidToken:
        # SECRET_KEY changed since these were saved. Treat them as unset so the
        # page asks for them again, rather than failing every request.
        logger.error("Integration credentials could not be decrypted; SECRET_KEY has changed.")
        return {}


def _check_name(name: str) -> None:
    if name not in DEFINITIONS:
        raise ValidationError("Unknown integration '{}'.".format(name))


def get(session: Session, name: str) -> IntegrationSetting:
    """The integration's row, or an unsaved one holding the defaults."""
    _check_name(name)
    row = session.get(IntegrationSetting, name)
    if row is None:
        row = IntegrationSetting(name=name, enabled=False, config={}, secrets=None)
    row.config = {**DEFINITIONS[name]["config"], **(row.config or {})}
    if name == AI and not row.config.get("model"):
        row.config = {**row.config, "model": default_model()}
    return row


def credentials(row: IntegrationSetting) -> Dict[str, str]:
    """The decrypted credentials. For server-side use only."""
    return _decrypt(row.secrets)


def view(row: IntegrationSetting) -> Dict[str, Any]:
    """What the browser may see: settings, and whether each credential is set."""
    secrets = credentials(row)
    return {
        "name": row.name,
        "enabled": row.enabled,
        "config": row.config,
        "credentials": {
            key: {"set": bool(secrets.get(key)), "hint": _hint(secrets.get(key))}
            for key in DEFINITIONS[row.name]["secrets"]
        },
        "updated_at": row.updated_at,
    }


def _hint(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return "…" + value[-4:] if len(value) > 8 else "set"


def update(
    session: Session,
    name: str,
    enabled: Optional[bool] = None,
    config: Optional[Dict[str, Any]] = None,
    secrets: Optional[Dict[str, Optional[str]]] = None,
) -> IntegrationSetting:
    """Save settings. A credential left out is kept; an empty string clears it."""
    _check_name(name)
    definition = DEFINITIONS[name]
    try:
        begin_write(session)
        row = session.get(IntegrationSetting, name)
        if row is None:
            row = IntegrationSetting(name=name, enabled=False, config={}, secrets=None)
            session.add(row)

        merged = {**definition["config"], **(row.config or {})}
        for key, value in (config or {}).items():
            if key not in definition["config"] or key in SYSTEM_FIELDS or key in SYSTEM_BY_NAME.get(name, ()):
                raise ValidationError("'{}' is not a setting of the {} integration.".format(key, name))
            merged[key] = value.strip() if isinstance(value, str) else value
        _validate_config(name, merged)
        row.config = merged

        stored = credentials(row)
        for key, value in (secrets or {}).items():
            if key not in definition["secrets"]:
                raise ValidationError("'{}' is not a credential of the {} integration.".format(key, name))
            if value is None:
                continue
            if value.strip() == "":
                stored.pop(key, None)
            else:
                stored[key] = value.strip()
        row.secrets = _encrypt(stored)

        if enabled is not None:
            row.enabled = bool(enabled)
        if row.enabled:
            _require_ready(name, merged, stored)
        session.commit()
    except Exception:
        session.rollback()
        raise
    logger.info("Updated %s integration (enabled=%s)", name, row.enabled)
    return get(session, name)


def record_system(session: Session, name: str, **values: Any) -> None:
    """Store a value the system tracks itself, e.g. when the inbox was last read."""
    row = session.get(IntegrationSetting, name)
    if row is None:
        return
    row.config = {**(row.config or {}), **values}
    session.commit()


def _validate_ai(config: Dict[str, Any]) -> None:
    model = str(config.get("model") or "").strip()
    if model and not MODEL_PATTERN.match(model):
        raise ValidationError("Choose a Gemini model, such as gemini-3.8-flash.")
    config["model"] = model.replace("models/", "", 1)
    if config.get("change_policy") not in CHANGE_POLICIES:
        raise ValidationError("Choose when the assistant must ask before changing data.")
    try:
        temperature = float(config.get("temperature", 0.2))
    except (TypeError, ValueError):
        raise ValidationError("Temperature must be a number between 0 and 1.")
    if not 0 <= temperature <= 1:
        raise ValidationError("Temperature must be between 0 and 1.")
    config["temperature"] = temperature
    if config.get("voice_provider", "gemini") not in VOICE_PROVIDERS:
        raise ValidationError("Voice calls run on Gemini or Sarvam.")
    if config.get("sarvam_language", "hi-IN") not in SARVAM_LANGUAGES:
        raise ValidationError("Unknown call language.")
    for key, limit in (("sarvam_chat_model", 80), ("sarvam_tts_model", 40), ("sarvam_voice", 60), ("voice_llm_base_url", 200)):
        config[key] = str(config.get(key) or "").strip()[:limit]
    if config.get("voice_chat", "gemini") not in ("gemini", "sarvam"):
        raise ValidationError("The call's chat model is Gemini or a Sarvam/compatible model.")
    config["voice_gemini_model"] = str(config.get("voice_gemini_model") or "gemini-3.5-flash-lite").strip()[:80]
    if config["voice_llm_base_url"] and not config["voice_llm_base_url"].startswith("https://"):
        raise ValidationError("The chat model address must start with https://.")
    for key, limit in (("company_profile", 30000), ("company_hours", 2000), ("company_delivery", 4000), ("company_payment", 4000),
                       ("company_policies", 8000), ("agent_name", 40), ("agent_tone", 120)):
        config[key] = str(config.get(key) or "")[:limit]


def _validate_config(name: str, config: Dict[str, Any]) -> None:
    if name == AI:
        _validate_ai(config)
    for key, default in DEFINITIONS[name]["config"].items():
        if isinstance(default, bool) and not isinstance(config.get(key), bool):
            config[key] = str(config.get(key)).lower() in ("1", "true", "yes", "on")
    if name == TALLY:
        if config.get("invoice_on", "order") not in ("order", "delivery"):
            raise ValidationError("Invoice on must be order or delivery.")
        if config["tax_mode"] not in TAX_MODES:
            raise ValidationError("Tax must be none, CGST + SGST, or IGST.")
        try:
            rate = float(config["gst_rate"] or 0)
        except (TypeError, ValueError):
            raise ValidationError("GST rate must be a number.")
        if not 0 <= rate <= 100:
            raise ValidationError("GST rate must be between 0 and 100.")
        config["gst_rate"] = rate
        url = config["server_url"].rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            raise ValidationError("The Tally server address must start with http:// or https://.")
        config["server_url"] = url
    if name == CONTROLS:
        if config["credit_check"] not in CREDIT_MODES:
            raise ValidationError("Credit check must be off, warn or block.")
        for key, high in (("overdue_grace_days", 365), ("max_discount_percent", 100), ("min_margin_percent", 100)):
            try:
                number = float(config[key] or 0)
            except (TypeError, ValueError):
                raise ValidationError("{} must be a number.".format(key.replace("_", " ")))
            if not 0 <= number <= high:
                raise ValidationError("{} must be between 0 and {}.".format(key.replace("_", " "), high))
            config[key] = int(number) if key == "overdue_grace_days" else number
    if name == WHATSAPP:
        config["country_code"] = "".join(ch for ch in str(config["country_code"]) if ch.isdigit())
    if name == MARKETING:
        from . import marketing_policy

        marketing_policy.validate(config)
    if name == INSTAGRAM:
        config["ig_user_id"] = "".join(ch for ch in str(config["ig_user_id"]) if ch.isdigit())
        if config["api_host"] not in ("graph.facebook.com", "graph.instagram.com"):
            raise ValidationError("The Instagram API host must be graph.facebook.com or graph.instagram.com.")
    if name == EMAIL:
        for key, low, high in (("imap_port", 1, 65535), ("smtp_port", 1, 65535), ("poll_minutes", 1, 1440)):
            try:
                number = int(config[key])
            except (TypeError, ValueError):
                raise ValidationError("{} must be a whole number.".format(key.replace("_", " ")))
            if not low <= number <= high:
                raise ValidationError("{} must be between {} and {}.".format(key.replace("_", " "), low, high))
            config[key] = number


def _require_ready(name: str, config: Dict[str, Any], secrets: Dict[str, str]) -> None:
    """An integration can only be switched on with everything it needs."""
    missing: List[str] = []
    if name == AI:
        settings = get_settings()
        if not (secrets.get("api_key") or settings.vertex_api_key or settings.vertex_project):
            raise ValidationError("Add a Gemini API key first.")
    if name == WHATSAPP:
        if not config["phone_number_id"]:
            missing.append("the phone number ID")
        if not config["verify_token"]:
            missing.append("a verify token")
        if config["send_invoices"]:
            if not secrets.get("access_token"):
                missing.append("an access token (to send invoices)")
            if not config["invoice_template"]:
                missing.append("the invoice template name")
    if name == INSTAGRAM:
        if not config["ig_user_id"]:
            missing.append("the Instagram account ID")
        if not secrets.get("access_token"):
            missing.append("an access token")
    if name == TALLY:
        if not config["server_url"]:
            missing.append("the Tally server address")
        if not config["company"]:
            missing.append("the company name")
    if name == EMAIL:
        if not config["imap_host"]:
            missing.append("the IMAP server")
        if not config["username"]:
            missing.append("the username")
        if not secrets.get("password"):
            missing.append("the password")
    if missing:
        raise ValidationError("To switch this on, add {}.".format(", ".join(missing)))


def company_knowledge(session: Session) -> str:
    """Everything the owner wrote about the business, for the agents' prompts."""
    config = get(session, AI).config
    parts = []
    for key, title in (("company_profile", "About the business"), ("company_hours", "Hours"), ("company_delivery", "Delivery"),
                       ("company_payment", "Payment terms"), ("company_policies", "Policies")):
        text = (config.get(key) or "").strip()
        if text:
            parts.append("## {}\n{}".format(title, text))
    return "\n\n".join(parts)
