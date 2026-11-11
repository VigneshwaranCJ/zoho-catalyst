"""Import every model here so Alembic autogenerate can see all tables."""

from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.knowledge import IngestionJob, KnowledgeSource
from app.models.knowledge_docs import (
    KnowledgeDocument,
    KnowledgeLink,
    KnowledgeSection,
    KnowledgeVersion,
)
from app.models.organization import Organization
from app.models.user import RefreshToken, User

__all__ = [
    "ApiKey",
    "AuditLog",
    "IngestionJob",
    "KnowledgeDocument",
    "KnowledgeLink",
    "KnowledgeSection",
    "KnowledgeSource",
    "KnowledgeVersion",
    "Organization",
    "RefreshToken",
    "User",
]
