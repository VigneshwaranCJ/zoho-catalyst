"""knowledge_sources + ingestion_jobs (with RLS) and the worker's job-claim function.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CURRENT_ORG = "NULLIF(current_setting('app.current_org', true), '')::uuid"


def _timestamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    app_role = get_settings().postgres_app_user

    op.create_table(
        "knowledge_sources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("uri", sa.Text()),
        sa.Column("final_uri", sa.Text()),
        sa.Column("storage_key", sa.Text()),
        sa.Column("sha256", sa.String(64)),
        sa.Column("mime_type", sa.String(100)),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("page_count", sa.Integer()),
        sa.Column("uploaded_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.CheckConstraint(
            "source_type IN ('pdf', 'docx', 'html', 'markdown', 'text', 'url')", name="type_valid"
        ),
    )
    # The same file can't be uploaded twice into one organization (unless deleted).
    op.create_index(
        "uq_knowledge_sources_org_sha256_live",
        "knowledge_sources",
        ["organization_id", "sha256"],
        unique=True,
        postgresql_where=sa.text("sha256 IS NOT NULL AND deleted_at IS NULL"),
    )

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "source_id",
            sa.Uuid(),
            sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column(
            "run_after", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("locked_by", sa.String(100)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("extracted_key", sa.Text()),
        sa.Column("docling_key", sa.Text()),
        sa.Column("stats", postgresql.JSONB(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('queued', 'fetching', 'extracting', 'extracted', 'failed')",
            name="status_valid",
        ),
    )
    # The worker's "find the next job" query only looks at queued/running jobs.
    op.create_index(
        "ix_ingestion_jobs_pending",
        "ingestion_jobs",
        ["run_after", "created_at"],
        postgresql_where=sa.text("status IN ('queued', 'fetching', 'extracting')"),
    )

    for table in ("knowledge_sources", "ingestion_jobs"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (organization_id = {CURRENT_ORG}) WITH CHECK (organization_id = {CURRENT_ORG})"
        )
    # Sources are soft-deleted (UPDATE deleted_at), never hard-deleted by the app.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON knowledge_sources, ingestion_jobs TO {app_role}")

    # The worker serves ALL organizations, but RLS would hide every job from it.
    # This owner-run function hands out exactly one job id at a time:
    #   * FOR UPDATE SKIP LOCKED: several workers never grab the same job.
    #   * Jobs stuck in a running state longer than p_stale_after (crashed worker)
    #     are picked up again.
    # The worker then processes the job inside a normal tenant-scoped session.
    op.execute(
        """
        CREATE FUNCTION ingestion_claim_next_job(p_worker text, p_stale_after interval)
        RETURNS TABLE (job_id uuid, organization_id uuid)
        LANGUAGE sql VOLATILE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            UPDATE ingestion_jobs j
               SET status = CASE WHEN s.source_type = 'url' THEN 'fetching' ELSE 'extracting' END,
                   locked_at = now(), locked_by = p_worker, attempts = j.attempts + 1,
                   started_at = COALESCE(j.started_at, now()), updated_at = now()
              FROM knowledge_sources s
             WHERE j.id = (
                   SELECT id FROM ingestion_jobs
                    WHERE (status = 'queued' AND run_after <= now())
                       OR (status IN ('fetching', 'extracting')
                           AND locked_at < now() - p_stale_after)
                    ORDER BY run_after, created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1)
              AND s.id = j.source_id
            RETURNING j.id, j.organization_id
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION ingestion_claim_next_job(text, interval) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION ingestion_claim_next_job(text, interval) TO {app_role}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS ingestion_claim_next_job(text, interval)")
    op.drop_table("ingestion_jobs")
    op.drop_table("knowledge_sources")
