"""Append-only audit logging."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def record(
    session: AsyncSession,
    *,
    action: str,
    organization_id: uuid.UUID | None,
    actor_type: str,
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditLog(
            action=action,
            organization_id=organization_id,
            actor_type=actor_type,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            ip=ip,
            user_agent=(user_agent or "")[:500] or None,
            details=details or {},
        )
    )
