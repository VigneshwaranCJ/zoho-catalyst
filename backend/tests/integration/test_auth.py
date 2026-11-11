import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import ACCESS_COOKIE, CSRF_COOKIE, REFRESH_COOKIE
from app.models.audit_log import AuditLog
from tests.conftest import login


async def test_login_sets_httponly_cookies_and_returns_user(
    client: httpx.AsyncClient, make_org
) -> None:
    org = make_org("technova")
    response = await login(client, org.users["org_admin"])

    body = response.json()
    assert body["user"]["email"] == "org_admin@technova.example"
    assert body["user"]["role"] == "org_admin"
    assert "org:manage" in body["user"]["permissions"]

    set_cookie = response.headers.get_list("set-cookie")
    access = next(c for c in set_cookie if c.startswith(f"{ACCESS_COOKIE}="))
    refresh = next(c for c in set_cookie if c.startswith(f"{REFRESH_COOKIE}="))
    csrf = next(c for c in set_cookie if c.startswith(f"{CSRF_COOKIE}="))
    assert "HttpOnly" in access and "SameSite=lax" in access
    assert "HttpOnly" in refresh and "Path=/api/v1/auth" in refresh
    assert "HttpOnly" not in csrf  # JS must be able to read the CSRF token
    assert body["csrf_token"] in csrf


async def test_me_requires_authentication(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_me_with_cookie(client: httpx.AsyncClient, make_org) -> None:
    org = make_org("technova")
    await login(client, org.users["viewer"])
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["role"] == "viewer"


async def test_wrong_password_and_unknown_email_look_identical(
    client: httpx.AsyncClient, make_org
) -> None:
    org = make_org("technova")
    wrong = await client.post(
        "/api/v1/auth/login",
        json={"email": org.users["viewer"].email, "password": "nope-nope-nope"},
    )
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "ghost@nowhere.example", "password": "nope-nope-nope"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()  # no user-enumeration hints


async def test_failed_login_is_audited(client: httpx.AsyncClient, make_org, owner_engine) -> None:
    org = make_org("technova")
    await client.post(
        "/api/v1/auth/login",
        json={"email": org.users["viewer"].email, "password": "bad-password-1"},
    )
    with Session(owner_engine) as s:
        actions = s.scalars(select(AuditLog.action)).all()
    assert "auth.login_failed" in actions


async def test_login_is_rate_limited(client: httpx.AsyncClient, make_org) -> None:
    org = make_org("technova")
    payload = {"email": org.users["viewer"].email, "password": "bad-password-1"}
    codes = [(await client.post("/api/v1/auth/login", json=payload)).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5
    assert codes[5] == 429


async def test_disabled_user_cannot_log_in(
    client: httpx.AsyncClient, make_org, owner_engine
) -> None:
    org = make_org("technova")
    with Session(owner_engine) as s, s.begin():
        s.execute(
            text("UPDATE users SET is_active = false WHERE email = :e"),
            {"e": org.users["viewer"].email},
        )
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": org.users["viewer"].email, "password": org.users["viewer"].password},
    )
    assert response.status_code == 401


async def test_refresh_rotates_and_detects_reuse(client: httpx.AsyncClient, make_org) -> None:
    org = make_org("technova")
    await login(client, org.users["viewer"])
    old_refresh = client.cookies.get(REFRESH_COOKIE)

    rotated = await client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200
    new_refresh = client.cookies.get(REFRESH_COOKIE)
    assert new_refresh and new_refresh != old_refresh

    # Replaying the old (now revoked) token = possible theft -> rejected,
    # and every session of that user is revoked, including the new one.
    client.cookies.set(REFRESH_COOKIE, old_refresh, path="/api/v1/auth")
    replay = await client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401

    client.cookies.set(REFRESH_COOKIE, new_refresh, path="/api/v1/auth")
    after = await client.post("/api/v1/auth/refresh")
    assert after.status_code == 401


async def test_logout_revokes_refresh_token(client: httpx.AsyncClient, make_org) -> None:
    org = make_org("technova")
    await login(client, org.users["viewer"])
    refresh_token = client.cookies.get(REFRESH_COOKIE)

    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 204

    client.cookies.set(REFRESH_COOKIE, refresh_token, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_cookie_requests_that_change_state_need_csrf_header(
    client: httpx.AsyncClient, make_org
) -> None:
    org = make_org("technova")
    response = await login(client, org.users["org_admin"])
    csrf = response.json()["csrf_token"]

    without = await client.patch("/api/v1/organization", json={"name": "TechNova Ltd"})
    assert without.status_code == 403

    with_header = await client.patch(
        "/api/v1/organization", json={"name": "TechNova Ltd"}, headers={"X-CSRF-Token": csrf}
    )
    assert with_header.status_code == 200
    assert with_header.json()["name"] == "TechNova Ltd"


async def test_bearer_token_works_and_skips_csrf(client: httpx.AsyncClient, make_org) -> None:
    """API clients (no cookies) send `Authorization: Bearer`; CSRF doesn't apply to them."""
    org = make_org("technova")
    await login(client, org.users["org_admin"])
    token = client.cookies.get(ACCESS_COOKIE)
    client.cookies.clear()
    response = await client.patch(
        "/api/v1/organization",
        json={"name": "Renamed"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
