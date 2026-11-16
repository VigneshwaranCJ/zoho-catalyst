"""Dashboard authentication endpoints.

Tokens travel in httpOnly cookies (JavaScript can't read them, which blocks
token theft via XSS). A separate, readable CSRF cookie + header protects
state-changing requests.
"""

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    CurrentPrincipal,
    DbSession,
)
from app.core import rate_limit
from app.core.config import get_settings
from app.core.principal import Principal
from app.core.rbac import ROLE_PERMISSIONS
from app.core.security import new_csrf_token
from app.schemas.auth import AuthResponse, LoginRequest, MeResponse
from app.services import auth_service
from app.services.auth_service import IssuedTokens

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

LOGIN_LIMIT = 5
LOGIN_WINDOW_SECONDS = 15 * 60
REFRESH_PATH = "/api/v1/auth"


def _me(p: Principal) -> MeResponse:
    return MeResponse(
        user_id=p.user_id,
        organization_id=p.organization_id,
        email=p.email,
        display_name=p.display_name,
        role=p.role,
        permissions=sorted(ROLE_PERMISSIONS.get(p.role, frozenset())),
    )


def _set_auth_cookies(response: Response, tokens: IssuedTokens) -> str:
    settings = get_settings()
    csrf = new_csrf_token()
    common = {"secure": settings.cookie_secure, "samesite": "lax"}
    response.set_cookie(
        ACCESS_COOKIE,
        tokens.access_token,
        httponly=True,
        path="/",
        max_age=settings.access_token_minutes * 60,
        **common,  # type: ignore[arg-type]
    )
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        httponly=True,
        path=REFRESH_PATH,
        max_age=settings.refresh_token_days * 86400,
        **common,  # type: ignore[arg-type]
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        httponly=False,
        path="/",
        max_age=settings.refresh_token_days * 86400,
        **common,  # type: ignore[arg-type]
    )
    return csrf


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH)
    response.delete_cookie(CSRF_COOKIE, path="/")


def _auth_response(tokens: IssuedTokens, csrf: str, p: Principal) -> AuthResponse:
    return AuthResponse(
        user=_me(p),
        csrf_token=csrf,
        access_token_expires_at=tokens.access_claims.expires_at.isoformat(),
    )


async def _principal_for(session: DbSession, tokens: IssuedTokens) -> Principal:
    from app.models.user import User  # local import keeps module import graph simple

    user = await session.get(User, tokens.access_claims.user_id)
    assert user is not None
    return Principal(user.id, user.organization_id, user.role, user.email, user.display_name)


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest, request: Request, response: Response, session: DbSession
) -> AuthResponse:
    ip = request.client.host if request.client else "unknown"
    limiter_key = f"rl:login:{body.email.lower()}:{ip}"
    if not await rate_limit.hit(
        limiter_key, limit=LOGIN_LIMIT, window_seconds=LOGIN_WINDOW_SECONDS
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts. Try again in 15 minutes."
        )
    try:
        tokens = await auth_service.login(
            session,
            email=body.email,
            password=body.password,
            organization_slug=body.organization_slug,
            ip=ip,
            user_agent=request.headers.get("user-agent"),
        )
    except auth_service.OrganizationRequiredError as exc:
        # Only reached after the password was verified, so listing the
        # organizations reveals nothing to someone without the password.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": str(exc), "organizations": exc.organizations},
        ) from exc
    except auth_service.AuthError as exc:
        await session.commit()  # keep the failed-login audit record
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    await rate_limit.reset(limiter_key)
    csrf = _set_auth_cookies(response, tokens)
    return _auth_response(tokens, csrf, await _principal_for(session, tokens))


@router.post(
    "/refresh",
    response_model=AuthResponse,
    responses={401: {"description": "Session ended"}, 409: {"description": "Concurrent refresh"}},
)
async def refresh(
    request: Request, response: Response, session: DbSession
) -> AuthResponse | JSONResponse:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        tokens = await auth_service.refresh(session, refresh_token=token)
    except auth_service.RefreshRaceError:
        # Another tab refreshed a moment ago and its response carries the new
        # cookies. Keep them: the caller should simply retry its request.
        return JSONResponse({"detail": "Session was just refreshed. Retry."}, status_code=409)
    except auth_service.AuthError as exc:
        await session.commit()  # persist reuse-detection revocations
        # Return (not raise) so the cookie deletions are part of THIS response;
        # cookies set on the injected `response` are dropped when raising.
        failed = JSONResponse({"detail": str(exc)}, status_code=status.HTTP_401_UNAUTHORIZED)
        _clear_auth_cookies(failed)
        return failed
    csrf = _set_auth_cookies(response, tokens)
    return _auth_response(tokens, csrf, await _principal_for(session, tokens))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, session: DbSession) -> Response:
    await auth_service.logout(session, refresh_token=request.cookies.get(REFRESH_COOKIE))
    response.status_code = status.HTTP_204_NO_CONTENT
    _clear_auth_cookies(response)
    return response


@router.get("/me", response_model=MeResponse)
async def me(principal: CurrentPrincipal) -> MeResponse:
    return _me(principal)
