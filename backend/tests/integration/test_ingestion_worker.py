"""Job lifecycle tests for the ingestion worker (fast: Docling is replaced by a fake)."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.principal import Principal
from app.db.session import tenant_session
from app.ingestion.extractor import ExtractionError, ExtractionResult, Heading
from app.ingestion.processor import IngestionProcessor, retry_delay
from app.ingestion.safe_fetch import SafeFetcher
from app.ingestion.validation import FileKind
from app.models.knowledge import IngestionJob, KnowledgeSource
from app.services import knowledge_sources as svc
from app.storage.files import get_storage


class FakeExtractor:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[FileKind] = []

    def extract(self, kind: FileKind, data: bytes) -> ExtractionResult:
        self.calls.append(kind)
        if self.error:
            raise self.error
        return ExtractionResult(
            markdown="<!-- page: 1 -->\n\n## Warranty\n\n24-month limited warranty.\n",
            page_count=1,
            headings=[Heading("Warranty", 1)],
            table_count=0,
            docling_json={"fake": True},
            stats={"extractor": "fake", "duration_ms": 1},
        )


def _principal(org) -> Principal:  # type: ignore[no-untyped-def]
    user = org.users["editor"]
    return Principal(user.id, org.id, "editor", user.email, "editor")


async def _upload(org, data: bytes = b"# Manual\n\nSome text here.") -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session(org.id) as session:
        outcome = await svc.upload_file(session, _principal(org), filename="manual.md", data=data)
        return outcome.source.id


async def _job(org, source_id: uuid.UUID) -> IngestionJob:  # type: ignore[no-untyped-def]
    async with tenant_session(org.id) as session:
        jobs = await svc.latest_jobs(session, [source_id])
        return jobs[source_id]


async def test_successful_job_writes_outputs(make_org) -> None:
    org = make_org("technova")
    source_id = await _upload(org)
    extractor = FakeExtractor()
    processor = IngestionProcessor(extractor=extractor)  # type: ignore[arg-type]

    assert await processor.run_once("test-worker")
    assert not await processor.run_once("test-worker")  # queue now empty

    job = await _job(org, source_id)
    assert job.status == "extracted" and job.progress == 100 and job.attempts == 1
    assert job.stats["outline"] == [{"text": "Warranty", "page": 1}]
    assert extractor.calls == [FileKind.MARKDOWN]
    stored = get_storage().get_text(job.extracted_key)
    assert stored.startswith("<!-- source: manual.md | sha256: ")
    assert "24-month limited warranty" in stored
    async with tenant_session(org.id) as session:
        source = await session.get(KnowledgeSource, source_id)
        assert source.page_count == 1


async def test_permanent_error_fails_immediately(make_org) -> None:
    org = make_org("technova")
    source_id = await _upload(org)
    processor = IngestionProcessor(extractor=FakeExtractor(ExtractionError("Unreadable.")))  # type: ignore[arg-type]
    await processor.run_once("w")
    job = await _job(org, source_id)
    assert job.status == "failed"
    assert job.error == "Unreadable."
    assert job.attempts == 1


async def test_unexpected_error_is_retried_with_backoff_then_gives_up(
    make_org, owner_engine
) -> None:
    org = make_org("technova")
    source_id = await _upload(org)
    processor = IngestionProcessor(extractor=FakeExtractor(RuntimeError("boom")))  # type: ignore[arg-type]

    await processor.run_once("w")
    job = await _job(org, source_id)
    assert job.status == "queued" and job.attempts == 1
    assert "Retrying automatically" in job.error
    assert "boom" not in job.error  # internal details are not shown to users
    assert job.run_after > datetime.now(UTC) + timedelta(seconds=20)
    assert not await processor.run_once("w")  # backoff: not due yet

    for _ in range(2):  # make it due again and retry until attempts are exhausted
        with Session(owner_engine) as s, s.begin():
            s.execute(text("UPDATE ingestion_jobs SET run_after = now() - interval '1 second'"))
        await processor.run_once("w")
    job = await _job(org, source_id)
    assert job.status == "failed" and job.attempts == 3
    assert "gave up after 3 attempts" in job.error


def test_retry_delay_grows_and_is_capped() -> None:
    assert [retry_delay(n).total_seconds() for n in (1, 2, 3)] == [30, 60, 120]
    assert retry_delay(20).total_seconds() == 1800


async def test_two_workers_never_claim_the_same_job(make_org) -> None:
    org = make_org("technova")
    await _upload(org, b"# One\n\nfirst document text")
    await _upload(org, b"# Two\n\nsecond document text")
    processor = IngestionProcessor(extractor=FakeExtractor())  # type: ignore[arg-type]
    first = await processor.claim("worker-a")
    second = await processor.claim("worker-b")
    third = await processor.claim("worker-c")
    assert first and second and first.job_id != second.job_id
    assert third is None


async def test_stale_job_from_crashed_worker_is_reclaimed(make_org, owner_engine) -> None:
    org = make_org("technova")
    source_id = await _upload(org)
    processor = IngestionProcessor(extractor=FakeExtractor())  # type: ignore[arg-type]
    claimed = await processor.claim("crashed-worker")
    assert claimed is not None
    with Session(owner_engine) as s, s.begin():  # it "crashed" mid-extraction long ago
        s.execute(
            text(
                "UPDATE ingestion_jobs SET status = 'extracting', "
                "locked_at = now() - interval '1 hour'"
            )
        )
    assert await processor.run_once("healthy-worker")
    job = await _job(org, source_id)
    assert job.status == "extracted" and job.attempts == 2


async def test_url_job_fetches_safely_and_extracts(make_org) -> None:
    org = make_org("technova")
    html = b"<!doctype html><html><body><h1>FAQ</h1><p>Answer text.</p></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "text/html"}, content=html)

    async def resolver(host: str, port: int) -> list[str]:
        return ["93.184.215.14"]

    async with tenant_session(org.id) as session:
        source = KnowledgeSource(
            organization_id=org.id, source_type="url", original_name="docs.example/faq",
            uri="https://docs.example/faq",
        )  # fmt: skip
        session.add(source)
        await session.flush()
        session.add(IngestionJob(organization_id=org.id, source_id=source.id))
        source_id = source.id

    extractor = FakeExtractor()
    fetcher = SafeFetcher(resolver=resolver, transport=httpx.MockTransport(handler))
    processor = IngestionProcessor(extractor=extractor, fetcher=fetcher)  # type: ignore[arg-type]
    await processor.run_once("w")

    job = await _job(org, source_id)
    assert job.status == "extracted", job.error
    assert extractor.calls == [FileKind.HTML]
    async with tenant_session(org.id) as session:
        src = await session.get(KnowledgeSource, source_id)
        assert src.sha256 and src.mime_type == "text/html" and src.size_bytes == len(html)


@pytest.mark.parametrize("robots_status", [503])
async def test_url_job_blocked_by_unreachable_robots(make_org, robots_status: int) -> None:
    org = make_org("technova")

    async def resolver(host: str, port: int) -> list[str]:
        return ["93.184.215.14"]

    fetcher = SafeFetcher(
        resolver=resolver, transport=httpx.MockTransport(lambda r: httpx.Response(robots_status))
    )
    async with tenant_session(org.id) as session:
        source = KnowledgeSource(
            organization_id=org.id,
            source_type="url",
            original_name="x",
            uri="https://docs.example/",
        )
        session.add(source)
        await session.flush()
        session.add(IngestionJob(organization_id=org.id, source_id=source.id))
        source_id = source.id

    processor = IngestionProcessor(extractor=FakeExtractor(), fetcher=fetcher)  # type: ignore[arg-type]
    await processor.run_once("w")
    job = await _job(org, source_id)
    assert job.status == "failed"
    assert "robots.txt" in job.error
