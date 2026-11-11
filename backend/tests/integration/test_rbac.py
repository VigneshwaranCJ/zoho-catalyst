import httpx
import pytest

from tests.conftest import login


@pytest.mark.parametrize(
    ("role", "expected"),
    [("org_admin", 200), ("editor", 403), ("agent", 403), ("viewer", 403)],
)
async def test_only_admins_can_list_users(
    client: httpx.AsyncClient, make_org, role: str, expected: int
) -> None:
    org = make_org("technova")
    await login(client, org.users[role])
    response = await client.get("/api/v1/users")
    assert response.status_code == expected


@pytest.mark.parametrize("role", ["editor", "agent", "viewer"])
async def test_non_admins_cannot_rename_organization(
    client: httpx.AsyncClient, make_org, role: str
) -> None:
    org = make_org("technova")
    csrf = (await login(client, org.users[role])).json()["csrf_token"]
    response = await client.patch(
        "/api/v1/organization", json={"name": "Hacked"}, headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 403


async def test_role_change_applies_immediately(
    client: httpx.AsyncClient, make_org, owner_engine
) -> None:
    """The role is re-read from the DB on every request, not trusted from the token."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    org = make_org("technova")
    admin = org.users["org_admin"]
    await login(client, admin)
    assert (await client.get("/api/v1/users")).status_code == 200

    with Session(owner_engine) as s, s.begin():
        s.execute(text("UPDATE users SET role = 'viewer' WHERE id = :id"), {"id": admin.id})
    assert (await client.get("/api/v1/users")).status_code == 403
