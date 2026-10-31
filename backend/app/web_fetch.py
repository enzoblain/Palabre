"""Web page reader for the research groups: https GET run by the backend, never to a non-public address."""

import asyncio
import socket
from collections.abc import Iterable
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpcore

from app.config import settings
from app.egress_proxy import is_public_address
from app.errors import WorkflowError

HTTPS_PORT = 443
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "application/json", "text/xml", "application/xml")
SKIPPED_TAGS = {"script", "style", "noscript", "template", "svg", "head"}
BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "pre", "table"}
DEFAULT_CHARSET = "utf-8"
REQUEST_HEADERS = [
    (b"User-Agent", b"Palabre-research/1.0"),
    (b"Accept", b"text/html,text/plain;q=0.9,*/*;q=0.1"),
    (b"Accept-Encoding", b"identity"),  # httpcore does not decompress
]


class PublicOnlyBackend(httpcore.AsyncNetworkBackend):
    """Connects to resolved public addresses only: checked here, so a name cannot be rebound between check and use."""

    def __init__(self) -> None:
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[tuple[int, int, int | bytes]] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = [info[4][0] for info in infos]
        if not addresses or not all(is_public_address(a) for a in addresses):
            raise WorkflowError(f"{host} does not resolve to a public address")
        return await self._backend.connect_tcp(addresses[0], port, timeout, local_address, socket_options)

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skipped_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIPPED_TAGS:
            self._skipped_depth += 1
        elif tag in BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIPPED_TAGS:
            self._skipped_depth = max(0, self._skipped_depth - 1)
        elif tag in BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipped_depth:
            self._parts.append(data)

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self._parts).splitlines())
        return "\n".join(line for line in lines if line)


def extract_text(body: str, content_type: str) -> str:
    if not content_type.startswith(("text/html", "application/xhtml+xml")):
        return body.strip()
    extractor = _TextExtractor()
    extractor.feed(body)
    extractor.close()
    return extractor.text()


def validate_url(url: str) -> str:
    """The URL if it is a plain https one, else a WorkflowError."""
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or not parts.hostname:
        raise WorkflowError("Only https URLs can be fetched")
    if parts.username or parts.password:
        raise WorkflowError("URLs with credentials are refused")
    if (parts.port or HTTPS_PORT) != HTTPS_PORT:
        raise WorkflowError(f"Only port {HTTPS_PORT} can be fetched")
    return parts.geturl()


def _charset(content_type: str) -> str:
    for param in content_type.split(";")[1:]:
        key, _, value = param.strip().partition("=")
        if key.lower() == "charset" and value:
            return _known_charset(value.strip("\"'"))
    return DEFAULT_CHARSET


def _known_charset(name: str) -> str:
        b" ".decode(name, errors="replace")  # codecs.lookup also accepts non-text codecs such as hex or zlib
    try:
        b"".decode(name)  # codecs.lookup also accepts non-text codecs such as hex or zlib
    except LookupError:
        return DEFAULT_CHARSET
    return name


def _header(response: httpcore.Response, name: bytes) -> str:
    return next((v.decode("latin-1") for k, v in response.headers if k.lower() == name), "")


async def _read_limited(response: httpcore.Response) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_stream():
        body += chunk
        if len(body) > settings.fetch_max_bytes:
            return bytes(body[: settings.fetch_max_bytes])  # truncated: the text so far is still useful
    return bytes(body)


async def _get(pool: httpcore.AsyncConnectionPool, url: str) -> tuple[str, str]:
    """(content type, decoded body) of the page, following redirects one validated hop at a time."""
    for _ in range(settings.fetch_max_redirects + 1):
        url = validate_url(url)
        async with pool.stream("GET", url, headers=REQUEST_HEADERS) as response:
            if response.status in REDIRECT_STATUSES:
                url = urljoin(url, _header(response, b"location"))
                continue
            if response.status != 200:
                raise WorkflowError(f"The page answered HTTP {response.status}")
            content_type = _header(response, b"content-type").lower()
            if not content_type.startswith(TEXT_TYPES):
                raise WorkflowError(f"Unsupported content type: {content_type or 'unknown'}")
            raw = await _read_limited(response)
            return content_type, raw.decode(_charset(content_type), errors="replace")
    raise WorkflowError(f"More than {settings.fetch_max_redirects} redirects")


async def fetch_page(url: str) -> str:
    """Text of the page at `url`, cut to fetch_max_chars."""
    validate_url(url)
    try:
        async with httpcore.AsyncConnectionPool(network_backend=PublicOnlyBackend()) as pool:
            async with asyncio.timeout(settings.fetch_timeout_s):
                content_type, body = await _get(pool, url)
    except TimeoutError as exc:
        raise WorkflowError("The page took too long to answer") from exc
    except (httpcore.NetworkError, httpcore.TimeoutException, httpcore.ProtocolError, OSError) as exc:
        raise WorkflowError(f"The page could not be fetched: {exc}") from exc
    return extract_text(body, content_type)[: settings.fetch_max_chars]
