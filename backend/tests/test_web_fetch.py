import asyncio
from contextlib import asynccontextmanager

import httpcore
import pytest

from app import web_fetch
from app.config import settings
from app.errors import WorkflowError
from app.mcp_server.permissions import mcp_tools_for


async def chunked(body: bytes):
    for start in range(0, len(body), 4):
        yield body[start : start + 4]


class FakePool:
    """Answers each GET with the next scripted (status, headers, body) and records the URLs asked."""

    def __init__(self, *answers: tuple[int, dict[str, str], bytes]) -> None:
        self.answers = list(answers)
        self.urls: list[str] = []

    @asynccontextmanager
    async def stream(self, method: str, url: str, headers=None):
        assert method == "GET"
        self.urls.append(url)
        status, response_headers, body = self.answers.pop(0)

        yield httpcore.Response(
            status,
            headers=[(k.encode(), v.encode()) for k, v in response_headers.items()],
            content=chunked(body),
        )


HTML = {"Content-Type": "text/html; charset=utf-8"}


@pytest.mark.parametrize(
    "url",
    ["http://example.com/", "ftp://example.com/", "file:///etc/passwd", "https://user:pw@example.com/", "https://example.com:5432/", "example.com"],
)
def test_validate_url_refuses(url):
    with pytest.raises(WorkflowError):
        web_fetch.validate_url(url)


def test_validate_url_accepts_https():
    assert web_fetch.validate_url(" https://example.com/a?b=1 ") == "https://example.com/a?b=1"


def test_extract_text_drops_scripts_and_keeps_blocks():
    html = "<html><head><title>t</title></head><body><script>x()</script><h1>Title</h1><p>one   two</p><p>three</p></body></html>"
    assert web_fetch.extract_text(html, "text/html") == "Title\none two\nthree"


def test_extract_text_leaves_plain_text():
    assert web_fetch.extract_text(" a\n<b> \n", "text/plain") == "a\n<b>"


async def test_get_returns_decoded_body():
    pool = FakePool((200, HTML, "café".encode()))
    assert await web_fetch._get(pool, "https://example.com/") == ("text/html; charset=utf-8", "café")


async def test_get_follows_redirects_and_validates_each_hop():
    pool = FakePool((302, {"Location": "/next"}, b""), (200, HTML, b"ok"))
    await web_fetch._get(pool, "https://example.com/start")
    assert pool.urls == ["https://example.com/start", "https://example.com/next"]
    downgrade = FakePool((302, {"Location": "http://example.com/"}, b""))
    with pytest.raises(WorkflowError, match="https"):
        await web_fetch._get(downgrade, "https://example.com/")


async def test_get_stops_redirect_loops(monkeypatch):
    monkeypatch.setattr(settings, "fetch_max_redirects", 2)
    pool = FakePool(*[(302, {"Location": "/again"}, b"")] * 3)
    with pytest.raises(WorkflowError, match="redirects"):
        await web_fetch._get(pool, "https://example.com/")


@pytest.mark.parametrize("answer", [(404, HTML, b""), (200, {"Content-Type": "application/pdf"}, b"%PDF")])
async def test_get_refuses_errors_and_binary(answer):
    with pytest.raises(WorkflowError):
        await web_fetch._get(FakePool(answer), "https://example.com/")


async def test_get_caps_the_body_size(monkeypatch):
    monkeypatch.setattr(settings, "fetch_max_bytes", 10)
    _, body = await web_fetch._get(FakePool((200, HTML, b"x" * 100)), "https://example.com/")
    assert body == "x" * 10


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "10.0.0.5", "169.254.169.254", "::1"])
async def test_backend_refuses_non_public_addresses(host):
    with pytest.raises(WorkflowError, match="public"):
        await web_fetch.PublicOnlyBackend().connect_tcp(host, 443)


async def test_fetch_page_truncates_text(monkeypatch):
    async def fake_get(pool, url):
        return "text/plain", "x" * 50

    monkeypatch.setattr(web_fetch, "_get", fake_get)
    monkeypatch.setattr(settings, "fetch_max_chars", 5)
    assert await web_fetch.fetch_page("https://example.com/") == "xxxxx"


async def test_fetch_page_times_out(monkeypatch):
    async def slow_get(pool, url):
        await asyncio.sleep(5)

    monkeypatch.setattr(web_fetch, "_get", slow_get)
    monkeypatch.setattr(settings, "fetch_timeout_s", 0.05)
    with pytest.raises(WorkflowError, match="too long"):
        await web_fetch.fetch_page("https://example.com/")


def test_only_research_gets_fetch_page():
    assert "fetch_page" in mcp_tools_for(["conversation", "research"], False)
    for permissions in (["conversation"], ["conversation", "code", "request_review"], ["manage_tasks", "merge"]):
        assert "fetch_page" not in mcp_tools_for(permissions, True)
