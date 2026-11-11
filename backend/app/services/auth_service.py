"""Authentication use cases: login, token refresh (rotation), logout."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    InvalidTokenError,
    TokenClaims,
    decode_token,
    issue_token,
    sha256_hex,
    verify_password,
)
from app.db.session import set_tenant
from app.models.user import RefreshToken, User
from app.services import audit


class AuthError(Exception):
    """Generic auth failure. Message is safe to show (never says *why* exactly)."""


class OrganizationRequiredError(AuthError):
    """Same email exists in several organizations; caller must pick one."""


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    access_claims: TokenClaims
    refresh_claims: TokenClaims


async def _issue_pair(
    session: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID, role: str
) -> IssuedTokens:
    access, access_claims = issue_token(
        user_id=user_id, organization_id=org_id, role=role, token_type="access"
    )
    refresh, refresh_claims = issue_token(
        user_id=user_id, organization_id=org_id, role=role, token_type="refresh"
    )
    session.add(
        RefreshToken(
            organization_id=org_id,
            user_id=user_id,
            jti_hash=sha256_hex(refresh_claims.jti),
            expires_at=refresh_claims.expires_at,
        )
    )
    return IssuedTokens(access, refresh, access_claims, refresh_claims)


async def login(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    organization_slug: str | None,
    ip: str | None,
    user_agent: str | None,
) -> IssuedTokens:
    rows = (
        (
            await session.execute(
                text("SELECT * FROM auth_find_login_candidates(:email)"), {"email": email}
            )
        )
        .mappings()
        .all()
    )
    if organization_slug:
        rows = [r for r in rows if r["organization_slug"] == organization_slug]

    if len(rows) > 1:
        raise OrganizationRequiredError("Please choose an organization.")

    candidate = rows[0] if rows else None
    password_ok = verify_password(password, candidate["password_hash"] if candidate else None)
    if (
        candidate is None
        or not password_ok
        or not candidate["is_active"]
        or candidate["organization_status"] != "active"
    ):
        if candidate is not None:
            await set_tenant(session, candidate["organization_id"])
            await audit.record(
                session,
                action="auth.login_failed",
                organization_id=candidate["organization_id"],
                actor_type="user",
                actor_id=str(candidate["user_id"]),
                ip=ip,
                user_agent=user_agent,
            )
        raise AuthError("Invalid email or password.")

    org_id: uuid.UUID = candidate["organization_id"]
    user_id: uuid.UUID = candidate["user_id"]
    await set_tenant(session, org_id)
    await session.execute(
        update(User).where(User.id == user_id).values(last_login_at=datetime.now(UTC))
    )
    tokens = await _issue_pair(session, user_id, org_id, candidate["role"])
    await audit.record(
        session,
        action="auth.login",
        organization_id=org_id,
        actor_type="user",
        actor_id=str(user_id),
        ip=ip,
        user_agent=user_agent,
    )
    return tokens


async def refresh(session: AsyncSession, *, refresh_token: str) -> IssuedTokens:
    """Rotate: the old refresh token is revoked and a new pair is issued.

    If a revoked token is presented again (possible theft), all of that user's
    refresh tokens are revoked.
    """
    try:
        claims = decode_token(refresh_token, "refresh")
    except InvalidTokenError as exc:
        raise AuthError("Session expired. Please sign in again.") from exc

    await set_tenant(session, claims.organization_id)
    stored = await session.scalar(
        select(RefreshToken).where(RefreshToken.jti_hash == sha256_hex(claims.jti))
    )
    now = datetime.now(UTC)
    if stored is None or stored.expires_at <= now:
        raise AuthError("Session expired. Please sign in again.")
    if stored.revoked_at is not None:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == stored.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await audit.record(
            session,
            action="auth.refresh_reuse_detected",
            organization_id=claims.organization_id,
            actor_type="user",
            actor_id=str(claims.user_id),
        )
        raise AuthError("Session expired. Please sign in again.")

    user = await session.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise AuthError("Session expired. Please sign in again.")

    stored.revoked_at = now
    return await _issue_pair(session, user.id, user.organization_id, user.role)


async def logout(session: AsyncSession, *, refresh_token: str | None) -> None:
    if not refresh_token:
        return
    try:
        claims = decode_token(refresh_token, "refresh")
    except InvalidTokenError:
        return
    await set_tenant(session, claims.organization_id)
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.jti_hash == sha256_hex(claims.jti), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await audit.record(
        session,
        action="auth.logout",
        organization_id=claims.organization_id,
        actor_type="user",
        actor_id=str(claims.user_id),
    )
