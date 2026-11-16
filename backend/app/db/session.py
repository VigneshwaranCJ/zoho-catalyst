"""Database engine and sessions.

Multi-tenant isolation in plain words:
  * The app connects as a NON-owner role (`csp_app`). PostgreSQL Row-Level
    Security (RLS) policies on every tenant table only show rows where
    `organization_id = current_setting('app.current_org')`.
  * At the start of each transaction we call `set_tenant()`; the setting is
    transaction-local (`set_config(..., is_local => true)`), so it can never
    leak into another request that reuses the same pooled connection.
  * If no tenant is set, policies match nothing: the safe default is "see nothing".
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.app_database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=10,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def set_tenant(session: AsyncSession, organization_id: uuid.UUID | None) -> None:
    """Scope the current transaction to one organization for RLS."""
    await session.execute(
        text("SELECT set_config('app.current_org', :org, true)"),
        {"org": str(organization_id) if organization_id else ""},
    )


@asynccontextmanager
async def tenant_session(organization_id: uuid.UUID | None) -> AsyncIterator[AsyncSession]:
    """Open a session + transaction already scoped to a tenant. Commits on success."""
    async with get_sessionmaker()() as session, session.begin():
        await set_tenant(session, organization_id)
        yield session


async def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
        get_engine.cache_clear()
        get_sessionmaker.cache_clear()
