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
        },
        "secrets": ["api_key"],
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
            "template_language": "en",
            "country_code": "91",
            "graph_version": "v23.0",
        },
        "secrets": ["app_secret", "access_token"],
    },
    TALLY: {
        "config": {
            # TallyPrime's HTTP server, e.g. http://tally.example.com:9000
            "server_url": "",
            "company": "",
            "sync_sales_orders": True,
            "create_invoices": True,
            "sync_purchase_orders": True,
            "customer_group": "Sundry Debtors",
            "supplier_group": "Sundry Creditors",
            "godown": "Main Location",
            "sales_ledger": "Sales",
            "purchase_ledger": "Purchase",
            "sales_order_type": "Sales Order",
            "sales_invoice_type": "Sales",
            "purchase_order_type": "Purchase Order",
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
            if key not in definition["config"] or key in SYSTEM_FIELDS:
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


def _validate_config(name: str, config: Dict[str, Any]) -> None:
    if name == AI:
        _validate_ai(config)
    for key, default in DEFINITIONS[name]["config"].items():
        if isinstance(default, bool) and not isinstance(config.get(key), bool):
            config[key] = str(config.get(key)).lower() in ("1", "true", "yes", "on")
    if name == TALLY:
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
    if name == EMAIL:
        for key, low, high in (("imap_port", 1, 65535), ("poll_minutes", 1, 1440)):
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
