"""End-to-end knowledge flow: generate drafts -> review -> Git commit -> search.

Claude is replaced by the scripted FakeLLM (tests/fakes.py); everything else is
real: PostgreSQL (RLS), the worker, the Git repository, the search index.
"""

import uuid

import httpx
import pytest

from app.core.principal import Principal
from app.db.session import tenant_session
from app.ingestion.processor import IngestionProcessor
from app.knowledge.okf import document as okfdoc
from app.knowledge.okf.validate import validate_bundle
from app.knowledge.repo import KnowledgeRepo
from app.services import knowledge_publish as publish
from app.services import knowledge_sources as svc
from app.services.knowledge_search import search_sections
from tests.conftest import login
from tests.fakes import MANUAL_MARKDOWN, FakeLLM
from tests.fixtures.technova_bundle import BUNDLE, SEARCH_CASES
from tests.integration.test_ingestion_worker import FakeExtractor


class ManualExtractor(FakeExtractor):
    """Returns the TechNova manual excerpt as the 'extracted' text."""

    def extract(self, kind, data):  # type: ignore[no-untyped-def]
        result = super().extract(kind, data)
        result.markdown = MANUAL_MARKDOWN.split("\n\n", 1)[1]  # without the provenance header
        result.page_count = 12
        return result


def _principal(org, role: str = "org_admin") -> Principal:  # type: ignore[no-untyped-def]
    u = org.users[role]
    return Principal(u.id, org.id, role, u.email, role)


async def _generate_drafts(org) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session(org.id) as session:
        outcome = await svc.upload_file(
            session,
            _principal(org, "editor"),
            filename="SmartAir_X1_User_Manual.md",
            data=b"# SmartAir X1 manual\n\nplaceholder bytes, extraction is faked",
        )
        source_id = outcome.source.id
    processor = IngestionProcessor(extractor=ManualExtractor(), llm_factory=FakeLLM)  # type: ignore[arg-type]
    assert await processor.run_once("test-worker")
    return source_id


async def _publish_fixture_bundle(org) -> None:  # type: ignore[no-untyped-def]
    """Publish the hand-written TechNova bundle through the real review flow."""
    async with tenant_session(org.id) as session:
        versions = []
        for path, content in BUNDLE.items():
            fm = okfdoc.parse(content).frontmatter
            versions.append(
                await publish.save_draft(
                    session,
                    organization_id=org.id,
                    path=path,
                    content=content,
                    validation=publish.validate_content(path, content, set(BUNDLE)),
                    generated_by="csp-ingestor/claude-sonnet-5-5",
                    title=fm["title"],
                    doc_type=fm["type"],
                    audience=fm["audience"],
                )
            )
        await publish.approve(session, _principal(org), [v.id for v in versions])


async def _auth(client: httpx.AsyncClient, user) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {"X-CSRF-Token": (await login(client, user)).json()["csrf_token"]}


# ---------------------------------------------------------------- generation -> drafts
async def test_worker_generates_drafts_for_review(client: httpx.AsyncClient, make_org) -> None:
    org = make_org("technova")
    source_id = await _generate_drafts(org)
    await _auth(client, org.users["editor"])

    source = (await client.get(f"/api/v1/knowledge/sources/{source_id}")).json()
    assert source["job"]["status"] == "needs_review"
    generation = source["stats"]["generation"]
    assert generation["drafts"] == 3 and generation["dropped_statements"] == 2
    assert generation["usage"]["calls"] == 5 and generation["usage"]["cost_usd"] > 0

    drafts = (await client.get("/api/v1/knowledge/reviews")).json()
    assert {d["path"] for d in drafts} == {
        "products/smartair-x1-installation.md",
        "policies/smartair-x1-warranty.md",
        "sources/smartair-x1-user-manual.md",
    }
    assert all(d["error_count"] == 0 and not d["is_update"] for d in drafts)

    warranty = next(d for d in drafts if d["path"].endswith("warranty.md"))
    detail = (await client.get(f"/api/v1/knowledge/versions/{warranty['version_id']}")).json()
    assert detail["review_status"] == "pending"
    assert "24-month limited warranty" in detail["content"]
    assert detail["diff"].startswith("--- /dev/null")  # a brand-new document
    assert any("Dropped unverifiable" in w["message"] for w in detail["validation"]["warnings"])


