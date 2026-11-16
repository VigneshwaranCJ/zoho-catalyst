import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ValidationSummary(BaseModel):
    ok: bool
    errors: list[dict[str, str]]
    warnings: list[dict[str, str]]


class DraftListItem(BaseModel):
    version_id: uuid.UUID
    document_id: uuid.UUID
    path: str
    title: str
    doc_type: str
    audience: str
    version_no: int
    is_update: bool
    source_id: uuid.UUID | None
    source_name: str | None
    job_id: uuid.UUID | None
    created_at: datetime
    error_count: int
    warning_count: int
    has_injection_warnings: bool


class VersionDetail(BaseModel):
    version_id: uuid.UUID
    document_id: uuid.UUID
    path: str
    title: str
    doc_type: str
    version_no: int
    review_status: str
    content: str
    validation: ValidationSummary
    diff: str
    has_injection_warnings: bool
    generated_by: str
    created_at: datetime
    reviewed_at: datetime | None
    review_note: str | None
    git_commit_sha: str | None


class ApproveRequest(BaseModel):
    version_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=2000)
    acknowledge_warnings: bool = False


class ApproveResponse(BaseModel):
    commit_sha: str
    approved: int


class RejectRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class DocumentListItem(BaseModel):
    id: uuid.UUID
    path: str
    title: str
    doc_type: str
    description: str | None
    audience: str
    status: str
    tags: list[str]
    current_version_no: int | None
    pending_drafts: int
    updated_at: datetime


class VersionHistoryItem(BaseModel):
    version_id: uuid.UUID
    version_no: int
    review_status: str
    generated_by: str
    created_at: datetime
    reviewed_at: datetime | None
    git_commit_sha: str | None


class DocumentDetail(DocumentListItem):
    content: str | None
    trust_tier: str | None
    versions: list[VersionHistoryItem]


class EditDocumentRequest(BaseModel):
    content: str = Field(min_length=10, max_length=500_000)


class SearchHitOut(BaseModel):
    section_id: uuid.UUID
    document_id: uuid.UUID
    path: str
    doc_title: str
    doc_type: str
    heading: str
    anchor: str
    heading_path: list[str]
    snippet: str
    source_pages: list[int]
    score: float


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHitOut]


class ProfileSchemaResponse(BaseModel):
    okf_version: str
    profile: str
    json_schema: dict[str, Any]
