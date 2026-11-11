"""SSRF-hardened HTTP fetcher for URL ingestion.

SSRF ("server-side request forgery"): a user submits a URL, our server fetches
it, and the URL actually points *inside* our network: the cloud metadata service
(169.254.169.254), the database, localhost admin pages... This module makes that
impossible:

1. Only http/https, default ports, no `user:password@` in the URL.
2. We resolve DNS ourselves and reject the URL if ANY resolved address is not a
   public internet address (private, loopback, link-local, reserved, multicast,
   IPv4-mapped IPv6 tricks, ...).
3. We connect to the exact IP we validated (TLS still verifies the real
   hostname via SNI), so DNS can't change its answer between check and
   connection ("DNS rebinding").
4. Redirects are followed manually and every hop is validated again.
5. Size cap, overall timeout, allowed content types, and system proxy settings
   are ignored (`trust_env=False`).

OWASP reference: Server-Side Request Forgery Prevention Cheat Sheet.
"""

import asyncio
import ipaddress
import socket
import urllib.robotparser
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.core.config import get_settings

Resolver = Callable[[str, int], Awaitable[list[str]]]

HTML_TYPES = ("text/html", "application/xhtml+xml")
DOCUMENT_TYPES = (*HTML_TYPES, "application/pdf", "text/plain", "text/markdown")
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")
_REDIRECT_CODES = {301, 302, 303, 307, 308}


class FetchBlockedError(ValueError):
    """The URL is not allowed (security policy or bad input). Message is user-safe."""


class FetchError(Exception):
    """Temporary failure (network, 5xx). The job may be retried."""


@dataclass(frozen=True, slots=True)
class Target:
    scheme: str
    host: str  # IDNA-encoded, lowercase
    port: int
    path_query: str
    url: str


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str  # final URL after redirects
    content_type: str
    body: bytes


async def system_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def check_ip(value: str) -> None:
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0])  # drop IPv6 zone id
    except ValueError as exc:
        raise FetchBlockedError("The address could not be checked.") from exc
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped  # ::ffff:127.0.0.1 is really 127.0.0.1
    if not ip.is_global or ip.is_multicast:
        raise FetchBlockedError("This URL points to a private or internal network address.")


def parse_url(url: str) -> Target:
    url = url.strip()
    if len(url) > 2048:
        raise FetchBlockedError("The URL is too long.")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise FetchBlockedError("The URL is not valid.") from exc
    if parts.scheme not in {"http", "https"}:
        raise FetchBlockedError("Only http:// and https:// URLs are allowed.")
    if parts.username or parts.password:
        raise FetchBlockedError("URLs with a username or password are not allowed.")
    if not parts.hostname:
        raise FetchBlockedError("The URL has no host name.")
    default_port = 443 if parts.scheme == "https" else 80
    if port not in (None, default_port):
        raise FetchBlockedError("Only standard web ports (80 and 443) are allowed.")
    try:
        host = parts.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError as exc:
        raise FetchBlockedError("The host name is not valid.") from exc
    if host == "localhost" or host.endswith(_BLOCKED_SUFFIXES):
        raise FetchBlockedError("This URL points to a private or internal network address.")
    literal = host.strip("[]")
    try:
        ipaddress.ip_address(literal)
        is_ip_literal = True
    except ValueError:
        is_ip_literal = False
    if is_ip_literal:  # e.g. http://127.0.0.1/ or http://[::1]/: check right away
        check_ip(literal)
    path_query = parts.path or "/"
    if parts.query:
        path_query += f"?{parts.query}"
    clean = urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))
    return Target(parts.scheme, host, port or default_port, path_query, clean)


