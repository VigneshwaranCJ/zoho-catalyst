"""Application settings.

All configuration comes from environment variables (or a `.env` file).
`pydantic-settings` validates types at startup, so a missing or malformed
value fails fast with a clear error instead of breaking later at runtime.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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

    def _dsn(self, user: str, password: SecretStr, db: str | None = None) -> str:
        return (
            f"postgresql+psycopg://{user}:{password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{db or self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def app_database_url(self) -> str:
        """Runtime connection: non-owner role, subject to Row-Level Security."""
        return self._dsn(self.postgres_app_user, self.postgres_app_password)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def owner_database_url(self) -> str:
        """Migrations/seeding connection: table owner role."""
        return self._dsn(self.postgres_owner_user, self.postgres_owner_password)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
