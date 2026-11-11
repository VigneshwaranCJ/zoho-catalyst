"""OKF knowledge: documents, versions (drafts + history), search sections, links.

Also extends ingestion job statuses for AI generation and review.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CURRENT_ORG = "NULLIF(current_setting('app.current_org', true), '')::uuid"
OLD_STATUSES = "('queued', 'fetching', 'extracting', 'extracted', 'failed')"
NEW_STATUSES = (
    "('queued', 'fetching', 'extracting', 'extracted', 'generating', "
    "'needs_review', 'reviewed', 'failed')"
)
SEARCH_VECTOR = (
    "setweight(to_tsvector('english', coalesce(doc_title, '') || ' ' || "
    "coalesce(heading, '')), 'A') || setweight(to_tsvector('english', "
    "coalesce(body, '')), 'B')"
)


def _org_fk() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        "organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )  # fmt: skip


def _timestamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _claim_function(stale_statuses: str) -> str:
    return f"""
        CREATE OR REPLACE FUNCTION ingestion_claim_next_job(p_worker text, p_stale_after interval)
        RETURNS TABLE (job_id uuid, organization_id uuid)
        LANGUAGE sql VOLATILE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            UPDATE ingestion_jobs j
               SET status = CASE WHEN s.source_type = 'url' AND j.extracted_key IS NULL
                                 THEN 'fetching' ELSE 'extracting' END,
                   locked_at = now(), locked_by = p_worker, attempts = j.attempts + 1,
                   started_at = COALESCE(j.started_at, now()), updated_at = now()
              FROM knowledge_sources s
             WHERE j.id = (
                   SELECT id FROM ingestion_jobs
                    WHERE (status = 'queued' AND run_after <= now())
                       OR (status IN {stale_statuses} AND locked_at < now() - p_stale_after)
                    ORDER BY run_after, created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1)
              AND s.id = j.source_id
            RETURNING j.id, j.organization_id
        $$
    """


def upgrade() -> None:
    app_role = get_settings().postgres_app_user
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ---- ingestion job statuses for AI generation + review
    op.drop_constraint(op.f("ck_ingestion_jobs_status_valid"), "ingestion_jobs", type_="check")
    op.create_check_constraint("status_valid", "ingestion_jobs", f"status IN {NEW_STATUSES}")
    op.drop_index("ix_ingestion_jobs_pending", table_name="ingestion_jobs")
    op.create_index(
        "ix_ingestion_jobs_pending", "ingestion_jobs", ["run_after", "created_at"],
        postgresql_where=sa.text("status IN ('queued', 'fetching', 'extracting', 'generating')"),
    )  # fmt: skip
    op.execute(_claim_function("('fetching', 'extracting', 'generating')"))

    # ---- documents / versions
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _org_fk(),
        sa.Column("path", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("doc_type", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("audience", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("current_version_id", sa.Uuid()),
        *_timestamps(),
        sa.CheckConstraint("status IN ('draft', 'live', 'archived')", name="status_valid"),
    )
    op.create_index(
        "uq_knowledge_documents_org_path_active", "knowledge_documents",
        ["organization_id", "path"], unique=True,
        postgresql_where=sa.text("status <> 'archived'"),
    )  # fmt: skip
    op.create_table(
        "knowledge_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _org_fk(),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("frontmatter", postgresql.JSONB(), nullable=False),
        sa.Column("validation", postgresql.JSONB(), nullable=False),
        sa.Column("review_status", sa.String(20), nullable=False),
        sa.Column("base_version_id", sa.Uuid(), sa.ForeignKey("knowledge_versions.id", ondelete="SET NULL")),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("knowledge_sources.id", ondelete="SET NULL"), index=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("ingestion_jobs.id", ondelete="SET NULL"), index=True),
        sa.Column("generated_by", sa.String(100), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_note", sa.Text()),
        sa.Column("git_commit_sha", sa.String(64)),
        *_timestamps(),
        sa.CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected', 'superseded')",
            name="review_status_valid",
        ),
        sa.UniqueConstraint("document_id", "version_no", name="uq_knowledge_versions_doc_no"),
    )
    op.create_foreign_key(
        "fk_knowledge_documents_current_version_id_knowledge_versions",
        "knowledge_documents", "knowledge_versions", ["current_version_id"], ["id"],
        ondelete="SET NULL",
    )  # fmt: skip

    # ---- search index + links
    op.create_table(
        "knowledge_sections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _org_fk(),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("knowledge_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("anchor", sa.String(120), nullable=False),
        sa.Column("heading", sa.Text(), nullable=False),
        sa.Column("heading_path", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source_pages", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("audience", sa.String(20), nullable=False),
        sa.Column("doc_title", sa.Text(), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(), sa.Computed(SEARCH_VECTOR, persisted=True)),
    )
    op.create_index(
        "ix_knowledge_sections_search", "knowledge_sections", ["search_vector"],
        postgresql_using="gin",
    )  # fmt: skip
    op.create_index(
        "ix_knowledge_sections_heading_trgm", "knowledge_sections", ["heading"],
        postgresql_using="gin", postgresql_ops={"heading": "gin_trgm_ops"},
    )  # fmt: skip
    op.create_table(
        "knowledge_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _org_fk(),
        sa.Column("from_document_id", sa.Uuid(), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("to_path", sa.String(255), nullable=False),
    )

    for table in ("knowledge_documents", "knowledge_versions", "knowledge_sections", "knowledge_links"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (organization_id = {CURRENT_ORG}) WITH CHECK (organization_id = {CURRENT_ORG})"
        )
    # Documents and versions are history: never deleted by the app.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON knowledge_documents, knowledge_versions TO {app_role}")
    # The search index and links are rebuilt on publish.
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON knowledge_sections, knowledge_links TO {app_role}")


def downgrade() -> None:
    for table in ("knowledge_links", "knowledge_sections"):
        op.drop_table(table)
    op.drop_constraint(
        op.f("fk_knowledge_documents_current_version_id_knowledge_versions"), "knowledge_documents",
        type_="foreignkey",
    )  # fmt: skip
    op.drop_table("knowledge_versions")
    op.drop_table("knowledge_documents")
    op.execute(_claim_function("('fetching', 'extracting')"))
    op.drop_index("ix_ingestion_jobs_pending", table_name="ingestion_jobs")
    op.create_index(
        "ix_ingestion_jobs_pending", "ingestion_jobs", ["run_after", "created_at"],
        postgresql_where=sa.text("status IN ('queued', 'fetching', 'extracting')"),
    )  # fmt: skip
    op.drop_constraint(op.f("ck_ingestion_jobs_status_valid"), "ingestion_jobs", type_="check")
    op.create_check_constraint("status_valid", "ingestion_jobs", f"status IN {OLD_STATUSES}")
