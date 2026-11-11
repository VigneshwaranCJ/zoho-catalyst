"""Application settings.

All configuration comes from environment variables (or a `.env` file).
`pydantic-settings` validates types at startup, so a missing or malformed
value fails fast with a clear error instead of breaking later at runtime.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy import URL

# The repo-root .env (one level above backend/) is shared with Docker Compose.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General ---
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = False

    # --- Security ---
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    cookie_secure: bool = False
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    # --- PostgreSQL ---
    postgres_db: str = "csp"
    postgres_owner_user: str = "csp_owner"
    postgres_owner_password: SecretStr = SecretStr("")
    postgres_app_user: str = "csp_app"
    postgres_app_password: SecretStr = SecretStr("")
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432

    # --- Valkey / Redis ---
    redis_url: str = "redis://127.0.0.1:6379/0"

    # --- Seed (development only) ---
    seed_admin_email: str = "admin@technova.example"
    seed_admin_password: SecretStr = SecretStr("")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        # Allow CORS_ORIGINS="a,b" in .env (NoDecode keeps it as a raw string).
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _refuse_unsafe_production_config(self) -> "Settings":
        """Fail at startup rather than run production with development-grade settings."""
        if self.app_env != "production":
            return self
        problems = []
        secret = self.jwt_secret.get_secret_value()
        if "change-me" in secret or len(secret) < 48:
            problems.append("JWT_SECRET must be a unique random value of at least 48 characters")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true (cookies only over HTTPS)")
        for name in ("postgres_owner_password", "postgres_app_password"):
            value = getattr(self, name).get_secret_value()
            if len(value) < 16 or "dev" in value.lower():
                problems.append(f"{name.upper()} must be a strong, non-development password")
        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self

    def _dsn(self, user: str, password: SecretStr) -> URL:
        # URL.create escapes special characters (@ : / # %) in passwords, and
        # str(url) masks the password, so it can't leak into logs by accident.
        return URL.create(
            "postgresql+psycopg",
            username=user,
            password=password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def app_database_url(self) -> URL:
        """Runtime connection: non-owner role, subject to Row-Level Security."""
        return self._dsn(self.postgres_app_user, self.postgres_app_password)

    @property
    def owner_database_url(self) -> URL:
        """Migrations/seeding connection: table owner role."""
        return self._dsn(self.postgres_owner_user, self.postgres_owner_password)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
