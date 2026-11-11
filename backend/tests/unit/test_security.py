import uuid

import jwt
import pytest

from app.core.config import get_settings
from app.core.rbac import ROLE_PERMISSIONS, Permission, has_permission
from app.core.security import (
    InvalidTokenError,
    decode_token,
    hash_password,
    issue_token,
    verify_password,
)


def _token(token_type: str = "access") -> str:
    token, _ = issue_token(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role="viewer",
        token_type=token_type,  # type: ignore[arg-type]
    )
    return token


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("s3cret-Password!")
    assert hashed.startswith("$argon2id$")
    assert verify_password("s3cret-Password!", hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password("anything", None)


def test_access_token_roundtrip() -> None:
    claims = decode_token(_token("access"), "access")
    assert claims.role == "viewer"


def test_refresh_token_is_not_accepted_as_access_token() -> None:
    with pytest.raises(InvalidTokenError):
        decode_token(_token("refresh"), "access")


def test_tampered_token_is_rejected() -> None:
    token = _token()
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.{signature[:-2]}AA"
    with pytest.raises(InvalidTokenError):
        decode_token(tampered, "access")


def test_alg_none_token_is_rejected() -> None:
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "org": str(uuid.uuid4()),
            "typ": "access",
            "jti": "x",
            "role": "org_admin",
            "exp": 9999999999,
        },
        key=None,
        algorithm="none",
    )
    with pytest.raises(InvalidTokenError):
        decode_token(forged, "access")


def test_token_signed_with_other_secret_is_rejected() -> None:
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "org": str(uuid.uuid4()),
            "typ": "access",
            "jti": "x",
            "role": "org_admin",
            "exp": 9999999999,
        },
        key="attacker-secret-" + "y" * 40,
        algorithm=get_settings().jwt_algorithm,
    )
    with pytest.raises(InvalidTokenError):
        decode_token(forged, "access")


def test_rbac_matrix_matches_security_design() -> None:
    assert ROLE_PERMISSIONS["org_admin"] == frozenset(Permission)
    assert has_permission("editor", Permission.PUBLISH_KNOWLEDGE)
    assert has_permission("viewer", Permission.VIEW_KNOWLEDGE)
    assert not has_permission("viewer", Permission.EDIT_KNOWLEDGE)
    assert not has_permission("editor", Permission.MANAGE_ORG)
    assert has_permission("agent", Permission.APPROVE_AGENT_ACTIONS)
    assert not has_permission("agent", Permission.EDIT_KNOWLEDGE)
    assert not has_permission("viewer", Permission.HANDLE_TICKETS)
    assert not has_permission("unknown-role", Permission.VIEW_ANALYTICS)
