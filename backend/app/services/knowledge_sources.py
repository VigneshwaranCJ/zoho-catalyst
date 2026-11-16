"""Knowledge source use cases (API side): upload, add URL, list, retry, delete.

The heavy lifting (fetching URLs, Docling extraction) happens later in the
worker; these functions only validate input, store the original and queue a job.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.principal import Principal
from app.db.base import new_id
from app.ingestion import validation
from app.ingestion.safe_fetch import SafeFetcher, parse_url
from app.models.knowledge import ACTIVE_JOB_STATUSES, IngestionJob, KnowledgeSource
from app.services import audit
from app.storage.files import get_storage


class SourceNotFoundError(LookupError):
    pass


class SourceConflictError(ValueError):
    """Operation not possible in the current state. Message is user-safe."""


@dataclass(frozen=True, slots=True)
class UploadOutcome:
    status: Literal["created", "duplicate"]
    source: KnowledgeSource
    job: IngestionJob | None


async def _live_source_by_sha(session: AsyncSession, sha256: str) -> KnowledgeSource | None:
    return await session.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.sha256 == sha256, KnowledgeSource.deleted_at.is_(None)
        )
    )


async def upload_file(
    session: AsyncSession, principal: Principal, *, filename: str | None, data: bytes
) -> UploadOutcome:
    """Validate, store and queue one uploaded file. Raises UnsupportedFileError."""
    detected = validation.detect(data, filename, max_bytes=get_settings().max_upload_bytes)
    sha256 = hashlib.sha256(data).hexdigest()

    existing = await _live_source_by_sha(session, sha256)
    if existing is not None:
        return UploadOutcome("duplicate", existing, None)

    source_id = new_id()
    storage = get_storage()
    key = storage.source_key(principal.organization_id, source_id, f"original.{detected.extension}")
    source = KnowledgeSource(
        id=source_id,
        organization_id=principal.organization_id,
        source_type=detected.kind.value,
        original_name=validation.safe_display_name(filename),
        storage_key=key,
        sha256=sha256,
        mime_type=detected.mime_type,
        size_bytes=len(data),
        uploaded_by=principal.user_id,
    )
    job = IngestionJob(organization_id=principal.organization_id, source_id=source_id)
    try:
        async with session.begin_nested():  # savepoint: a lost race only undoes this file
            session.add_all([source, job])
            await session.flush()
    except IntegrityError:
        # Another request uploaded the same file a moment ago (unique index).
        existing = await _live_source_by_sha(session, sha256)
        if existing is None:
            raise
        return UploadOutcome("duplicate", existing, None)

    storage.put_bytes(key, data)
    await audit.record(
        session,
        action="knowledge.source_uploaded",
        organization_id=principal.organization_id,
        actor_type="user",
        actor_id=str(principal.user_id),
        target_type="knowledge_source",
        target_id=str(source_id),
        details={"name": source.original_name, "type": source.source_type, "bytes": len(data)},
    )
    return UploadOutcome("created", source, job)


async def add_url(session: AsyncSession, principal: Principal, *, url: str) -> UploadOutcome:
    """Queue a web page for ingestion. Raises FetchBlockedError for unsafe URLs.

    We check DNS now to give immediate feedback; the worker checks again when it
    actually fetches (the answer may change in between).
    """
    target = parse_url(url)
    await SafeFetcher().validated_ip(target)
    source_id = new_id()
    source = KnowledgeSource(
        id=source_id,
        organization_id=principal.organization_id,
        source_type="url",
        original_name=f"{target.host}{target.path_query}"[:255],
        uri=target.url,
        uploaded_by=principal.user_id,
    )
    job = IngestionJob(organization_id=principal.organization_id, source_id=source_id)
    session.add_all([source, job])
    await session.flush()
    await audit.record(
        session,
        action="knowledge.url_added",
        organization_id=principal.organization_id,
        actor_type="user",
        actor_id=str(principal.user_id),
        target_type="knowledge_source",
        target_id=str(source_id),
        details={"url": target.url},
    )
    return UploadOutcome("created", source, job)


async def latest_jobs(
    session: AsyncSession, source_ids: list[uuid.UUID]
) -> dict[uuid.UUID, IngestionJob]:
    if not source_ids:
        return {}
    newest = (
        select(IngestionJob.source_id, func.max(IngestionJob.created_at).label("created_at"))
        .where(IngestionJob.source_id.in_(source_ids))
        .group_by(IngestionJob.source_id)
        .subquery()
    )
    rows = await session.scalars(
        select(IngestionJob).join(
            newest,
            (IngestionJob.source_id == newest.c.source_id)
            & (IngestionJob.created_at == newest.c.created_at),
        )
    )
    return {job.source_id: job for job in rows}


async def list_sources(session: AsyncSession) -> list[tuple[KnowledgeSource, IngestionJob | None]]:
    sources = list(
        await session.scalars(
            select(KnowledgeSource)
            .where(KnowledgeSource.deleted_at.is_(None))
            .order_by(KnowledgeSource.created_at.desc())
            .limit(500)
        )
    )
    jobs = await latest_jobs(session, [s.id for s in sources])
    return [(s, jobs.get(s.id)) for s in sources]


async def get_source(
    session: AsyncSession, source_id: uuid.UUID
) -> tuple[KnowledgeSource, IngestionJob | None]:
    # RLS already hides other organizations' rows: a foreign id simply isn't found.
    source = await session.get(KnowledgeSource, source_id)
    if source is None or source.deleted_at is not None:
        raise SourceNotFoundError
    jobs = await latest_jobs(session, [source_id])
    return source, jobs.get(source_id)


async def extracted_markdown(session: AsyncSession, source_id: uuid.UUID) -> str:
    _source, job = await get_source(session, source_id)
    # Available as soon as an extraction exists, whatever happened afterwards (AI, review).
    if job is None or not job.extracted_key:
        raise SourceConflictError("The extracted text is not available yet.")
    return get_storage().get_text(job.extracted_key)


async def retry(session: AsyncSession, principal: Principal, source_id: uuid.UUID) -> IngestionJob:
    source, job = await get_source(session, source_id)
    if job is not None and job.status in ACTIVE_JOB_STATUSES:
        raise SourceConflictError("This source is already being processed.")
    new_job = IngestionJob(organization_id=source.organization_id, source_id=source.id)
    session.add(new_job)
    await session.flush()
    await audit.record(
        session,
        action="knowledge.source_retried",
        organization_id=principal.organization_id,
        actor_type="user",
        actor_id=str(principal.user_id),
        target_type="knowledge_source",
        target_id=str(source.id),
    )
    return new_job


async def request_generation(
    session: AsyncSession, principal: Principal, source_id: uuid.UUID
) -> IngestionJob:
    """Queue AI knowledge generation again, reusing the text that was already extracted."""
    if not get_settings().llm_configured:
        raise SourceConflictError("AI generation is not configured (ANTHROPIC_API_KEY is missing).")
    source, job = await get_source(session, source_id)
    if job is not None and job.status in ACTIVE_JOB_STATUSES:
        raise SourceConflictError("This source is already being processed.")
    extracted = await session.scalar(
        select(IngestionJob)
        .where(IngestionJob.source_id == source.id, IngestionJob.extracted_key.is_not(None))
        .order_by(IngestionJob.created_at.desc())
        .limit(1)
    )
    if extracted is None:
        raise SourceConflictError("Extract the document first (use Retry).")
    new_job = IngestionJob(
        organization_id=source.organization_id,
        source_id=source.id,
        extracted_key=extracted.extracted_key,
        docling_key=extracted.docling_key,
        stats={k: v for k, v in extracted.stats.items() if k != "generation"},
    )
    session.add(new_job)
    await session.flush()
    await audit.record(
        session,
        action="knowledge.generation_requested",
        organization_id=principal.organization_id,
        actor_type="user",
        actor_id=str(principal.user_id),
        target_type="knowledge_source",
        target_id=str(source.id),
    )
    return new_job


async def soft_delete(session: AsyncSession, principal: Principal, source_id: uuid.UUID) -> None:
    """Hide the source. Files are kept until a retention job purges them (recoverable)."""
    source, _job = await get_source(session, source_id)
    source.deleted_at = datetime.now(UTC)
    await audit.record(
        session,
        action="knowledge.source_deleted",
        organization_id=principal.organization_id,
        actor_type="user",
        actor_id=str(principal.user_id),
        target_type="knowledge_source",
        target_id=str(source.id),
        details={"name": source.original_name},
    )
