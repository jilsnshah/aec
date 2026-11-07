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

    #: Encrypts integration credentials (AI API key, email password, WhatsApp
    #: app secret) at rest. Set a long random value in production and keep it:
    #: changing it makes saved credentials unreadable, and they must be entered
    #: again.
    secret_key: str = "dev-only-insecure-secret-key-change-me"

    # AI credentials. Set on the server only -- users can switch the AI on or
    # off and pick a model, never see or change these. A model is offered only
    # when its provider has credentials here.
    #: Gemini on Vertex AI, express-mode API key ("AQ...").
    vertex_api_key: str = ""
    #: Gemini on Vertex AI with Application Default Credentials (local
    #: development: gcloud auth application-default login). Ignored when
    #: vertex_api_key is set.
    vertex_project: str = ""
    vertex_location: str = "global"
    #: Claude through the Anthropic API.
    anthropic_api_key: str = ""

    #: The first admin, created at startup when nobody can sign in yet.
    #: Change the password from the app afterwards; these are not re-read.
    admin_username: str = ""
    admin_password: str = ""
    #: How long a sign-in lasts.
    session_days: int = 7

    #: How often the email inbox may be polled at most, in seconds.
    email_poll_tick_seconds: int = 60

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
