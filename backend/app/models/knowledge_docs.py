"""OKF knowledge documents, their versions, and the search index.

* knowledge_documents : one row per OKF file path (e.g. policies/warranty.md)
* knowledge_versions  : every draft / approved revision of a document. Drafts
                        live here until a human approves them; approval commits
                        the file to the organization's Git repo (git_commit_sha).
* knowledge_sections  : the live search index, one row per heading section
                        (PostgreSQL full-text search + trigram similarity).
* knowledge_links     : Markdown links between documents (graph, 1-hop expansion).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped, Timestamps, UUIDPrimaryKey

DOC_STATUSES = ("draft", "live", "archived")
REVIEW_STATUSES = ("pending", "approved", "rejected", "superseded")


class KnowledgeDocument(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint(f"status IN {DOC_STATUSES}", name="status_valid"),
        Index(
            "uq_knowledge_documents_org_path_active",
            "organization_id",
            "path",
            unique=True,
            postgresql_where=text("status <> 'archived'"),
        ),
    )

    path: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    audience: Mapped[str] = mapped_column(String(20), nullable=False, default="customer")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_versions.id", ondelete="SET NULL", use_alter=True)
    )


class KnowledgeVersion(UUIDPrimaryKey, Timestamps, TenantScoped, Base):
    __tablename__ = "knowledge_versions"
    __table_args__ = (
        CheckConstraint(f"review_status IN {REVIEW_STATUSES}", name="review_status_valid"),
        UniqueConstraint("document_id", "version_no", name="uq_knowledge_versions_doc_no"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)  # full Markdown incl. frontmatter
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    frontmatter: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    validation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # Which live version this draft was based on (detects concurrent edits).
    base_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_versions.id", ondelete="SET NULL")
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="SET NULL"), index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingestion_jobs.id", ondelete="SET NULL"), index=True
    )
    generated_by: Mapped[str] = mapped_column(String(100), nullable=False)  # OKF actor
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)
    git_commit_sha: Mapped[str | None] = mapped_column(String(64))


class KnowledgeSection(UUIDPrimaryKey, TenantScoped, Base):
    """Search index row: one heading section of a LIVE document version."""

    __tablename__ = "knowledge_sections"
    __table_args__ = (
        Index("ix_knowledge_sections_search", "search_vector", postgresql_using="gin"),
        Index(
            "ix_knowledge_sections_heading_trgm",
            "heading",
            postgresql_using="gin",
            postgresql_ops={"heading": "gin_trgm_ops"},
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_versions.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    anchor: Mapped[str] = mapped_column(String(120), nullable=False)
    heading: Mapped[str] = mapped_column(Text, nullable=False)
    heading_path: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source_pages: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False, default=list)
    audience: Mapped[str] = mapped_column(String(20), nullable=False)
    doc_title: Mapped[str] = mapped_column(Text, nullable=False)
    # Weighted: document title + heading (A) rank above body text (B).
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(doc_title, '') || ' ' || "
            "coalesce(heading, '')), 'A') || setweight(to_tsvector('english', "
            "coalesce(body, '')), 'B')",
            persisted=True,
        ),
    )


class KnowledgeLink(UUIDPrimaryKey, TenantScoped, Base):
    __tablename__ = "knowledge_links"

    from_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    to_path: Mapped[str] = mapped_column(String(255), nullable=False)
