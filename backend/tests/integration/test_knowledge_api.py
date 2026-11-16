from pathlib import Path

import httpx
import pytest

from tests.conftest import login

SAMPLES = Path(__file__).resolve().parents[3] / "sample-data" / "technova"
PDF = (SAMPLES / "SmartAir_X1_User_Manual.pdf").read_bytes()
DOCX = (SAMPLES / "TechNova_Customer_Service_Policies.docx").read_bytes()


async def _auth(client: httpx.AsyncClient, user) -> dict[str, str]:  # type: ignore[no-untyped-def]
    csrf = (await login(client, user)).json()["csrf_token"]
    return {"X-CSRF-Token": csrf}


async def test_editor_uploads_multiple_files(client: httpx.AsyncClient, make_org) -> None:
    org = make_org("technova")
    headers = await _auth(client, org.users["editor"])
    response = await client.post(
        "/api/v1/knowledge/sources",
        headers=headers,
        files=[
            ("files", ("SmartAir_X1_User_Manual.pdf", PDF, "application/pdf")),
            ("files", ("policies.docx", DOCX, "application/octet-stream")),
            ("files", ("virus.pdf", b"MZ\x90\x00not a pdf\x00", "application/pdf")),
        ],
    )
    assert response.status_code == 201, response.text
    items = response.json()["items"]
    assert [i["status"] for i in items] == ["created", "created", "rejected"]
    assert items[0]["source"]["source_type"] == "pdf"
    assert items[0]["source"]["job"]["status"] == "queued"
    assert items[1]["source"]["source_type"] == "docx"  # detected from bytes, not MIME
    assert "Unsupported" in items[2]["error"]

    listed = (await client.get("/api/v1/knowledge/sources")).json()
    assert {s["name"] for s in listed} == {"SmartAir_X1_User_Manual.pdf", "policies.docx"}


async def test_same_file_twice_is_a_duplicate(client: httpx.AsyncClient, make_org) -> None:
    org = make_org("technova")
    headers = await _auth(client, org.users["editor"])
    files = [("files", ("manual.pdf", PDF, "application/pdf"))]
    first = await client.post("/api/v1/knowledge/sources", headers=headers, files=files)
    second = await client.post("/api/v1/knowledge/sources", headers=headers, files=files)
    assert first.json()["items"][0]["status"] == "created"
    dup = second.json()["items"][0]
    assert dup["status"] == "duplicate"
    assert dup["source"]["id"] == first.json()["items"][0]["source"]["id"]


@pytest.mark.parametrize("role", ["viewer", "agent"])
async def test_non_editors_cannot_upload(client: httpx.AsyncClient, make_org, role: str) -> None:
    org = make_org("technova")
    headers = await _auth(client, org.users[role])
    response = await client.post(
        "/api/v1/knowledge/sources",
        headers=headers,
        files=[("files", ("manual.pdf", PDF, "application/pdf"))],
    )
    assert response.status_code == 403
    assert (await client.get("/api/v1/knowledge/sources")).status_code == 200  # can view


@pytest.mark.parametrize(
    "url",
    ["http://169.254.169.254/latest/meta-data/", "http://localhost:8000/", "file:///etc/passwd"],
)
async def test_internal_urls_are_refused(client: httpx.AsyncClient, make_org, url: str) -> None:
    org = make_org("technova")
    headers = await _auth(client, org.users["editor"])
    response = await client.post(
        "/api/v1/knowledge/sources/url", headers=headers, json={"url": url}
    )
    assert response.status_code == 400


async def test_public_url_is_queued(client: httpx.AsyncClient, make_org, monkeypatch) -> None:
    async def fake_resolver(host: str, port: int) -> list[str]:
        return ["93.184.215.14"]

    monkeypatch.setattr("app.ingestion.safe_fetch.system_resolver", fake_resolver)
    org = make_org("technova")
    headers = await _auth(client, org.users["editor"])
    response = await client.post(
        "/api/v1/knowledge/sources/url",
        headers=headers,
        json={"url": "https://www.technova.example/smartair-x1/faq"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source_type"] == "url"
    assert body["job"]["status"] == "queued"


async def test_other_organization_cannot_see_source(client: httpx.AsyncClient, make_org) -> None:
    alpha = make_org("alpha")
    bravo = make_org("bravo")
    headers = await _auth(client, alpha.users["editor"])
    upload = await client.post(
        "/api/v1/knowledge/sources",
        headers=headers,
        files=[("files", ("manual.pdf", PDF, "application/pdf"))],
    )
    source_id = upload.json()["items"][0]["source"]["id"]

    await _auth(client, bravo.users["org_admin"])
    assert (await client.get(f"/api/v1/knowledge/sources/{source_id}")).status_code == 404
    assert (await client.get("/api/v1/knowledge/sources")).json() == []
    # Bravo can upload the SAME file: duplicates are per organization.
    headers_b = {"X-CSRF-Token": client.cookies.get("csp_csrf")}
    again = await client.post(
        "/api/v1/knowledge/sources",
        headers=headers_b,
        files=[("files", ("manual.pdf", PDF, "application/pdf"))],
    )
    assert again.json()["items"][0]["status"] == "created"


async def test_extracted_text_not_ready_yet(client: httpx.AsyncClient, make_org) -> None:
    org = make_org("technova")
    headers = await _auth(client, org.users["editor"])
    upload = await client.post(
        "/api/v1/knowledge/sources",
        headers=headers,
        files=[("files", ("manual.pdf", PDF, "application/pdf"))],
    )
    source_id = upload.json()["items"][0]["source"]["id"]
    response = await client.get(f"/api/v1/knowledge/sources/{source_id}/extracted")
    assert response.status_code == 409


async def test_delete_needs_publish_permission_and_allows_reupload(
    client: httpx.AsyncClient, make_org
) -> None:
    org = make_org("technova", roles=("org_admin", "agent"))
    headers = await _auth(client, org.users["org_admin"])
    files = [("files", ("manual.pdf", PDF, "application/pdf"))]
    source_id = (
        await client.post("/api/v1/knowledge/sources", headers=headers, files=files)
    ).json()["items"][0]["source"]["id"]

    agent_headers = await _auth(client, org.users["agent"])
    denied = await client.delete(f"/api/v1/knowledge/sources/{source_id}", headers=agent_headers)
    assert denied.status_code == 403

    headers = await _auth(client, org.users["org_admin"])
    deleted = await client.delete(f"/api/v1/knowledge/sources/{source_id}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/knowledge/sources/{source_id}")).status_code == 404
    reupload = await client.post("/api/v1/knowledge/sources", headers=headers, files=files)
    assert reupload.json()["items"][0]["status"] == "created"


async def test_retry_refused_while_job_active(client: httpx.AsyncClient, make_org) -> None:
    org = make_org("technova")
    headers = await _auth(client, org.users["editor"])
    upload = await client.post(
        "/api/v1/knowledge/sources",
        headers=headers,
        files=[("files", ("manual.pdf", PDF, "application/pdf"))],
    )
    source_id = upload.json()["items"][0]["source"]["id"]
    retry = await client.post(f"/api/v1/knowledge/sources/{source_id}/retry", headers=headers)
    assert retry.status_code == 409