class SafeFetcher:
    def __init__(
        self,
        *,
        resolver: Resolver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        # Looked up at call time (not import time) so tests can substitute a fake DNS.
        self.resolver = resolver or (lambda host, port: system_resolver(host, port))
        self.transport = transport
        self.timeout = settings.fetch_timeout_seconds
        self.max_bytes = settings.fetch_max_mb * 1024 * 1024
        self.max_redirects = settings.fetch_max_redirects
        self.user_agent = settings.fetch_user_agent

    async def validated_ip(self, target: Target) -> str:
        try:
            ips = await self.resolver(target.host.strip("[]"), target.port)
        except OSError as exc:
            raise FetchBlockedError("The host name could not be found.") from exc
        if not ips:
            raise FetchBlockedError("The host name could not be found.")
        for ip in ips:  # ALL answers must be public: attackers mix public + private
            check_ip(ip)
        return ips[0]

    async def fetch(
        self,
        url: str,
        *,
        allowed_types: tuple[str, ...] = DOCUMENT_TYPES,
        max_bytes: int | None = None,
    ) -> FetchResult:
        limit = max_bytes or self.max_bytes
        try:
            async with asyncio.timeout(self.timeout):
                return await self._fetch(url, allowed_types, limit)
        except TimeoutError as exc:
            raise FetchError("The website took too long to respond.") from exc

    async def _fetch(self, url: str, allowed_types: tuple[str, ...], limit: int) -> FetchResult:
        current = url
        async with httpx.AsyncClient(
            transport=self.transport,
            follow_redirects=False,  # we validate every hop ourselves
            trust_env=False,  # ignore HTTP(S)_PROXY / netrc from the environment
            timeout=self.timeout,
        ) as client:
            for _ in range(self.max_redirects + 1):
                target = parse_url(current)
                ip = await self.validated_ip(target)
                host_ip = f"[{ip}]" if ":" in ip else ip
                default_port = 443 if target.scheme == "https" else 80
                host_header = (
                    target.host if target.port == default_port else f"{target.host}:{target.port}"
                )
                request_url = f"{target.scheme}://{host_ip}:{target.port}{target.path_query}"
                extensions = {"sni_hostname": target.host} if target.scheme == "https" else {}
                headers = {
                    "Host": host_header,
                    "User-Agent": self.user_agent,
                    "Accept": ", ".join(allowed_types),
                }
                try:
                    async with client.stream(
                        "GET", request_url, headers=headers, extensions=extensions
                    ) as response:
                        if response.status_code in _REDIRECT_CODES:
                            location = response.headers.get("location")
                            if not location:
                                raise FetchError("The website sent a redirect without a target.")
                            current = urljoin(target.url, location)
                            continue
                        if response.status_code >= 500:
                            raise FetchError(
                                f"The website returned an error ({response.status_code})."
                            )
                        if response.status_code >= 400:
                            raise FetchBlockedError(
                                f"The website refused the request ({response.status_code})."
                            )
                        content_type = (
                            response.headers.get("content-type", "").split(";")[0].strip().lower()
                        )
                        if content_type not in allowed_types:
                            raise FetchBlockedError(
                                f"Unsupported content type: {content_type or 'unknown'}."
                            )
                        declared = response.headers.get("content-length")
                        if declared and declared.isdigit() and int(declared) > limit:
                            raise FetchBlockedError("The page is too large.")
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > limit:
                                raise FetchBlockedError("The page is too large.")
                        return FetchResult(target.url, content_type, bytes(body))
                except httpx.HTTPError as exc:
                    raise FetchError(
                        f"Could not connect to the website: {type(exc).__name__}"
                    ) from exc
        raise FetchBlockedError("The website redirected too many times.")

    async def robots_allows(self, url: str) -> bool:
        """Respect robots.txt (RFC 9309): missing/4xx = allowed; 5xx/unreachable = disallowed."""
        target = parse_url(url)
        robots_url = f"{target.scheme}://{urlsplit(target.url).netloc}/robots.txt"
        try:
            result = await self.fetch(
                robots_url, allowed_types=("text/plain",), max_bytes=512 * 1024
            )
        except FetchBlockedError:
            return True  # 4xx, wrong content type, etc. -> no usable rules
        except FetchError:
            return False
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(result.body.decode("utf-8", "replace").splitlines())
        return parser.can_fetch(self.user_agent, url)