async def test_approving_publishes_to_git_and_search(client: httpx.AsyncClient, make_org) -> None:
    org = make_org("technova")
    source_id = await _generate_drafts(org)
    headers = await _auth(client, org.users["editor"])  # editors may publish (RBAC)
    drafts = (await client.get("/api/v1/knowledge/reviews")).json()

    response = await client.post(
        "/api/v1/knowledge/versions/approve",
        headers=headers,
        json={"version_ids": [d["version_id"] for d in drafts], "note": "Looks right"},
    )
    assert response.status_code == 200, response.text
    sha = response.json()["commit_sha"]

    repo = KnowledgeRepo(org.id)
    files = repo.read_all()
    assert set(files) == {
        "index.md",
        "log.md",
        "products/index.md",
        "policies/index.md",
        "sources/index.md",
        "products/smartair-x1-installation.md",
        "policies/smartair-x1-warranty.md",
        "sources/smartair-x1-user-manual.md",
    }
    assert repo.head_sha() == sha
    report = validate_bundle(files)  # the published bundle is OKF-conformant + profile-valid
    assert report.ok, report.as_dict()
    fm = okfdoc.parse(files["policies/smartair-x1-warranty.md"]).frontmatter
    assert fm["status"] == "stable"
    assert fm["verified"][-1]["by"].startswith("human:")  # human-reviewed trust tier

    assert (await client.get("/api/v1/knowledge/reviews")).json() == []
    source = (await client.get(f"/api/v1/knowledge/sources/{source_id}")).json()
    assert source["job"]["status"] == "reviewed"

    hits = (await client.get("/api/v1/knowledge/search", params={"q": "warranty period"})).json()[
        "hits"
    ]
    assert hits[0]["path"] == "policies/smartair-x1-warranty.md"
    assert hits[0]["source_pages"] == [11]
    assert "[^" not in hits[0]["snippet"]  # footnote markers removed from search text

    docs = (await client.get("/api/v1/knowledge/documents")).json()
    warranty = next(d for d in docs if d["path"].endswith("warranty.md"))
    detail = (await client.get(f"/api/v1/knowledge/documents/{warranty['id']}")).json()
    assert detail["status"] == "live" and detail["trust_tier"] == "human-reviewed"
    assert detail["versions"][0]["git_commit_sha"] == sha


async def test_reject_keeps_draft_out_of_git(client: httpx.AsyncClient, make_org) -> None:
    org = make_org("technova")
    await _generate_drafts(org)
    headers = await _auth(client, org.users["editor"])
    drafts = (await client.get("/api/v1/knowledge/reviews")).json()
    for d in drafts:
        r = await client.post(
            f"/api/v1/knowledge/versions/{d['version_id']}/reject",
            headers=headers,
            json={"note": "no"},
        )
        assert r.status_code == 204
    assert KnowledgeRepo(org.id).head_sha() is None  # nothing was ever committed
    assert (await client.get("/api/v1/knowledge/documents")).json() == []  # paths freed


@pytest.mark.parametrize("role", ["agent", "viewer"])
async def test_only_publishers_can_approve(client: httpx.AsyncClient, make_org, role: str) -> None:
    org = make_org("technova")
    await _generate_drafts(org)
    headers = await _auth(client, org.users[role])
    drafts = (await client.get("/api/v1/knowledge/reviews")).json()  # may view
    response = await client.post(
        "/api/v1/knowledge/versions/approve",
        headers=headers,
        json={"version_ids": [drafts[0]["version_id"]]},
    )
    assert response.status_code == 403


