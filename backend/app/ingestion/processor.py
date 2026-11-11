"""Worker-side processing of ingestion jobs.

Job lifecycle (Phase 3):

    queued ──claim──► fetching (URLs only) ──► extracting ──► extracted
       ▲                                │
       └── retry with backoff ◄─────────┴──► failed (permanent error or out of attempts)

* Claiming uses the `ingestion_claim_next_job` database function (owner-run):
  several workers never take the same job, and jobs left "running" by a
  crashed worker are picked up again after WORKER_STALE_LOCK_MINUTES.
* Every status change is committed immediately so the dashboard shows progress.
* Each job is processed inside a tenant-scoped session (Row-Level Security).
* Permanent errors (bad file, blocked URL, unreadable document) fail at once;
  temporary ones (network, unexpected crash) are retried with backoff.
"""

import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_sessionmaker, tenant_session
from app.ingestion import validation
from app.ingestion.extractor import DoclingExtractor, ExtractionError, markdown_header
from app.ingestion.safe_fetch import FetchBlockedError, FetchError, SafeFetcher
from app.models.knowledge import IngestionJob, KnowledgeSource
from app.storage.files import LocalFileStorage, get_storage

log = get_logger("ingestion")

PERMANENT_ERRORS = (FetchBlockedError, validation.UnsupportedFileError, ExtractionError)
MIME_TO_KIND = {mime: kind for kind, mime in validation.MIME_TYPES.items()}
MIME_TO_KIND["application/xhtml+xml"] = validation.FileKind.HTML
MAX_OUTLINE = 300


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    job_id: uuid.UUID
    organization_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """Plain copy of the source row, so we don't hold a DB session during slow work."""

    source_id: uuid.UUID
    source_type: str
    uri: str | None
    storage_key: str | None
    name: str
    deleted: bool


def retry_delay(attempt: int) -> timedelta:
    """30 s, 60 s, 120 s, ... capped at 30 minutes."""
    return timedelta(seconds=min(30 * 2 ** max(attempt - 1, 0), 1800))


