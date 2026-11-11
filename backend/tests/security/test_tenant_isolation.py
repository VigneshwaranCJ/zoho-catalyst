"""Multi-tenant isolation: organization A must never see organization B's data.

We test at two levels:
  1. Through the API (what a real user can reach).
  2. Directly in SQL as the runtime app role, proving RLS holds even if a
     future Python query forgets its `WHERE organization_id = ...` filter.
"""

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.db.session import tenant_session
from app.models.user import User
from tests.conftest import login


async def test_api_lists_only_own_org_users(client: httpx.AsyncClient, make_org) -> None:
    org_a = make_org("alpha")
    make_org("bravo")
    await login(client, org_a.users["org_admin"])

    emails = {u["email"] for u in (await client.get("/api/v1/users")).json()}
    assert emails == {f"{r}@alpha.example" for r in ("org_admin", "editor", "agent", "viewer")}


async def test_api_organization_endpoint_returns_own_org(
    client: httpx.AsyncClient, make_org
) -> None:
    org_a = make_org("alpha")
    make_org("bravo")
    await login(client, org_a.users["viewer"])
    assert (await client.get("/api/v1/organization")).json()["slug"] == "alpha"


async def test_rls_hides_other_tenants_even_without_where_clause(make_org) -> None:
    org_a = make_org("alpha")
    make_org("bravo")
    async with tenant_session(org_a.id) as session:
        rows = (await session.scalars(select(User))).all()  # deliberately unfiltered
    assert {u.organization_id for u in rows} == {org_a.id}


async def test_rls_no_tenant_means_no_rows(make_org) -> None:
    make_org("alpha")
    async with tenant_session(None) as session:
        count = await session.scalar(text("SELECT count(*) FROM users"))
        orgs = await session.scalar(text("SELECT count(*) FROM organizations"))
    assert count == 0 and orgs == 0


async def test_rls_blocks_writing_into_another_tenant(make_org) -> None:
    org_a = make_org("alpha")
    org_b = make_org("bravo")
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_session(org_a.id) as session:
            session.add(
                User(
                    organization_id=org_b.id,
                    email="intruder@bravo.example",
                    display_name="x",
                    role="viewer",
                )
            )
            await session.flush()


async def test_rls_blocks_updating_another_tenant(make_org) -> None:
    org_a = make_org("alpha")
    org_b = make_org("bravo")
    async with tenant_session(org_a.id) as session:
        result = await session.execute(
            text("UPDATE users SET display_name = 'pwned' WHERE organization_id = :b"),
            {"b": org_b.id},
        )
    assert result.rowcount == 0  # type: ignore[attr-defined]


async def test_app_role_cannot_modify_audit_log(make_org) -> None:
    org_a = make_org("alpha")
    with pytest.raises(DBAPIError, match="permission denied"):
        async with tenant_session(org_a.id) as session:
            await session.execute(text("DELETE FROM audit_logs"))


async def test_tenant_setting_does_not_leak_between_transactions(make_org) -> None:
    """set_config(..., is_local=true) must reset when the transaction ends (pooled connections)."""
    org_a = make_org("alpha")
    async with tenant_session(org_a.id) as session:
        assert await session.scalar(text("SELECT count(*) FROM users")) == 4
    async with tenant_session(None) as session:
        assert await session.scalar(text("SELECT count(*) FROM users")) == 0
