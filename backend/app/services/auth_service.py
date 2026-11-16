"""Authentication use cases: login, token refresh (rotation), logout."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import RowMapping, select, text, update
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
from app.models.organization import Organization
from app.models.user import RefreshToken, User
from app.services import audit

# A refresh token presented again within this window after it was rotated is
# treated as a benign race (two browser tabs refreshing at the same moment),
# not as theft. Outside the window, reuse revokes every session of the user.
REUSE_GRACE = timedelta(seconds=30)

_SESSION_EXPIRED = "Session expired. Please sign in again."


class AuthError(Exception):
    """Generic auth failure. Message is safe to show (never says *why* exactly)."""


class OrganizationRequiredError(AuthError):
    """The password matched accounts in several organizations; caller must pick one."""

    def __init__(self, organizations: list[str]) -> None:
        super().__init__("Your account exists in several organizations. Please choose one.")
        self.organizations = organizations


class RefreshRaceError(AuthError):
    """This token was rotated a moment ago by a concurrent request.

    The caller must NOT clear the session cookies: the concurrent request has
    just set fresh ones.
    """


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


async def _audit_in_tenant(session: AsyncSession, org_id: uuid.UUID, **kwargs: Any) -> None:
    """Write an audit row for a specific tenant.

    Flushed immediately: RLS checks the row against the tenant that is set *at
    insert time*, and we may switch tenants several times in one login attempt.
    """
    await set_tenant(session, org_id)
    await audit.record(session, organization_id=org_id, **kwargs)
    await session.flush()


def _can_log_in(candidate: RowMapping) -> bool:
    return bool(candidate["is_active"]) and candidate["organization_status"] == "active"


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

    # Verify the password against every candidate BEFORE revealing anything,
    # so "this email exists in several organizations" is never leaked to
    # someone who doesn't know the password.
    if not rows:
        verify_password(password, None)  # same work as a real check (timing)
        raise AuthError("Invalid email or password.")
    matching = [r for r in rows if verify_password(password, r["password_hash"])]
    usable = [r for r in matching if _can_log_in(r)]

    if not usable:
        for r in rows:
            await _audit_in_tenant(
                session, r["organization_id"], action="auth.login_failed",
                actor_type="user", actor_id=str(r["user_id"]), ip=ip, user_agent=user_agent,
            )  # fmt: skip
        raise AuthError("Invalid email or password.")
    if len(usable) > 1:
        raise OrganizationRequiredError(sorted(r["organization_slug"] for r in usable))

    candidate = usable[0]
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

    * The rotation is ATOMIC: a single `UPDATE ... WHERE revoked_at IS NULL`
      claims the token, so two concurrent requests can never both succeed.
    * Reuse shortly after rotation = concurrent tabs -> RefreshRaceError.
    * Reuse later = probable theft -> every refresh token of the user is revoked.
    """
    try:
        claims = decode_token(refresh_token, "refresh")
    except InvalidTokenError as exc:
        raise AuthError(_SESSION_EXPIRED) from exc

    await set_tenant(session, claims.organization_id)
    jti_hash = sha256_hex(claims.jti)
    now = datetime.now(UTC)

    claimed_user_id = await session.scalar(
        update(RefreshToken)
        .where(
            RefreshToken.jti_hash == jti_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .values(revoked_at=now, rotated_at=now)
        .returning(RefreshToken.user_id)
    )

    if claimed_user_id is None:
        stored = await session.scalar(select(RefreshToken).where(RefreshToken.jti_hash == jti_hash))
        if stored is None or stored.revoked_at is None or stored.expires_at <= now:
            raise AuthError(_SESSION_EXPIRED)
        # Grace only for tokens that were *rotated* moments ago (another tab).
        # Tokens revoked by logout or theft detection never get it.
        if stored.rotated_at is not None and now - stored.rotated_at <= REUSE_GRACE:
            raise RefreshRaceError(_SESSION_EXPIRED)
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
        raise AuthError(_SESSION_EXPIRED)

    user = await session.get(User, claimed_user_id)
    org = await session.get(Organization, claims.organization_id)
    if user is None or not user.is_active or org is None or org.status != "active":
        raise AuthError(_SESSION_EXPIRED)
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
