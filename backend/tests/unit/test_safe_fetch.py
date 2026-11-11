"""SSRF protection tests. No real network: DNS and HTTP are faked."""

import httpx
import pytest

from app.ingestion.safe_fetch import (
    FetchBlockedError,
    SafeFetcher,
    check_ip,
    parse_url,
)

PUBLIC_IP = "93.184.215.14"


def fake_dns(mapping: dict[str, list[str]]):  # type: ignore[no-untyped-def]
    async def resolve(host: str, port: int) -> list[str]:
        if host not in mapping:
            raise OSError("NXDOMAIN")
        return mapping[host]

    return resolve


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://user:pass@example.com/",
        "http://example.com:22/",
        "http://example.com:8080/",
        "http://localhost/",
        "http://printer.local/",
        "http://db.internal/",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata service
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://0.0.0.0/",
        "http:///nohost",
    ],
)
def test_parse_url_blocks_dangerous_urls(url: str) -> None:
    with pytest.raises(FetchBlockedError):
        parse_url(url)


def test_parse_url_accepts_normal_urls() -> None:
    target = parse_url("https://Example.COM/docs/faq?lang=en#section")
    assert target.host == "example.com"
    assert target.port == 443
    assert target.path_query == "/docs/faq?lang=en"
    assert target.url == "https://Example.COM/docs/faq?lang=en"  # fragment dropped


@pytest.mark.parametrize(
    "ip", ["10.1.2.3", "172.16.0.1", "192.168.1.1", "127.0.0.1", "169.254.169.254",
           "100.64.0.1", "::1", "fe80::1", "fc00::1", "::ffff:10.0.0.1", "224.0.0.1"],
)  # fmt: skip
def test_check_ip_blocks_non_public(ip: str) -> None:
    with pytest.raises(FetchBlockedError):
        check_ip(ip)


def test_check_ip_allows_public() -> None:
    check_ip(PUBLIC_IP)
    check_ip("2606:4700:4700::1111")


async def test_dns_answer_pointing_inside_is_blocked() -> None:
    """A public-looking name that resolves to an internal address (DNS trick)."""
    fetcher = SafeFetcher(resolver=fake_dns({"evil.example": ["127.0.0.1"]}))
    with pytest.raises(FetchBlockedError, match="private"):
        await fetcher.fetch("http://evil.example/")


async def test_mixed_dns_answers_are_blocked() -> None:
    fetcher = SafeFetcher(resolver=fake_dns({"mixed.example": [PUBLIC_IP, "10.0.0.1"]}))
    with pytest.raises(FetchBlockedError):
        await fetcher.fetch("http://mixed.example/")


async def test_connects_to_validated_ip_with_original_host_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html>ok</html>")

    fetcher = SafeFetcher(
        resolver=fake_dns({"docs.example": [PUBLIC_IP]}), transport=httpx.MockTransport(handler)
    )
    result = await fetcher.fetch("https://docs.example/faq")
    assert result.body == b"<html>ok</html>"
    assert seen[0].url.host == PUBLIC_IP  # pinned: no second DNS lookup by httpx
    assert seen[0].headers["host"] == "docs.example"
    assert seen[0].extensions["sni_hostname"] == "docs.example"  # TLS still checks the name


async def test_redirect_to_internal_address_is_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})

    fetcher = SafeFetcher(
        resolver=fake_dns({"docs.example": [PUBLIC_IP]}), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(FetchBlockedError, match="private"):
        await fetcher.fetch("https://docs.example/")


async def test_redirect_to_name_resolving_inside_is_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(301, headers={"location": "https://sneaky.example/"})

    fetcher = SafeFetcher(
        resolver=fake_dns({"docs.example": [PUBLIC_IP], "sneaky.example": ["192.168.0.10"]}),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(FetchBlockedError):
        await fetcher.fetch("https://docs.example/")


async def test_redirect_loop_is_stopped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/again"})

    fetcher = SafeFetcher(
        resolver=fake_dns({"docs.example": [PUBLIC_IP]}), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(FetchBlockedError, match="too many"):
        await fetcher.fetch("https://docs.example/")


async def test_size_limit_and_content_type() -> None:
    big = httpx.MockTransport(
        lambda r: httpx.Response(200, headers={"content-type": "text/html"}, content=b"x" * 2048)
    )
    fetcher = SafeFetcher(resolver=fake_dns({"docs.example": [PUBLIC_IP]}), transport=big)
    with pytest.raises(FetchBlockedError, match="too large"):
        await fetcher.fetch("https://docs.example/", max_bytes=1024)

    exe = httpx.MockTransport(
        lambda r: httpx.Response(200, headers={"content-type": "application/x-msdownload"})
    )
    fetcher = SafeFetcher(resolver=fake_dns({"docs.example": [PUBLIC_IP]}), transport=exe)
    with pytest.raises(FetchBlockedError, match="content type"):
        await fetcher.fetch("https://docs.example/")


async def test_robots_txt_is_respected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                text="User-agent: *\nDisallow: /private/\n",
            )
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html></html>")

    fetcher = SafeFetcher(
        resolver=fake_dns({"docs.example": [PUBLIC_IP]}), transport=httpx.MockTransport(handler)
    )
    assert await fetcher.robots_allows("https://docs.example/faq")
    assert not await fetcher.robots_allows("https://docs.example/private/page")


async def test_missing_robots_txt_allows() -> None:
    fetcher = SafeFetcher(
        resolver=fake_dns({"docs.example": [PUBLIC_IP]}),
        transport=httpx.MockTransport(lambda r: httpx.Response(404)),
    )
    assert await fetcher.robots_allows("https://docs.example/faq")
