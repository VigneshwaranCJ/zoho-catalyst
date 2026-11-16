"""Knowledge review & publishing (human-in-the-loop).

    AI drafts / human edits ──► knowledge_versions (review_status = pending)
                                   │  reviewer approves            │ reviewer rejects
                                   ▼                                ▼
     finalize frontmatter (status: stable, verified by human:<id>)  rejected
     validate again (must pass) ──► ONE Git commit on main (+ regenerated index.md / log.md)
     ──► document.current_version = this version ──► rebuild search sections & links

Publishing is serialized per organization with a PostgreSQL advisory lock, so two
reviewers approving at the same time can't interleave Git commits.
"""

import difflib
import hashlib
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.principal import Principal
from app.knowledge.generation import GeneratedFile
from app.knowledge.indexer import split_sections
from app.knowledge.okf import bundle as okfbundle
from app.knowledge.okf import document as okfdoc
from app.knowledge.okf import validate as okfvalidate
from app.knowledge.repo import KnowledgeRepo, check_bundle_path
from app.models.knowledge import IngestionJob
from app.models.knowledge_docs import (
    KnowledgeDocument,
    KnowledgeLink,
    KnowledgeSection,
    KnowledgeVersion,
)
from app.models.organization import Organization
from app.services import audit

INJECTION_WARNING_PREFIX = "Possible prompt injection"


class PublishError(ValueError):
    """User-safe reason an operation was refused."""


class VersionNotFoundError(LookupError):
    pass


def _sha(text_: str) -> str:
    return hashlib.sha256(text_.encode("utf-8")).hexdigest()


def _actor_id(principal: Principal) -> str:
    return f"human:{str(principal.user_id).replace('-', '')[:12]}"


# ------------------------------------------------------------------ drafts
async def _next_version_no(session: AsyncSession, document_id: uuid.UUID) -> int:
    current = await session.scalar(
        select(func.max(KnowledgeVersion.version_no)).where(
            KnowledgeVersion.document_id == document_id
        )
    )
    return int(current or 0) + 1


async def _supersede_pending(session: AsyncSession, document_id: uuid.UUID) -> None:
    """A newer draft replaces any older draft still waiting for review."""
    await session.execute(
        update(KnowledgeVersion)
        .where(
            KnowledgeVersion.document_id == document_id,
            KnowledgeVersion.review_status == "pending",
        )
        .values(review_status="superseded")
    )


async def _active_document(session: AsyncSession, path: str) -> KnowledgeDocument | None:
    return await session.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.path == path, KnowledgeDocument.status != "archived"
        )
    )


async def save_draft(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    path: str,
    content: str,
    validation: dict[str, Any],
    generated_by: str,
    title: str,
    doc_type: str,
    audience: str,
    source_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
) -> KnowledgeVersion:
    check_bundle_path(path)
    document = await _active_document(session, path)
    if document is None:
        document = KnowledgeDocument(
            organization_id=organization_id, path=path, title=title[:255], doc_type=doc_type,
            audience=audience, status="draft", tags=[],
        )  # fmt: skip
        session.add(document)
        await session.flush()
    else:
        await _supersede_pending(session, document.id)
    fm = okfdoc.parse(content).frontmatter or {}
    version = KnowledgeVersion(
        organization_id=organization_id,
        document_id=document.id,
        version_no=await _next_version_no(session, document.id),
        content=content,
        content_sha256=_sha(content),
        frontmatter=fm,
        validation=validation,
        review_status="pending",
        base_version_id=document.current_version_id,
        source_id=source_id,
        job_id=job_id,
        generated_by=generated_by,
        created_by=created_by,
    )
    session.add(version)
    await session.flush()
    return version


async def save_generated_drafts(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    files: list[GeneratedFile],
    source_id: uuid.UUID,
    job_id: uuid.UUID,
    generated_by: str,
) -> list[KnowledgeVersion]:
    return [
        await save_draft(
            session,
            organization_id=organization_id,
            path=f.path,
            content=f.content,
            validation=f.validation,
            generated_by=generated_by,
            title=f.title,
            doc_type=f.doc_type,
            audience=f.audience,
            source_id=source_id,
            job_id=job_id,
        )
        for f in files
    ]


