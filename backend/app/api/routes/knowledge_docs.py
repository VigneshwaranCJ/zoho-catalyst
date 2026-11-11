"""OKF knowledge endpoints: review drafts, publish, browse, edit, search."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select

from app.api.deps import DbSession, require
from app.core.principal import Principal
from app.core.rbac import Permission
from app.knowledge.okf import document as okfdoc
from app.knowledge.okf.profile import (
    OKF_VERSION,
    PROFILE_ID,
    ActorEvent,
    profile_json_schema,
    trust_tier,
)
from app.models.knowledge import KnowledgeSource
from app.models.knowledge_docs import KnowledgeDocument, KnowledgeVersion
from app.schemas.knowledge_docs import (
    ApproveRequest,
    ApproveResponse,
    DocumentDetail,
    DocumentListItem,
    DraftListItem,
    EditDocumentRequest,
    ProfileSchemaResponse,
    RejectRequest,
    SearchHitOut,
    SearchResponse,
    ValidationSummary,
    VersionDetail,
    VersionHistoryItem,
)
from app.services import knowledge_publish as publish
from app.services.knowledge_publish import (
    INJECTION_WARNING_PREFIX,
    PublishError,
    VersionNotFoundError,
)
from app.services.knowledge_search import search_sections

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge documents"])

Viewer = Annotated[Principal, Depends(require(Permission.VIEW_KNOWLEDGE))]
Editor = Annotated[Principal, Depends(require(Permission.EDIT_KNOWLEDGE))]
Publisher = Annotated[Principal, Depends(require(Permission.PUBLISH_KNOWLEDGE))]


def _has_injection(validation: dict[str, Any]) -> bool:
    warnings: list[Any] = validation.get("warnings") or []
    return any(
        isinstance(w, dict) and str(w.get("message", "")).startswith(INJECTION_WARNING_PREFIX)
        for w in warnings
    )


@router.get("/reviews", response_model=list[DraftListItem])
async def list_drafts(_: Viewer, session: DbSession) -> list[DraftListItem]:
    """Drafts waiting for human review, newest first."""
    rows = await session.execute(
        select(KnowledgeVersion, KnowledgeDocument, KnowledgeSource.original_name)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeVersion.document_id)
        .outerjoin(KnowledgeSource, KnowledgeSource.id == KnowledgeVersion.source_id)
        .where(KnowledgeVersion.review_status == "pending")
        .order_by(KnowledgeVersion.created_at.desc(), KnowledgeDocument.path)
        .limit(500)
    )
    return [
        DraftListItem(
            version_id=v.id,
            document_id=d.id,
            path=d.path,
            title=d.title,
            doc_type=d.doc_type,
            audience=d.audience,
            version_no=v.version_no,
            is_update=v.base_version_id is not None,
            source_id=v.source_id,
            source_name=source_name,
            job_id=v.job_id,
            created_at=v.created_at,
            error_count=len(v.validation.get("errors", [])),
            warning_count=len(v.validation.get("warnings", [])),
            has_injection_warnings=_has_injection(v.validation),
        )
        for v, d, source_name in rows
    ]


@router.get("/versions/{version_id}", response_model=VersionDetail)
async def get_version(version_id: uuid.UUID, _: Viewer, session: DbSession) -> VersionDetail:
    try:
        view = await publish.get_version(session, version_id)
    except VersionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found") from exc
    v, d = view.version, view.document
    return VersionDetail(
        version_id=v.id,
        document_id=d.id,
        path=d.path,
        title=d.title,
        doc_type=d.doc_type,
        version_no=v.version_no,
        review_status=v.review_status,
        content=v.content,
        validation=ValidationSummary(
            ok=bool(v.validation.get("ok", True)),
            errors=v.validation.get("errors", []),
            warnings=v.validation.get("warnings", []),
        ),
        diff=view.diff,
        has_injection_warnings=view.has_injection_warnings,
        generated_by=v.generated_by,
        created_at=v.created_at,
        reviewed_at=v.reviewed_at,
        review_note=v.review_note,
        git_commit_sha=v.git_commit_sha,
    )


@router.post("/versions/approve", response_model=ApproveResponse)
async def approve_versions(
    body: ApproveRequest, principal: Publisher, session: DbSession
) -> ApproveResponse:
    """Publish one or more drafts in a single Git commit."""
    try:
        sha = await publish.approve(
            session,
            principal,
            body.version_ids,
            note=body.note,
            acknowledge_warnings=body.acknowledge_warnings,
        )
    except VersionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found") from exc
    except PublishError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return ApproveResponse(commit_sha=sha, approved=len(set(body.version_ids)))


@router.post("/versions/{version_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_version(
    version_id: uuid.UUID, body: RejectRequest, principal: Publisher, session: DbSession
) -> Response:
    try:
        await publish.reject(session, principal, version_id, note=body.note)
    except VersionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found") from exc
    except PublishError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _pending_counts(session: DbSession) -> dict[uuid.UUID, int]:
    rows = await session.execute(
        select(KnowledgeVersion.document_id, func.count())
        .where(KnowledgeVersion.review_status == "pending")
        .group_by(KnowledgeVersion.document_id)
    )
    return {doc_id: int(count) for doc_id, count in rows}


async def _list_item(session: DbSession, d: KnowledgeDocument, pending: int) -> DocumentListItem:
    current_no = (
        await session.scalar(
            select(KnowledgeVersion.version_no).where(KnowledgeVersion.id == d.current_version_id)
        )
        if d.current_version_id
        else None
    )
    return DocumentListItem(
        id=d.id,
        path=d.path,
        title=d.title,
        doc_type=d.doc_type,
        description=d.description,
        audience=d.audience,
        status=d.status,
        tags=list(d.tags),
        current_version_no=current_no,
        pending_drafts=pending,
        updated_at=d.updated_at,
    )


@router.get("/documents", response_model=list[DocumentListItem])
async def list_documents(_: Viewer, session: DbSession) -> list[DocumentListItem]:
    docs = await session.scalars(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.status != "archived")
        .order_by(KnowledgeDocument.path)
    )
    pending = await _pending_counts(session)
    return [await _list_item(session, d, pending.get(d.id, 0)) for d in docs]


@router.get("/documents/{document_id}", response_model=DocumentDetail)
async def get_document(document_id: uuid.UUID, _: Viewer, session: DbSession) -> DocumentDetail:
    d = await session.get(KnowledgeDocument, document_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    pending = await _pending_counts(session)
    base = await _list_item(session, d, pending.get(d.id, 0))
    current = (
        await session.get(KnowledgeVersion, d.current_version_id) if d.current_version_id else None
    )
    tier = None
    if current:
        raw = (okfdoc.parse(current.content).frontmatter or {}).get("verified") or []
        events = [ActorEvent.model_validate(e) for e in ([raw] if isinstance(raw, dict) else raw)]
        tier = trust_tier(events)
    versions = await session.scalars(
        select(KnowledgeVersion)
        .where(KnowledgeVersion.document_id == d.id)
        .order_by(KnowledgeVersion.version_no.desc())
    )
    return DocumentDetail(
        **base.model_dump(),
        content=current.content if current else None,
        trust_tier=tier,
        versions=[
            VersionHistoryItem(
                version_id=v.id,
                version_no=v.version_no,
                review_status=v.review_status,
                generated_by=v.generated_by,
                created_at=v.created_at,
                reviewed_at=v.reviewed_at,
                git_commit_sha=v.git_commit_sha,
            )
            for v in versions
        ],
    )


@router.put(
    "/documents/{document_id}", response_model=VersionDetail, status_code=status.HTTP_201_CREATED
)
async def edit_document(
    document_id: uuid.UUID, body: EditDocumentRequest, principal: Editor, session: DbSession
) -> VersionDetail:
    """Save an edited copy as a new DRAFT; it is published only after review."""
    try:
        version = await publish.edit_document(session, principal, document_id, body.content)
    except VersionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found") from exc
    except PublishError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return await get_version(version.id, principal, session)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_document(
    document_id: uuid.UUID, principal: Publisher, session: DbSession
) -> Response:
    """Remove a document from the published knowledge (Git keeps its history)."""
    try:
        await publish.archive_document(session, principal, document_id)
    except VersionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/search", response_model=SearchResponse)
async def search(
    _: Viewer,
    session: DbSession,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    include_internal: bool = False,
) -> SearchResponse:
    hits = await search_sections(session, q, limit=limit, include_internal=include_internal)
    return SearchResponse(
        query=q,
        hits=[
            SearchHitOut(
                section_id=h.section_id,
                document_id=h.document_id,
                path=h.path,
                doc_title=h.doc_title,
                doc_type=h.doc_type,
                heading=h.heading,
                anchor=h.anchor,
                heading_path=h.heading_path,
                snippet=h.body[:300] + ("..." if len(h.body) > 300 else ""),
                source_pages=h.source_pages,
                score=h.score,
            )
            for h in hits
        ],
    )


@router.get("/profile-schema", response_model=ProfileSchemaResponse)
async def profile_schema(_: Viewer) -> ProfileSchemaResponse:
    """The JSON Schema of our OKF profile (what generated frontmatter must satisfy)."""
    return ProfileSchemaResponse(
        okf_version=OKF_VERSION, profile=PROFILE_ID, json_schema=profile_json_schema()
    )
