"""Engine, session factory and concurrency wiring.

PostgreSQL only. The system is an inventory ledger whose correctness depends on
row-level locking: every operation that changes a product's stock or its
reservations takes ``SELECT ... FOR UPDATE`` on the rows it is about to touch,
so concurrent receipts, orders and deliveries serialise per product instead of
racing. Nothing here degrades gracefully to a database without that, which is
why the URL is checked rather than adapted.
"""
from __future__ import annotations

from typing import Iterator, List, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

#: URL schemes this application supports.
SUPPORTED_PREFIXES = ("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")


class UnsupportedDatabaseError(RuntimeError):
    """Raised when DATABASE_URL points at something other than PostgreSQL."""


def _check_url(database_url: str) -> str:
    if not database_url:
        raise UnsupportedDatabaseError(
            "DATABASE_URL is not set. This application requires PostgreSQL, for example "
            "postgresql+psycopg://user:password@localhost:5432/aec"
        )
    if not database_url.startswith(SUPPORTED_PREFIXES):
        raise UnsupportedDatabaseError(
            "DATABASE_URL must be a PostgreSQL URL (got {!r}). The inventory rules rely on "
            "row-level locking, so SQLite and other backends are not supported. Use "
            "postgresql+psycopg://user:password@host:5432/dbname".format(
                database_url.split("://")[0] + "://..."
            )
        )
    return database_url


def create_app_engine(
    database_url: str,
    echo: bool = False,
    schema: Optional[str] = None,
) -> Engine:
    """Build an engine with production-shaped pooling and server-side timeouts.

    ``schema`` sets ``search_path`` on every connection, which the test suite
    uses to give each test its own schema in one database.
    """
    settings = get_settings()
    _check_url(database_url)

    options: List[str] = []
    if schema:
        options.append("-csearch_path={}".format(schema))
    if settings.db_lock_timeout_ms > 0:
        # A request that cannot get a row lock fails fast instead of piling up.
        options.append("-clock_timeout={}".format(settings.db_lock_timeout_ms))
    if settings.db_statement_timeout_ms > 0:
        options.append("-cstatement_timeout={}".format(settings.db_statement_timeout_ms))

    connect_args = {"application_name": settings.app_name}
    if options:
        connect_args["options"] = " ".join(options)

    return create_engine(
        database_url,
        echo=echo,
        future=True,
        # Recycle before most proxies and PostgreSQL's own idle timeouts bite,
        # and check a pooled connection is still alive before handing it out.
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle_seconds,
        pool_timeout=settings.db_pool_timeout_seconds,
        connect_args=connect_args,
    )


_settings = get_settings()
engine: Engine = create_app_engine(_settings.database_url, echo=_settings.sql_echo)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def begin_write(session: Session) -> None:
    """Start a write operation from a clean transaction.

    A session that still holds an idle read transaction would carry its
    identity map into the write. Rolling that back first costs nothing -- there
    is nothing to lose before the first write -- and guarantees the locks taken
    below it are read against freshly committed data.
    """
    if session.in_transaction():
        session.rollback()


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
