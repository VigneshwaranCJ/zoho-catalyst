from datetime import datetime

from sqlalchemy import ARRAY, CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey

API_KEY_KINDS = ("widget_public", "server_secret")


class ApiKey(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """Widget public keys and server secret keys. Only a SHA-256 hash is stored."""

    __tablename__ = "api_keys"
    __table_args__ = (CheckConstraint(f"kind IN {API_KEY_KINDS}", name="kind_valid"),)

    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    allowed_origins: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
