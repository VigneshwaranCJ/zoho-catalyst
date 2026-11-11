"""Shared test fixtures.

Tests run against a REAL PostgreSQL (the `csp_test` database created by the
Docker init script) because the things we most need to prove — Row-Level
Security, constraints, the login function — only exist in Postgres.

Prerequisite:  docker compose up -d postgres valkey
"""

import os
import tempfile
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

# ---- Point settings at the test database BEFORE importing the app. ----
os.environ["APP_ENV"] = "test"
os.environ["POSTGRES_DB"] = os.environ.get("TEST_POSTGRES_DB", "csp_test")
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15")
os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)
# Uploaded files go to a throwaway folder, never the developer's real storage.
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="csp-test-storage-")

import httpx
import pytest
import redis as redis_sync
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.main import create_app
from app.models.organization import Organization
from app.models.user import User
from app.utils.event_loop import loop_factory

TEST_PASSWORD = "Correct-Horse-Battery-9"


def pytest_asyncio_loop_factories(config: object, item: object) -> dict[str, object]:
    # psycopg async needs a selector loop on Windows (see app/utils/event_loop.py).
    return {"selector_loop": loop_factory}


@pytest.fixture(scope="session")
def owner_engine() -> Iterator[object]:
    engine = create_engine(get_settings().owner_database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_db(owner_engine: object) -> None:
    """Fresh schema for the test run: downgrade to nothing, upgrade to head."""
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option(
        "script_location", os.path.join(os.path.dirname(__file__), "..", "migrations")
    )
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def clean_state(owner_engine: object) -> None:
    """Every test starts with empty tables and an empty rate-limit store.

    Deliberately synchronous: it must not depend on any event loop, because
    sync and async tests run on different loops.
    """
    with Session(owner_engine) as s, s.begin():  # type: ignore[call-overload]
        s.execute(text("TRUNCATE organizations, audit_logs RESTART IDENTITY CASCADE"))
    with redis_sync.from_url(get_settings().redis_url) as r:
        r.flushdb()


@dataclass
class SeededUser:
    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    role: str
    password: str = TEST_PASSWORD


@dataclass
class SeededOrg:
    id: uuid.UUID
    slug: str
    users: dict[str, SeededUser]


@pytest.fixture
def make_org(owner_engine: object):  # type: ignore[no-untyped-def]
    """Factory: create an org with one user per role (as the owner role, bypassing RLS)."""

    def _make(
        slug: str, roles: tuple[str, ...] = ("org_admin", "editor", "agent", "viewer")
    ) -> SeededOrg:
        with Session(owner_engine) as s, s.begin():  # type: ignore[call-overload]
            org = Organization(slug=slug, name=slug.title())
            s.add(org)
            s.flush()
            users: dict[str, SeededUser] = {}
            for role in roles:
                email = f"{role}@{slug}.example"
                user = User(
                    organization_id=org.id,
                    email=email,
                    display_name=role,
                    role=role,
                    password_hash=hash_password(TEST_PASSWORD),
                )
                s.add(user)
                s.flush()
                users[role] = SeededUser(user.id, org.id, email, role)
            return SeededOrg(org.id, slug, users)

    return _make


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    transport = httpx.ASGITransport(app=app, client=("203.0.113.10", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def login(client: httpx.AsyncClient, user: SeededUser) -> httpx.Response:
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": user.password}
    )
    assert response.status_code == 200, response.text
    return response
