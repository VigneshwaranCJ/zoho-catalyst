"""Role-based access control: which role may do what.

Mirrors the permission table in docs/SECURITY_DESIGN.md §4. Endpoints declare
the *permission* they need (never a role name), so changing who can do what
is a one-line edit here.
"""

from enum import StrEnum

ROLES = ("org_admin", "editor", "agent", "viewer")


class Permission(StrEnum):
    MANAGE_ORG = "org:manage"  # users, API keys, integrations
    EDIT_KNOWLEDGE = "knowledge:edit"  # upload sources, edit drafts
    PUBLISH_KNOWLEDGE = "knowledge:publish"  # approve / reject / delete
    VIEW_CONVERSATIONS = "conversations:view"
    HANDLE_TICKETS = "tickets:handle"  # reply as human, change status
    APPROVE_AGENT_ACTIONS = "agent:approve"  # human-in-the-loop approvals
    VIEW_ANALYTICS = "analytics:view"


_VIEW = {Permission.VIEW_CONVERSATIONS, Permission.VIEW_ANALYTICS}

ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "org_admin": frozenset(Permission),
    "editor": frozenset(_VIEW | {Permission.EDIT_KNOWLEDGE, Permission.PUBLISH_KNOWLEDGE}),
    "agent": frozenset(_VIEW | {Permission.HANDLE_TICKETS, Permission.APPROVE_AGENT_ACTIONS}),
    "viewer": frozenset(_VIEW),
}


def has_permission(role: str, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())