class IngestionProcessor:
    def __init__(
        self,
        *,
        extractor: DoclingExtractor,
        fetcher: SafeFetcher | None = None,
        storage: LocalFileStorage | None = None,
    ) -> None:
        self.extractor = extractor
        self.fetcher = fetcher or SafeFetcher()
        self.storage = storage or get_storage()
        self.settings = get_settings()

    async def claim(self, worker_id: str) -> ClaimedJob | None:
        async with get_sessionmaker()() as session, session.begin():
            row = (
                await session.execute(
                    text(
                        "SELECT job_id, organization_id FROM ingestion_claim_next_job("
                        ":worker, make_interval(mins => :stale))"
                    ),
                    {"worker": worker_id, "stale": self.settings.worker_stale_lock_minutes},
                )
            ).first()
        return ClaimedJob(row.job_id, row.organization_id) if row else None

    async def run_once(self, worker_id: str) -> bool:
        """Process at most one job. Returns True if a job was processed."""
        claimed = await self.claim(worker_id)
        if claimed is None:
            return False
        await self.process(claimed)
        return True

    async def _update(self, claimed: ClaimedJob, **values: Any) -> None:
        async with tenant_session(claimed.organization_id) as session:
            job = await session.get(IngestionJob, claimed.job_id)
            if job is None:
                return
            for key, value in values.items():
                setattr(job, key, value)

    async def process(self, claimed: ClaimedJob) -> None:
        async with tenant_session(claimed.organization_id) as session:
            job = await session.get(IngestionJob, claimed.job_id)
            source = await session.get(KnowledgeSource, job.source_id) if job else None
            if job is None or source is None:
                return
            attempts = job.attempts
            snapshot = SourceSnapshot(
                source_id=source.id,
                source_type=source.source_type,
                uri=source.uri,
                storage_key=source.storage_key,
                name=source.original_name,
                deleted=source.deleted_at is not None,
            )
        bound = log.bind(job_id=str(claimed.job_id), org_id=str(claimed.organization_id))
        if snapshot.deleted:
            await self._fail(claimed, "The source was deleted.")
            return

        bound.info("ingestion_started", attempt=attempts, source_type=snapshot.source_type)
        try:
            if snapshot.source_type == "url":
                await self._update(claimed, status="fetching", progress=10, error=None)
                kind, data, sha256 = await self._fetch_url(claimed, snapshot)
            else:
                if snapshot.storage_key is None:
                    raise ExtractionError("The uploaded file is missing.")
                kind = validation.FileKind(snapshot.source_type)
                data = self.storage.get_bytes(snapshot.storage_key)
                sha256 = hashlib.sha256(data).hexdigest()

            await self._update(claimed, status="extracting", progress=40, error=None)
            result = await asyncio.to_thread(self.extractor.extract, kind, data)

            source_id = snapshot.source_id
            org_id = claimed.organization_id
            md_key = self.storage.source_key(org_id, source_id, "extracted.md")
            header = markdown_header(
                source_name=snapshot.name, sha256=sha256, extractor=result.stats["extractor"]
            )
            self.storage.put_text(md_key, header + result.markdown)
            docling_key = None
            if result.docling_json is not None:
                docling_key = self.storage.source_key(org_id, source_id, "docling.json.gz")
                self.storage.put_json_gz(docling_key, result.docling_json)

            stats = dict(result.stats)
            stats["outline"] = [
                {"text": h.text[:300], "page": h.page} for h in result.headings[:MAX_OUTLINE]
            ]
            async with tenant_session(org_id) as session:
                job = await session.get(IngestionJob, claimed.job_id)
                src = await session.get(KnowledgeSource, source_id)
                assert job is not None and src is not None
                job.status, job.progress, job.error = "extracted", 100, None
                job.extracted_key, job.docling_key, job.stats = md_key, docling_key, stats
                job.finished_at, job.locked_at, job.locked_by = datetime.now(UTC), None, None
                src.page_count = result.page_count
            bound.info(
                "ingestion_finished", pages=result.page_count, duration_ms=stats["duration_ms"]
            )
        except PERMANENT_ERRORS as exc:
            bound.warning("ingestion_failed", error=str(exc), permanent=True)
            await self._fail(claimed, str(exc))
        except Exception as exc:
            message = (
                str(exc)
                if isinstance(exc, FetchError)
                else "An internal error occurred while processing this document."
            )
            bound.error("ingestion_error", error=repr(exc), attempt=attempts, exc_info=True)
            if attempts >= self.settings.ingestion_max_attempts:
                await self._fail(claimed, f"{message} (gave up after {attempts} attempts)")
            else:
                await self._update(
                    claimed,
                    status="queued",
                    error=f"{message} Retrying automatically.",
                    run_after=datetime.now(UTC) + retry_delay(attempts),
                    locked_at=None,
                    locked_by=None,
                )

    async def _fail(self, claimed: ClaimedJob, error: str) -> None:
        await self._update(
            claimed,
            status="failed",
            error=error,
            finished_at=datetime.now(UTC),
            locked_at=None,
            locked_by=None,
        )

    async def _fetch_url(
        self, claimed: ClaimedJob, snapshot: SourceSnapshot
    ) -> tuple[validation.FileKind, bytes, str]:
        url = snapshot.uri
        if not url:
            raise FetchBlockedError("The source has no URL.")
        if not await self.fetcher.robots_allows(url):
            raise FetchBlockedError("The website's robots.txt does not allow fetching this page.")
        fetched = await self.fetcher.fetch(url)
        kind = MIME_TO_KIND.get(fetched.content_type)
        if kind is None:
            raise FetchBlockedError(f"Unsupported content type: {fetched.content_type}.")
        # Same byte-level checks as uploads (a "PDF" link must really be a PDF).
        detected = validation.detect(
            fetched.body, f"page.{validation.EXTENSIONS[kind]}", max_bytes=len(fetched.body) + 1
        )
        sha256 = hashlib.sha256(fetched.body).hexdigest()
        key = self.storage.source_key(
            claimed.organization_id, snapshot.source_id, f"original.{detected.extension}"
        )
        self.storage.put_bytes(key, fetched.body)
        async with tenant_session(claimed.organization_id) as session:
            duplicate = await session.scalar(
                select(KnowledgeSource.original_name).where(
                    KnowledgeSource.sha256 == sha256,
                    KnowledgeSource.deleted_at.is_(None),
                    KnowledgeSource.id != snapshot.source_id,
                )
            )
            if duplicate:
                raise FetchBlockedError(f"The same content was already added as '{duplicate}'.")
            src = await session.get(KnowledgeSource, snapshot.source_id)
            assert src is not None
            src.final_uri, src.storage_key, src.sha256 = fetched.url, key, sha256
            src.mime_type, src.size_bytes = detected.mime_type, len(fetched.body)
        return detected.kind, fetched.body, sha256