def validate_content(
    path: str, content: str, known_paths: set[str] | None = None
) -> dict[str, Any]:
    report = okfvalidate.Report()
    okfvalidate.check_conformance(path, content, report)
    okfvalidate.check_profile(path, content, report, known_paths=known_paths)
    return report.as_dict()


async def edit_document(
    session: AsyncSession, principal: Principal, document_id: uuid.UUID, content: str
) -> KnowledgeVersion:
    """A human edit becomes a new draft that goes through review like AI drafts."""
    document = await session.get(KnowledgeDocument, document_id)
    if document is None or document.status == "archived":
        raise VersionNotFoundError
    try:
        fm = okfdoc.parse(content).frontmatter or {}
    except okfdoc.OkfParseError as exc:
        raise PublishError(str(exc)) from exc
    version = await save_draft(
        session,
        organization_id=document.organization_id,
        path=document.path,
        content=content,
        validation=validate_content(document.path, content, await live_paths(session)),
        generated_by=_actor_id(principal),
        title=str(fm.get("title") or document.title),
        doc_type=str(fm.get("type") or document.doc_type),
        audience=str(fm.get("audience") or document.audience),
        created_by=principal.user_id,
    )
    await audit.record(
        session, action="knowledge.document_edited", organization_id=principal.organization_id,
        actor_type="user", actor_id=str(principal.user_id), target_type="knowledge_document",
        target_id=str(document.id), details={"path": document.path, "version": version.version_no},
    )  # fmt: skip
    return version


async def live_paths(session: AsyncSession) -> set[str]:
    rows = await session.scalars(
        select(KnowledgeDocument.path).where(KnowledgeDocument.status == "live")
    )
    return set(rows)


# ------------------------------------------------------------------ review
@dataclass
class VersionView:
    version: KnowledgeVersion
    document: KnowledgeDocument
    diff: str
    has_injection_warnings: bool


async def get_version(session: AsyncSession, version_id: uuid.UUID) -> VersionView:
    version = await session.get(KnowledgeVersion, version_id)
    if version is None:
        raise VersionNotFoundError
    document = await session.get(KnowledgeDocument, version.document_id)
    assert document is not None
    base = (
        await session.get(KnowledgeVersion, version.base_version_id)
        if version.base_version_id
        else None
    )
    diff = "".join(
        difflib.unified_diff(
            (base.content if base else "").splitlines(keepends=True),
            version.content.splitlines(keepends=True),
            fromfile=f"{document.path} (published)" if base else "/dev/null",
            tofile=f"{document.path} (v{version.version_no})",
        )
    )
    warnings = version.validation.get("warnings", [])
    return VersionView(
        version, document, diff,
        any(str(w.get("message", "")).startswith(INJECTION_WARNING_PREFIX) for w in warnings),
    )  # fmt: skip


def _finalize(content: str, principal: Principal, now: datetime) -> str:
    """Mark as approved: status stable + a human verification event (OKF §5.2/§5.3)."""
    doc = okfdoc.parse(content)
    fm = dict(doc.frontmatter or {})
    fm["status"] = "stable"
    verified = fm.get("verified") or []
    if isinstance(verified, dict):
        verified = [verified]
    verified = [v for v in verified if not str(v.get("by", "")).startswith("human:")]
    verified.append({"by": _actor_id(principal), "at": now.isoformat(timespec="seconds")})
    fm["verified"] = verified
    return okfdoc.render(fm, doc.body)


async def _lock_org(session: AsyncSession, organization_id: uuid.UUID) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"knowledge-publish:{organization_id}"},
    )


