"""Knowledge source endpoints: upload documents, add URLs, follow processing."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import PlainTextResponse

from app.api.deps import DbSession, require
from app.core.config import get_settings
from app.core.principal import Principal
from app.core.rbac import Permission
from app.ingestion.safe_fetch import FetchBlockedError
from app.ingestion.validation import UnsupportedFileError, safe_display_name
from app.schemas.knowledge import (
    AddUrlRequest,
    SourceDetail,
    SourceOut,
    UploadItemOut,
    UploadResponse,
)
from app.services import knowledge_sources as svc

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])

Viewer = Annotated[Principal, Depends(require(Permission.VIEW_KNOWLEDGE))]
Editor = Annotated[Principal, Depends(require(Permission.EDIT_KNOWLEDGE))]
Publisher = Annotated[Principal, Depends(require(Permission.PUBLISH_KNOWLEDGE))]

_CHUNK = 1024 * 1024


async def _read_capped(upload: UploadFile, max_bytes: int) -> bytes:
    """Read an upload in chunks and stop as soon as it exceeds the limit."""
    data = bytearray()
    while chunk := await upload.read(_CHUNK):
        data.extend(chunk)
        if len(data) > max_bytes:
            raise UnsupportedFileError(f"The file is larger than {max_bytes // (1024 * 1024)} MB.")
    return bytes(data)


@router.post("/sources", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_sources(
    principal: Editor,
    session: DbSession,
    files: Annotated[list[UploadFile], File(description="PDF, DOCX, HTML, Markdown or text")],
) -> UploadResponse:
    """Upload one or more documents. Each file gets its own result (created/duplicate/rejected)."""
    settings = get_settings()
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No files were uploaded.")
    if len(files) > settings.max_files_per_upload:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Upload at most {settings.max_files_per_upload} files at a time.",
        )
    items: list[UploadItemOut] = []
    for upload in files:
        name = safe_display_name(upload.filename)
        try:
            data = await _read_capped(upload, settings.max_upload_bytes)
            outcome = await svc.upload_file(session, principal, filename=name, data=data)
        except UnsupportedFileError as exc:
            items.append(UploadItemOut(filename=name, status="rejected", error=str(exc)))
            continue
        finally:
            await upload.close()
        items.append(
            UploadItemOut(
                filename=name,
                status=outcome.status,
                source=SourceOut.build(outcome.source, outcome.job),
            )
        )
    return UploadResponse(items=items)


@router.post("/sources/url", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
async def add_url_source(body: AddUrlRequest, principal: Editor, session: DbSession) -> SourceOut:
    """Queue a public web page for ingestion (private/internal addresses are refused)."""
    try:
        outcome = await svc.add_url(session, principal, url=body.url)
    except FetchBlockedError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return SourceOut.build(outcome.source, outcome.job)


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(_: Viewer, session: DbSession) -> list[SourceOut]:
    return [SourceOut.build(s, j) for s, j in await svc.list_sources(session)]


@router.get("/sources/{source_id}", response_model=SourceDetail)
async def get_source(source_id: uuid.UUID, _: Viewer, session: DbSession) -> SourceDetail:
    try:
        source, job = await svc.get_source(session, source_id)
    except svc.SourceNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found") from exc
    return SourceDetail.build_detail(source, job)


@router.get(
    "/sources/{source_id}/extracted",
    response_class=PlainTextResponse,
    responses={200: {"content": {"text/markdown": {}}}},
)
async def get_extracted(source_id: uuid.UUID, _: Viewer, session: DbSession) -> Response:
    """The extracted text as Markdown, with `<!-- page: N -->` markers for PDFs."""
    try:
        markdown = await svc.extracted_markdown(session, source_id)
    except svc.SourceNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found") from exc
    except svc.SourceConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    # Served as plain text, never rendered as HTML (content comes from untrusted files).
    return PlainTextResponse(
        markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/sources/{source_id}/retry", response_model=SourceOut)
async def retry_source(source_id: uuid.UUID, principal: Editor, session: DbSession) -> SourceOut:
    try:
        await svc.retry(session, principal, source_id)
        source, job = await svc.get_source(session, source_id)
    except svc.SourceNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found") from exc
    except svc.SourceConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return SourceOut.build(source, job)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: uuid.UUID, principal: Publisher, session: DbSession) -> Response:
    try:
        await svc.soft_delete(session, principal, source_id)
    except svc.SourceNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
