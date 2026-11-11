"""Initial tenancy: organizations, users, refresh_tokens, api_keys, audit_logs + RLS.

Revision ID: 0001
Revises:
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("users", "refresh_tokens", "api_keys", "audit_logs")
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


def _org_fk(nullable: bool = False) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        "organization_id",
        sa.Uuid(),
        sa.ForeignKey("organizations.id", ondelete="CASCADE", name=None),
        nullable=nullable,
        index=True,
    )


def upgrade() -> None:
    app_role = get_settings().postgres_app_user

    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("slug", sa.String(63), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("knowledge_repo_path", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="status_valid"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _org_fk(),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("password_hash", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("organization_id", "email", name="uq_users_org_email"),
        sa.CheckConstraint("role IN ('org_admin', 'editor', 'agent', 'viewer')", name="role_valid"),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _org_fk(),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("jti_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _org_fk(),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "allowed_origins", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column("rate_limit_per_min", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.CheckConstraint("kind IN ('widget_public', 'server_secret')", name="kind_valid"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _org_fk(nullable=True),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.String(64)),
        sa.Column("action", sa.String(100), nullable=False, index=True),
        sa.Column("target_type", sa.String(50)),
        sa.Column("target_id", sa.String(64)),
        sa.Column("ip", postgresql.INET()),
        sa.Column("user_agent", sa.Text()),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # ------------------------------------------------------------------ RLS
    # The app role is NOT the table owner, so these policies always apply to it.
    # The owner role (migrations, seeding, the SECURITY DEFINER login lookup)
    # is intentionally exempt.
    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON organizations "
        f"USING (id = {CURRENT_ORG}) WITH CHECK (id = {CURRENT_ORG})"
    )
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (organization_id = {CURRENT_ORG}) "
            f"WITH CHECK (organization_id = {CURRENT_ORG})"
        )

    # ------------------------------------------------------------------ grants
    op.execute(f"GRANT USAGE ON SCHEMA public TO {app_role}")
    op.execute(f"GRANT SELECT, UPDATE ON organizations TO {app_role}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON users, refresh_tokens, api_keys TO {app_role}"
    )
    op.execute(f"GRANT SELECT, INSERT ON audit_logs TO {app_role}")  # append-only

    # ------------------------------------------------------------------ login lookup
    # At login we don't know the tenant yet, so RLS would hide every user.
    # This narrowly-scoped function (runs as owner) returns only what login needs.
    op.execute(
        """
        CREATE FUNCTION auth_find_login_candidates(p_email citext)
        RETURNS TABLE (
            user_id uuid, organization_id uuid, organization_slug text,
            organization_status text, role text, password_hash text, is_active boolean
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$
            SELECT u.id, u.organization_id, o.slug, o.status, u.role, u.password_hash, u.is_active
            FROM users u JOIN organizations o ON o.id = u.organization_id
            WHERE u.email = p_email
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION auth_find_login_candidates(citext) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION auth_find_login_candidates(citext) TO {app_role}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth_find_login_candidates(citext)")
    for table in ("audit_logs", "api_keys", "refresh_tokens", "users", "organizations"):
        op.drop_table(table)
