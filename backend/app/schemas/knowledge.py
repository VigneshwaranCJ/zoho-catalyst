import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.knowledge import IngestionJob, KnowledgeSource


class JobOut(BaseModel):
    id: uuid.UUID
    status: str
    progress: int
    attempts: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None


class SourceOut(BaseModel):
    id: uuid.UUID
    name: str
    source_type: str
    uri: str | None
    mime_type: str | None
    size_bytes: int | None
    page_count: int | None
    created_at: datetime
    job: JobOut | None

    @classmethod
    def build(cls, source: KnowledgeSource, job: IngestionJob | None) -> "SourceOut":
        return cls(
            id=source.id,
            name=source.original_name,
            source_type=source.source_type,
            uri=source.final_uri or source.uri,
            mime_type=source.mime_type,
            size_bytes=source.size_bytes,
            page_count=source.page_count,
            created_at=source.created_at,
            job=JobOut(
                id=job.id,
                status=job.status,
                progress=job.progress,
                attempts=job.attempts,
                error=job.error,
                started_at=job.started_at,
                finished_at=job.finished_at,
            )
            if job
            else None,
        )


class OutlineItem(BaseModel):
    text: str
    page: int | None


class SourceDetail(SourceOut):
    sha256: str | None
    outline: list[OutlineItem]
    stats: dict[str, Any]

    @classmethod
    def build_detail(cls, source: KnowledgeSource, job: IngestionJob | None) -> "SourceDetail":
        base = SourceOut.build(source, job)
        stats = dict(job.stats) if job else {}
        outline = [OutlineItem(**h) for h in stats.pop("outline", [])]
        return cls(**base.model_dump(), sha256=source.sha256, outline=outline, stats=stats)


class UploadItemOut(BaseModel):
    filename: str
    status: Literal["created", "duplicate", "rejected"]
    error: str | None = None
    source: SourceOut | None = None


class UploadResponse(BaseModel):
    items: list[UploadItemOut]


class AddUrlRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048, examples=["https://example.com/faq"])
