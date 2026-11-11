"""Organization & user administration (minimal in Phase 2; grows in Phase 8)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentPrincipal, DbSession, Principal, require
from app.core.rbac import Permission
from app.models.organization import Organization
from app.models.user import User
from app.schemas.users import OrganizationOut, OrganizationUpdate, UserOut
from app.services import audit

router = APIRouter(prefix="/api/v1", tags=["organization"])


@router.get("/organization", response_model=OrganizationOut)
async def get_organization(principal: CurrentPrincipal, session: DbSession) -> Organization:
    org = await session.get(Organization, principal.organization_id)
    if org is None:  # would indicate an RLS/config bug
        raise HTTPException(404, "Organization not found")
    return org


@router.patch("/organization", response_model=OrganizationOut)
async def update_organization(
    body: OrganizationUpdate,
    principal: Annotated[Principal, Depends(require(Permission.MANAGE_ORG))],
    session: DbSession,
) -> Organization:
    org = await session.get(Organization, principal.organization_id)
    if org is None:
        raise HTTPException(404, "Organization not found")
    old_name, org.name = org.name, body.name
    await audit.record(
        session,
        action="organization.update",
        organization_id=org.id,
        actor_type="user",
        actor_id=str(principal.user_id),
        target_type="organization",
        target_id=str(org.id),
        details={"name": {"from": old_name, "to": body.name}},
    )
    return org


@router.get("/users", response_model=list[UserOut])
async def list_users(
    principal: Annotated[Principal, Depends(require(Permission.MANAGE_ORG))],
    session: DbSession,
) -> list[User]:
    # No explicit org filter needed for correctness (RLS enforces it), but we add
    # one anyway: defence in depth, and it keeps the query plan index-friendly.
    result = await session.scalars(
        select(User).where(User.organization_id == principal.organization_id).order_by(User.email)
    )
    return list(result)
