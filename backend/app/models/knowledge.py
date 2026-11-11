"""Knowledge ingestion models: uploaded sources and their processing jobs."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey

SOURCE_TYPES = ("pdf", "docx", "html", "markdown", "text", "url")

# Phase 3 lifecycle. Phase 4 adds generating / validating / needs_review.
JOB_STATUSES = ("queued", "fetching", "extracting", "extracted", "failed")
ACTIVE_JOB_STATUSES = ("queued", "fetching", "extracting")


class KnowledgeSource(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """One uploaded file or submitted URL: the raw origin of knowledge."""

    __tablename__ = "knowledge_sources"
    __table_args__ = (
        CheckConstraint(f"source_type IN {SOURCE_TYPES}", name="type_valid"),
        # The same file can't be uploaded twice into one organization (unless deleted).
        Index(
            "uq_knowledge_sources_org_sha256_live",
            "organization_id",
            "sha256",
            unique=True,
            postgresql_where=text("sha256 IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    uri: Mapped[str | None] = mapped_column(Text)  # submitted URL (web sources)
    final_uri: Mapped[str | None] = mapped_column(Text)  # after redirects
    storage_key: Mapped[str | None] = mapped_column(Text)  # original bytes
    sha256: Mapped[str | None] = mapped_column(String(64))  # NULL until a URL is fetched
    mime_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    page_count: Mapped[int | None] = mapped_column(Integer)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestionJob(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    """Background work item that turns a source into extracted, page-marked text."""

    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint(f"status IN {JOB_STATUSES}", name="status_valid"),
        Index(
            "ix_ingestion_jobs_pending",
            "run_after",
            "created_at",
            postgresql_where=text("status IN ('queued', 'fetching', 'extracting')"),
        ),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Declared so SQLAlchemy knows to INSERT the source before its job (no lazy loading:
    # async code must load related rows explicitly).
    source: Mapped[KnowledgeSource] = relationship(lazy="raise")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extracted_key: Mapped[str | None] = mapped_column(Text)  # page-marked Markdown
    docling_key: Mapped[str | None] = mapped_column(Text)  # full Docling JSON (gz)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
