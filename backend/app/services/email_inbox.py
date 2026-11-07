"""Email intake: read unread mail over IMAP and hand it to the enquiry agent.

The inbox is read on the interval set in the integration (and on demand from
the Integrations page). Each unread message is recorded once -- keyed by its
Message-ID -- then marked read, and the agent decides whether it is an
enquiry. Mail is fetched with ``BODY.PEEK[]`` so a message that fails to be
recorded stays unread and is picked up next time.
"""
from __future__ import annotations

import email
import hashlib
import html
import imaplib
import logging
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import ValidationError
from . import inbound
from . import integration_settings as settings_service

logger = logging.getLogger(__name__)

CHANNEL = "email"
#: Most messages read in one check; the rest wait for the next one.
BATCH_LIMIT = 50
#: Longest body handed to the agent.
MAX_BODY_CHARS = 20000

#: Opens the IMAP connection: (host, port) -> client. Tests replace it.
imap_factory: Callable[[str, int], Any] = lambda host, port: imaplib.IMAP4_SSL(host, port, timeout=30)


def _header(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:
        return value.strip()


def _text_of(message: Message) -> str:
    """The readable text of a message: the plain-text part, else the HTML stripped."""
    plain, rich = [], []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if part.get_content_type() == "text/plain":
            plain.append(text)
        elif part.get_content_type() == "text/html":
            rich.append(text)
    if plain:
        return "\n".join(plain).strip()
    if rich:
        stripped = re.sub(r"(?is)<(script|style).*?</\1>", " ", "\n".join(rich))
        stripped = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", stripped)
        stripped = re.sub(r"<[^>]+>", " ", stripped)
        return re.sub(r"[ \t]+", " ", html.unescape(stripped)).strip()
    return ""


def parse_email(raw: bytes) -> Dict[str, Any]:
    """The parts of an email the agent needs, from its raw RFC 822 bytes."""
    message = email.message_from_bytes(raw)
    name, address = parseaddr(_header(message.get("From")))
    received = None
    try:
        received = parsedate_to_datetime(message.get("Date"))
        if received is not None and received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass
    message_id = (message.get("Message-ID") or "").strip()
    return {
        # A message without a Message-ID is keyed by its content instead.
        "external_id": message_id or "sha256:" + hashlib.sha256(raw).hexdigest(),
        "sender": address.lower() or "unknown",
        "sender_name": name or None,
        "subject": _header(message.get("Subject")) or None,
        "body": _text_of(message)[:MAX_BODY_CHARS],
        "received_at": received,
    }


def check_inbox(session: Session) -> List[uuid.UUID]:
    """Read unread mail now. Returns the ids of newly recorded messages."""
    row = settings_service.get(session, settings_service.EMAIL)
    config = row.config
    password = settings_service.credentials(row).get("password")
    if not (config.get("imap_host") and config.get("username") and password):
        raise ValidationError("Email is not set up: add the IMAP server, username and password.")

    recorded: List[uuid.UUID] = []
    error: Optional[str] = None
    client = None
    try:
        client = imap_factory(config["imap_host"], int(config["imap_port"]))
        client.login(config["username"], password)
        status, _ = client.select(config.get("folder") or "INBOX")
        if status != "OK":
            raise ValidationError("The folder '{}' could not be opened.".format(config.get("folder")))
        status, data = client.search(None, "UNSEEN")
        numbers = (data[0] or b"").split() if status == "OK" else []
        for number in numbers[:BATCH_LIMIT]:
            status, parts = client.fetch(number, "(BODY.PEEK[])")
            raw = next((part[1] for part in parts or [] if isinstance(part, tuple)), None)
            if status != "OK" or raw is None:
                continue
            fields = parse_email(raw)
            if fields["body"]:
                stored = inbound.record(session, CHANNEL, **fields)
                if stored is not None:
                    recorded.append(stored.id)
            client.store(number, "+FLAGS", "\\Seen")
    except ValidationError:
        raise
    except (imaplib.IMAP4.error, OSError) as exc:
        error = "Could not read the inbox: {}".format(exc)
        logger.warning("Email check failed: %s", exc)
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass
        settings_service.record_system(
            session,
            settings_service.EMAIL,
            last_checked_at=datetime.now(timezone.utc).isoformat(),
            last_error=error,
        )
    if error:
        raise ValidationError(error)
    return recorded


def _due(config: Dict[str, Any]) -> bool:
    last = config.get("last_checked_at")
    if not last:
        return True
    try:
        last_at = datetime.fromisoformat(last)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - last_at >= timedelta(minutes=int(config.get("poll_minutes") or 5))


def poll_once() -> int:
    """One tick of the background poller: read the inbox if it is due."""
    session = inbound.session_factory()
    try:
        row = settings_service.get(session, settings_service.EMAIL)
        if not row.enabled or not _due(row.config):
            return 0
        try:
            ids = check_inbox(session)
        except ValidationError as exc:
            logger.warning("Scheduled email check: %s", exc.message)
            return 0
    finally:
        session.close()
    for message_id in ids:
        inbound.process(message_id)
    return len(ids)


class Poller:
    """Reads the inbox in the background while the server runs."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="email-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        tick = max(10, get_settings().email_poll_tick_seconds)
        while not self._stop.wait(tick):
            try:
                poll_once()
            except Exception:
                logger.exception("Email poller tick failed")


poller = Poller()
