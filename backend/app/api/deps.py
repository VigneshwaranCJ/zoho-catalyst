"""FastAPI dependencies: DB session, current user, tenant scope, RBAC, CSRF."""

import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Permission, has_permission
from app.core.security import InvalidTokenError, decode_token
from app.db.session import get_sessionmaker, set_tenant
from app.models.user import User

ACCESS_COOKIE = "csp_access"
REFRESH_COOKIE = "csp_refresh"
CSRF_COOKIE = "csp_csrf"
CSRF_HEADER = "X-CSRF-Token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


async def get_db() -> AsyncIterator[AsyncSession]:
    """One session (and transaction) per request: commit on success, roll back on error."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


DbSession = Annotated[AsyncSession, Depends(get_db)]


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: str
    email: str
    display_name: str


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_principal(request: Request, session: DbSession) -> Principal:
    token: str | None = None
    via_cookie = False
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    elif cookie := request.cookies.get(ACCESS_COOKIE):
        token, via_cookie = cookie, True
    if not token:
        raise _unauthorized()

    try:
        claims = decode_token(token, "access")
    except InvalidTokenError as exc:
        raise _unauthorized("Session expired") from exc

    # CSRF: cookie-authenticated, state-changing requests must echo the CSRF cookie
    # in a header. A malicious site can make the browser *send* cookies, but it
    # cannot *read* them to copy into a header.
    if via_cookie and request.method not in _SAFE_METHODS:
        cookie_csrf = request.cookies.get(CSRF_COOKIE, "")
        header_csrf = request.headers.get(CSRF_HEADER, "")
        if not cookie_csrf or not secrets.compare_digest(cookie_csrf, header_csrf):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing or invalid")

    # Scope this request's transaction to the user's organization (RLS).
    await set_tenant(session, claims.organization_id)

    # Re-read the user every request so deactivation / role changes apply immediately.
    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise _unauthorized("Account disabled")

    return Principal(
        user_id=user.id,
        organization_id=user.organization_id,
        role=user.role,
        email=user.email,
        display_name=user.display_name,
    )


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def require(permission: Permission) -> Callable[[Principal], Awaitable[Principal]]:
    """Dependency factory: `Depends(require(Permission.MANAGE_ORG))`."""

    async def checker(principal: CurrentPrincipal) -> Principal:
        if not has_permission(principal.role, permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have permission to do this")
        return principal

    return checker
