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
from . import triggers, email_inbox, groups, marketing_rules, tally_sync

logger = logging.getLogger(__name__)

def _paused() -> bool:
    """Settings -> Controls -> 'Automation paused': nothing acts on its own."""
    from . import inbound, integration_settings

    session = inbound.session_factory()
    try:
        return integration_settings.automation_paused(session)
    finally:
        session.close()


def _unless_paused(job: Callable[[], int]) -> Callable[[], int]:
    def run() -> int:
        return 0 if _paused() else job()

    run.__qualname__ = job.__qualname__
    return run


#: Bookkeeping always runs; automation (agents, triggers, marketing) only when not paused.
JOBS: List[Callable[[], int]] = [email_inbox.poll_once, tally_sync.process_due, tally_sync.refresh_statutory, groups.recompute_if_due,
                                 _unless_paused(triggers.tick), _unless_paused(marketing_rules.tick)]


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
