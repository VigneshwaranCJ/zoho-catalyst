"""Password hashing and JWT helpers.

* Passwords: Argon2id (memory-hard; the current OWASP recommendation).
* Access token: short-lived JWT (15 min) carried in an httpOnly cookie.
* Refresh token: longer-lived JWT whose `jti` is stored (hashed) in the DB so it
  can be rotated on every use and revoked on logout.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

_password_hasher = PasswordHash.recommended()  # Argon2id

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        # Still spend the hashing time so attackers can't tell "no such user" by timing.
        _password_hasher.hash(password)
        return False
    return _password_hasher.verify(password, password_hash)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True, slots=True)
class TokenClaims:
    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: str
    type: TokenType
    jti: str
    expires_at: datetime


def issue_token(
    *, user_id: uuid.UUID, organization_id: uuid.UUID, role: str, token_type: TokenType
) -> tuple[str, TokenClaims]:
    settings = get_settings()
    now = datetime.now(UTC)
    lifetime = (
        timedelta(minutes=settings.access_token_minutes)
        if token_type == "access"
        else timedelta(days=settings.refresh_token_days)
    )
    claims = TokenClaims(
        user_id=user_id,
        organization_id=organization_id,
        role=role,
        type=token_type,
        jti=secrets.token_urlsafe(16),
        expires_at=now + lifetime,
    )
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org": str(organization_id),
        "role": role,
        "typ": token_type,
        "jti": claims.jti,
        "iat": now,
        "exp": claims.expires_at,
    }
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), settings.jwt_algorithm)
    return token, claims


class InvalidTokenError(Exception):
    pass


def decode_token(token: str, expected_type: TokenType) -> TokenClaims:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],  # never accept "none" or other algorithms
            options={"require": ["exp", "sub", "org", "typ", "jti"]},
        )
        if payload["typ"] != expected_type:
            raise InvalidTokenError("wrong token type")
        return TokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            organization_id=uuid.UUID(payload["org"]),
            role=str(payload["role"]),
            type=expected_type,
            jti=str(payload["jti"]),
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc
