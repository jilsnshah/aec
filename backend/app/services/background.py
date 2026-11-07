"""Work that runs on a timer while the server is up.

One thread ticks every ``EMAIL_POLL_TICK_SECONDS`` and runs each job; a job
that fails is logged and the others still run. Every job is safe to run in
several server processes at once (rows are claimed with database locks or
unique keys).
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, List, Optional

from ..config import get_settings
from . import email_inbox, tally_sync

logger = logging.getLogger(__name__)

JOBS: List[Callable[[], int]] = [email_inbox.poll_once, tally_sync.process_due]


class Poller:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="background-jobs", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        tick = max(10, get_settings().email_poll_tick_seconds)
        while not self._stop.wait(tick):
            for job in JOBS:
                try:
                    job()
                except Exception:
                    logger.exception("Background job %s failed", job.__qualname__)


poller = Poller()
