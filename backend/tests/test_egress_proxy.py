import asyncio

import pytest

from app import egress_proxy
from app.config import settings


def test_parse_connect():
    assert egress_proxy.parse_connect("CONNECT API.anthropic.com.:443 HTTP/1.1") == ("api.anthropic.com", 443)
    assert egress_proxy.parse_connect("CONNECT [::1]:443 HTTP/1.1") == ("::1", 443)
    assert egress_proxy.parse_connect("GET http://example.com/ HTTP/1.1") is None
    assert egress_proxy.parse_connect("CONNECT example.com HTTP/1.1") is None


def test_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "egress_allowed_hosts", ["pypi.org"])
    assert egress_proxy.is_allowed("pypi.org", 443)
    assert not egress_proxy.is_allowed("pypi.org", 5432)
    assert not egress_proxy.is_allowed("example.com", 443)
    assert not egress_proxy.is_allowed("db", 443)


class FakeWriter:
    def __init__(self) -> None:
        self.data = b""

    def write(self, data: bytes) -> None:
        self.data += data

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        pass


async def _ask(line: str) -> bytes:
    reader = asyncio.StreamReader()
    reader.feed_data(f"{line}\r\n\r\n".encode())
    writer = FakeWriter()
    await egress_proxy.handle(reader, writer)  # type: ignore[arg-type]
    return writer.data


async def test_refuses_unlisted_host():
    assert (await _ask("CONNECT example.com:443 HTTP/1.1")).startswith(b"HTTP/1.1 403")


async def test_refuses_plain_requests():
    assert (await _ask("GET http://pypi.org/ HTTP/1.1")).startswith(b"HTTP/1.1 405")


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "::1"])
async def test_allowed_name_never_reaches_a_private_address(monkeypatch, address):
    async def resolve(self, host, port, **kwargs):
        return [(0, 0, 0, "", (address, port))]

    monkeypatch.setattr(settings, "egress_allowed_hosts", ["pypi.org"])
    monkeypatch.setattr(asyncio.get_running_loop().__class__, "getaddrinfo", resolve)
    assert (await _ask("CONNECT pypi.org:443 HTTP/1.1")).startswith(b"HTTP/1.1 502")


async def test_refuses_tunnels_beyond_the_cap(monkeypatch):
    monkeypatch.setattr(settings, "egress_allowed_hosts", ["pypi.org"])
    monkeypatch.setattr(egress_proxy, "_tunnels", asyncio.Semaphore(0))
    assert (await _ask("CONNECT pypi.org:443 HTTP/1.1")).startswith(b"HTTP/1.1 503")
