"""Liveness and readiness probes.

* /health: "is the process alive?" (no dependencies; used by Docker healthcheck)
* /ready:  "can it serve traffic?" (checks PostgreSQL and Valkey)
"""

from typing import Any

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.rate_limit import get_redis
from app.db.session import get_engine

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(response: Response) -> dict[str, Any]:
    checks: dict[str, str] = {}
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {type(exc).__name__}"
    try:
        await get_redis().ping()
        checks["valkey"] = "ok"
    except Exception as exc:
        checks["valkey"] = f"error: {type(exc).__name__}"

    healthy = all(v == "ok" for v in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if healthy else "degraded", "checks": checks}