async def test_edit_creates_a_reviewed_new_version(client: httpx.AsyncClient, make_org) -> None:
    org = make_org("technova")
    await _publish_fixture_bundle(org)
    headers = await _auth(client, org.users["editor"])
    docs = (await client.get("/api/v1/knowledge/documents")).json()
    doc = next(d for d in docs if d["path"] == "support/contact-support.md")
    current = (await client.get(f"/api/v1/knowledge/documents/{doc['id']}")).json()["content"]

    edited = current.replace("9:00-18:00", "8:00-20:00")
    draft = await client.put(
        f"/api/v1/knowledge/documents/{doc['id']}", headers=headers, json={"content": edited}
    )
    assert draft.status_code == 201, draft.text
    body = draft.json()
    assert body["review_status"] == "pending" and body["version_no"] == 2
    assert "-Hours: Monday to Friday, 9:00-18:00" in body["diff"]
    assert "+Hours: Monday to Friday, 8:00-20:00" in body["diff"]

    approved = await client.post(
        "/api/v1/knowledge/versions/approve",
        headers=headers,
        json={"version_ids": [body["version_id"]]},
    )
    assert approved.status_code == 200
    hits = (await client.get("/api/v1/knowledge/search", params={"q": "support hours"})).json()[
        "hits"
    ]
    assert "8:00-20:00" in hits[0]["snippet"]
    history = KnowledgeRepo(org.id).history("support/contact-support.md")
    assert len(history) == 2  # Git history shows both published versions


async def test_invalid_edit_cannot_be_published(client: httpx.AsyncClient, make_org) -> None:
    org = make_org("technova")
    await _publish_fixture_bundle(org)
    headers = await _auth(client, org.users["editor"])
    doc = next(
        d
        for d in (await client.get("/api/v1/knowledge/documents")).json()
        if d["path"] == "support/contact-support.md"
    )
    current = (await client.get(f"/api/v1/knowledge/documents/{doc['id']}")).json()["content"]
    broken = current.replace("[^smartair-x1-user-manual-p12]", "[^nowhere]", 1)
    draft = (
        await client.put(
            f"/api/v1/knowledge/documents/{doc['id']}", headers=headers, json={"content": broken}
        )
    ).json()
    assert draft["validation"]["ok"] is False
    response = await client.post(
        "/api/v1/knowledge/versions/approve",
        headers=headers,
        json={"version_ids": [draft["version_id"]]},
    )
    assert response.status_code == 409
    assert "validation errors" in response.json()["detail"]


async def test_stale_draft_is_refused(make_org) -> None:
    """Two edits based on the same version: the second can't silently overwrite the first."""
    org = make_org("technova")
    await _publish_fixture_bundle(org)
    p = _principal(org)
    async with tenant_session(org.id) as session:
        doc = next(
            d for d in await publish.live_paths(session) if d == "support/contact-support.md"
        )
        from sqlalchemy import select

        from app.models.knowledge_docs import KnowledgeDocument, KnowledgeVersion

        document = await session.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.path == doc)
        )
        current = await session.get(KnowledgeVersion, document.current_version_id)
        first = await publish.edit_document(
            session, p, document.id, current.content.replace("9:00", "8:00")
        )
        first_base = first.base_version_id
    async with tenant_session(org.id) as session:
        await publish.approve(session, p, [first.id])
    async with tenant_session(org.id) as session:
        # Simulate a draft created before the approval (same base as `first`).
        late = await publish.save_draft(
            session,
            organization_id=org.id,
            path="support/contact-support.md",
            content=current.content.replace("9:00", "7:00"),
            validation={"ok": True, "errors": [], "warnings": []},
            generated_by="human:x",
            title="Contact",
            doc_type="Contact Info",
            audience="customer",
        )
        late.base_version_id = first_base
    async with tenant_session(org.id) as session:
        with pytest.raises(publish.PublishError, match="changed after this draft"):
            await publish.approve(session, p, [late.id])


async def test_injection_warnings_need_acknowledgement(client: httpx.AsyncClient, make_org) -> None:
    org = make_org("technova")
    async with tenant_session(org.id) as session:
        content = BUNDLE["support/smartair-x1-faq.md"]
        validation = publish.validate_content("support/smartair-x1-faq.md", content)
        validation["warnings"].append(
            {
                "level": "warning",
                "path": "x",
                "message": "Possible prompt injection in the SOURCE (hidden_text): ...",
            }
        )
        version = await publish.save_draft(
            session,
            organization_id=org.id,
            path="support/smartair-x1-faq.md",
            content=content,
            validation=validation,
            generated_by="csp-ingestor/x",
            title="FAQ",
            doc_type="FAQ",
            audience="customer",
        )
    headers = await _auth(client, org.users["org_admin"])
    body = {"version_ids": [str(version.id)]}
    refused = await client.post("/api/v1/knowledge/versions/approve", headers=headers, json=body)
    assert refused.status_code == 409 and "prompt-injection" in refused.json()["detail"]
    ok = await client.post(
        "/api/v1/knowledge/versions/approve",
        headers=headers,
        json={**body, "acknowledge_warnings": True},
    )
    assert ok.status_code == 200


