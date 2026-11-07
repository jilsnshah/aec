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

#: The Claude models the enquiry agent may use, most capable first.
AI_MODELS: List[Dict[str, str]] = [
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "hint": "Most capable. The default."},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "hint": "Fast and capable."},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "hint": "Fastest and lowest cost."},
]
DEFAULT_MODEL = "claude-opus-5-5"

#: Per integration: default plain settings, and the names of its credentials.
DEFINITIONS: Dict[str, Dict[str, Any]] = {
    AI: {"config": {"model": DEFAULT_MODEL}, "secrets": ["api_key"]},
    WHATSAPP: {
        "config": {"phone_number_id": "", "business_account_id": "", "verify_token": ""},
        "secrets": ["app_secret"],
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


def _validate_config(name: str, config: Dict[str, Any]) -> None:
    if name == AI and config["model"] not in {model["id"] for model in AI_MODELS}:
        raise ValidationError("Choose one of the listed models.")
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
    if name == AI and not secrets.get("api_key"):
        missing.append("an API key")
    if name == WHATSAPP:
        if not config["phone_number_id"]:
            missing.append("the phone number ID")
        if not config["verify_token"]:
            missing.append("a verify token")
    if name == EMAIL:
        if not config["imap_host"]:
            missing.append("the IMAP server")
        if not config["username"]:
            missing.append("the username")
        if not secrets.get("password"):
            missing.append("the password")
    if missing:
        raise ValidationError("To switch this on, add {}.".format(", ".join(missing)))