async def _reindex(
    session: AsyncSession, document: KnowledgeDocument, version: KnowledgeVersion
) -> int:
    await session.execute(
        delete(KnowledgeSection).where(KnowledgeSection.document_id == document.id)
    )
    await session.execute(
        delete(KnowledgeLink).where(KnowledgeLink.from_document_id == document.id)
    )
    sections = split_sections(version.content)
    for s in sections:
        session.add(
            KnowledgeSection(
                organization_id=document.organization_id, document_id=document.id,
                version_id=version.id, position=s.position, anchor=s.anchor[:120],
                heading=s.heading, heading_path=s.heading_path, body=s.body,
                source_pages=s.source_pages, audience=document.audience, doc_title=document.title,
            )
        )  # fmt: skip
    for target in sorted(set(okfdoc.parse(version.content).links)):
        if target.startswith("/") and target.endswith(".md"):
            session.add(
                KnowledgeLink(
                    organization_id=document.organization_id, from_document_id=document.id,
                    to_path=target.lstrip("/")[:255],
                )
            )  # fmt: skip
    return len(sections)


async def _update_job_status(session: AsyncSession, job_ids: Iterable[uuid.UUID | None]) -> None:
    for job_id in {j for j in job_ids if j}:
        pending = await session.scalar(
            select(func.count()).where(
                KnowledgeVersion.job_id == job_id, KnowledgeVersion.review_status == "pending"
            )
        )
        if not pending:
            await session.execute(
                update(IngestionJob)
                .where(IngestionJob.id == job_id, IngestionJob.status == "needs_review")
                .values(status="reviewed")
            )


async def approve(
    session: AsyncSession,
    principal: Principal,
    version_ids: list[uuid.UUID],
    *,
    note: str | None = None,
    acknowledge_warnings: bool = False,
) -> str:
    """Approve one or more drafts in ONE Git commit. Returns the commit SHA."""
    if not version_ids:
        raise PublishError("Nothing to approve.")
    await _lock_org(session, principal.organization_id)
    now = datetime.now(UTC)
    views = [await get_version(session, vid) for vid in dict.fromkeys(version_ids)]
    for view in views:
        v, d = view.version, view.document
        if v.review_status != "pending":
            raise PublishError(f"{d.path}: this draft was already {v.review_status}.")
        if v.base_version_id != d.current_version_id:
            raise PublishError(
                f"{d.path}: the document changed after this draft was created. "
                "Open the current version and edit again."
            )
        if view.has_injection_warnings and not acknowledge_warnings:
            raise PublishError(
                f"{d.path}: the source contains possible prompt-injection text. Review the "
                "warnings and confirm to publish."
            )

    repo = KnowledgeRepo(principal.organization_id)
    bundle = repo.read_all()
    known = {p for p in bundle} | {view.document.path for view in views}
    changes: dict[str, str | None] = {}
    finals: dict[uuid.UUID, str] = {}
    for view in views:
        final = _finalize(view.version.content, principal, now)
        report = validate_content(view.document.path, final, known)
        if not report["ok"]:
            first = report["errors"][0]["message"]
            raise PublishError(f"{view.document.path}: fix validation errors first ({first}).")
        finals[view.version.id] = final
        changes[view.document.path] = final

    org = await session.get(Organization, principal.organization_id)
    merged = {**bundle, **{p: c for p, c in changes.items() if c is not None}}
    concepts = {
        p: c for p, c in merged.items() if PurePosixPath(p).name not in {"index.md", "log.md"}
    }
    changes.update(
        okfbundle.build_indexes(
            concepts, bundle_title=f"{org.name if org else 'Company'} Knowledge"
        )
    )
    changes["log.md"] = okfbundle.add_log_entry(
        bundle.get("log.md"),
        day=now.date(),
        entries=[
            f"**{'Update' if view.document.current_version_id else 'Creation'}**: "
            f"[{view.document.title}](/{view.document.path}) (v{view.version.version_no})"
            for view in views
        ],
    )
    titles = ", ".join(view.document.path for view in views[:5])
    message = f"Publish {len(views)} document(s): {titles}" + ("..." if len(views) > 5 else "")
    if note:
        message += f"\n\n{note.strip()[:1000]}"
    sha = repo.commit(
        changes,
        message=message,
        author_id=str(principal.user_id),
        author_name=principal.display_name,
    )

    for view in views:
        v, d = view.version, view.document
        final = finals[v.id]
        fm = okfdoc.parse(final).frontmatter or {}
        v.content, v.content_sha256, v.frontmatter = final, _sha(final), fm
        v.review_status, v.reviewed_by, v.reviewed_at = "approved", principal.user_id, now
        v.review_note, v.git_commit_sha = note, sha
        d.status, d.current_version_id = "live", v.id
        d.title = str(fm.get("title") or d.title)[:255]
        d.doc_type = str(fm.get("type") or d.doc_type)
        d.description = fm.get("description")
        d.audience = str(fm.get("audience") or d.audience)
        d.tags = [str(t) for t in fm.get("tags") or []]
        await session.flush()
        sections = await _reindex(session, d, v)
        await audit.record(
            session, action="knowledge.version_approved", organization_id=principal.organization_id,
            actor_type="user", actor_id=str(principal.user_id), target_type="knowledge_version",
            target_id=str(v.id),
            details={"path": d.path, "version": v.version_no, "commit": sha, "sections": sections,
                     "acknowledged_warnings": view.has_injection_warnings},
        )  # fmt: skip
    await _update_job_status(session, [view.version.job_id for view in views])
    return sha


