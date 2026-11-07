"""Application configuration, loaded from the environment."""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AEC Business Management"
    environment: str = "development"
    #: PostgreSQL only; the application refuses to start against anything else.
    database_url: str = "postgresql+psycopg://aec:aec_dev_password@localhost:5432/aec"

    # Connection pool. Size these against the database's max_connections and
    # the number of application processes.
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1800
    #: Abandon a statement that runs away. 0 disables.
    db_statement_timeout_ms: int = 30000
    #: Fail fast rather than queue behind a long-held row lock. 0 disables.
    db_lock_timeout_ms: int = 10000
    # Comma-separated list of allowed browser origins for the SPA.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    log_level: str = "INFO"
    sql_echo: bool = False

    #: Whether a line may be discounted all the way to zero. Some businesses
    #: forbid giving stock away on an order; set this false to reject a 100%
    #: discount instead of quietly pricing the line at nothing.
    allow_zero_price_lines: bool = True

    #: IANA time zone the business trades in. Daily figures (the dashboard's
    #: sales chart) start and end at local midnight in this zone.
    business_timezone: str = "Asia/Kolkata"

    #: The built web app (``frontend/dist``). When set, the API also serves it,
    #: so one service hosts both on the same origin. Empty in development, where
    #: Vite serves the app.
    frontend_dist: str = ""

    @field_validator("database_url")
    @classmethod
    def _use_psycopg(cls, value: str) -> str:
        """Hosting providers hand out ``postgres://`` or ``postgresql://`` URLs;
        this application uses the psycopg 3 driver, so say so explicitly."""
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix):]
        return value

    @property
    def cors_origin_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
