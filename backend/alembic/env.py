"""Alembic environment. PostgreSQL only; the URL comes from app settings."""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from app.config import get_settings
from app.database import create_app_engine
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
settings = get_settings()


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_app_engine(settings.database_url)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # PostgreSQL applies DDL inside the migration's transaction, so a
            # failed migration leaves the schema exactly as it was.
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