async def reject(
    session: AsyncSession, principal: Principal, version_id: uuid.UUID, *, note: str | None = None
) -> None:
    view = await get_version(session, version_id)
    v, d = view.version, view.document
    if v.review_status != "pending":
        raise PublishError(f"This draft was already {v.review_status}.")
    v.review_status, v.reviewed_by, v.reviewed_at = "rejected", principal.user_id, datetime.now(UTC)
    v.review_note = note
    if d.current_version_id is None:
        d.status = "archived"  # never published: free the path for future drafts
    await audit.record(
        session, action="knowledge.version_rejected", organization_id=principal.organization_id,
        actor_type="user", actor_id=str(principal.user_id), target_type="knowledge_version",
        target_id=str(v.id), details={"path": d.path, "note": note},
    )  # fmt: skip
    await _update_job_status(session, [v.job_id])


async def archive_document(
    session: AsyncSession, principal: Principal, document_id: uuid.UUID
) -> None:
    """Remove a document from the published bundle (Git keeps the history)."""
    await _lock_org(session, principal.organization_id)
    document = await session.get(KnowledgeDocument, document_id)
    if document is None or document.status == "archived":
        raise VersionNotFoundError
    if document.status == "live":
        repo = KnowledgeRepo(principal.organization_id)
        bundle = repo.read_all()
        remaining = {
            p: c for p, c in bundle.items()
            if p != document.path and PurePosixPath(p).name not in {"index.md", "log.md"}
        }  # fmt: skip
        org = await session.get(Organization, principal.organization_id)
        changes: dict[str, str | None] = {document.path: None}
        old_indexes = {p for p in bundle if PurePosixPath(p).name == "index.md"}
        new_indexes = okfbundle.build_indexes(
            remaining, bundle_title=f"{org.name if org else 'Company'} Knowledge"
        )
        changes.update(new_indexes)
        for stale in old_indexes - set(new_indexes):
            changes[stale] = None
        changes["log.md"] = okfbundle.add_log_entry(
            bundle.get("log.md"), day=datetime.now(UTC).date(),
            entries=[f"**Deprecation**: removed {document.title} (`{document.path}`)"],
        )  # fmt: skip
        repo.commit(
            changes, message=f"Remove {document.path}",
            author_id=str(principal.user_id), author_name=principal.display_name,
        )  # fmt: skip
    await _supersede_pending(session, document.id)
    await session.execute(
        delete(KnowledgeSection).where(KnowledgeSection.document_id == document.id)
    )
    await session.execute(
        delete(KnowledgeLink).where(KnowledgeLink.from_document_id == document.id)
    )
    document.status = "archived"
    await audit.record(
        session, action="knowledge.document_archived", organization_id=principal.organization_id,
        actor_type="user", actor_id=str(principal.user_id), target_type="knowledge_document",
        target_id=str(document.id), details={"path": document.path},
    )  # fmt: skip
