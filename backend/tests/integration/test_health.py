import httpx


async def test_health_is_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "X-Request-ID" in response.headers


async def test_ready_checks_postgres_and_valkey(client: httpx.AsyncClient) -> None:
    response = await client.get("/ready")
    assert response.status_code == 200, response.text
    assert response.json()["checks"] == {"postgres": "ok", "valkey": "ok"}
