from typing import Any

from sqlalchemy import CheckConstraint, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey

ORG_STATUSES = ("active", "suspended")


class Organization(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "organizations"
    __table_args__ = (CheckConstraint(f"status IN {ORG_STATUSES}", name="status_valid"),)

    slug: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    knowledge_repo_path: Mapped[str | None] = mapped_column(Text)
