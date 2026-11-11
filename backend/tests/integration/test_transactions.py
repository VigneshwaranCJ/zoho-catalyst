"""The request's DB transaction must be committed BEFORE the response is sent.

Otherwise a commit failure (constraint violation, lost connection) would reach
the client as "200 OK" while the data silently disappears.
"""

import uuid

import httpx
from fastapi import Depends

from app.api.deps import DbSession, Principal, get_current_principal
from app.main import create_app
from app.models.user import User
from tests.conftest import login


async def test_commit_failure_is_reported_to_client(make_org) -> None:
    org = make_org("technova")
    app = create_app()

    @app.post("/test-only/duplicate-user")
    async def add_duplicate(
        session: DbSession, principal: Principal = Depends(get_current_principal)
    ) -> dict[str, str]:
        # Same (organization_id, email) as an existing user. No flush here, so
        # the unique-constraint violation only happens at COMMIT time.
        session.add(
            User(
                id=uuid.uuid4(),
                organization_id=principal.organization_id,
                email=principal.email,
                display_name="dup",
                role="viewer",
            )
        )
        return {"status": "created"}

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await login(client, org.users["org_admin"])
        token = client.cookies.get("csp_access")
        response = await client.post(
            "/test-only/duplicate-user", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 500, "a failed commit must not be reported as success"