async def test_archive_removes_from_git_and_search(client: httpx.AsyncClient, make_org) -> None:
    org = make_org("technova")
    await _publish_fixture_bundle(org)
    headers = await _auth(client, org.users["org_admin"])
    doc = next(
        d
        for d in (await client.get("/api/v1/knowledge/documents")).json()
        if d["path"] == "support/contact-support.md"
    )
    assert (
        await client.delete(f"/api/v1/knowledge/documents/{doc['id']}", headers=headers)
    ).status_code == 204
    files = KnowledgeRepo(org.id).read_all()
    assert "support/contact-support.md" not in files
    assert "contact-support" not in files["support/index.md"]
    assert validate_bundle(files).ok
    hits = (
        await client.get("/api/v1/knowledge/search", params={"q": "support phone number"})
    ).json()["hits"]
    assert all(h["path"] != "support/contact-support.md" for h in hits)


async def test_other_organization_sees_nothing(client: httpx.AsyncClient, make_org) -> None:
    alpha = make_org("alpha")
    bravo = make_org("bravo")
    await _publish_fixture_bundle(alpha)
    await _generate_drafts(alpha)
    await _auth(client, bravo.users["org_admin"])
    assert (await client.get("/api/v1/knowledge/documents")).json() == []
    assert (await client.get("/api/v1/knowledge/reviews")).json() == []
    assert (await client.get("/api/v1/knowledge/search", params={"q": "warranty"})).json()[
        "hits"
    ] == []
    assert KnowledgeRepo(bravo.id).head_sha() is None


# ---------------------------------------------------------------- search quality (exit test)
async def test_search_recall_at_5_on_twenty_customer_questions(make_org) -> None:
    org = make_org("technova")
    await _publish_fixture_bundle(org)
    misses = []
    async with tenant_session(org.id) as session:
        for question, expected in SEARCH_CASES:
            hits = await search_sections(session, question, limit=10)
            top_docs = list(dict.fromkeys(h.path for h in hits))[:5]
            if not expected & set(top_docs):
                misses.append((question, top_docs))
    recall = 1 - len(misses) / len(SEARCH_CASES)
    print(f"\nrecall@5 = {recall:.0%}; misses: {misses}")
    assert recall >= 0.9, misses


async def test_internal_documents_are_hidden_from_customer_search(make_org) -> None:
    org = make_org("technova")
    await _publish_fixture_bundle(org)
    from datetime import UTC, datetime

    from app.knowledge.generation import SourceInfo, render_source_mirror
    from app.knowledge.quotes import SourcePages

    info = SourceInfo(
        id="s",
        name="SmartAir_X1_User_Manual.pdf",
        slug="smartair-x1-user-manual",
        uri=None,
        sha256="b" * 64,
        created_at=datetime.now(UTC),
    )
    body = MANUAL_MARKDOWN.split("\n\n", 1)[1]
    mirror = render_source_mirror(info, body, SourcePages.from_markdown(body), datetime.now(UTC))
    async with tenant_session(org.id) as session:
        version = await publish.save_draft(
            session,
            organization_id=org.id,
            path="sources/smartair-x1-user-manual.md",
            content=mirror,
            validation=publish.validate_content("sources/x.md", mirror),
            generated_by="process:csp-extractor",
            title=info.name,
            doc_type="Source Document",
            audience="internal",
        )
        await publish.approve(session, _principal(org), [version.id])
    async with tenant_session(org.id) as session:
        customer = await search_sections(session, "plastic wrapping filter cover")
        assert all(h.doc_type != "Source Document" for h in customer)
        staff = await search_sections(
            session, "plastic wrapping filter cover", include_internal=True, include_sources=True
        )
        mirror_hits = [h for h in staff if h.doc_type == "Source Document"]
        assert mirror_hits and mirror_hits[0].heading == "Page 6"
        assert mirror_hits[0].source_pages == [6]
