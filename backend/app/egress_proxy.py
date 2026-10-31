"""Outbound proxy for the agents: an HTTP CONNECT tunnel that only reaches an allowlist of hosts."""

import asyncio
import ipaddress
import logging
import socket

from app.config import settings

log = logging.getLogger(__name__)

MAX_HEADER_BYTES = 16384
CONNECT_TIMEOUT_S = 15
RELAY_CHUNK_BYTES = 65536
_CRLF = b"\r\n"
_tunnels = asyncio.Semaphore(settings.egress_max_tunnels)


def parse_connect(request_line: str) -> tuple[str, int] | None:
    """(host, port) of a `CONNECT host:port HTTP/1.x` line, None for anything else."""
    parts = request_line.split()
    if len(parts) != 3 or parts[0].upper() != "CONNECT" or not parts[2].startswith("HTTP/1."):
        return None
    host, sep, port = parts[1].rpartition(":")
    if not sep or not host or not port.isdigit():
        return None
    return host.strip("[]").lower().rstrip("."), int(port)


def is_allowed(host: str, port: int) -> bool:
    return port in settings.egress_allowed_ports and host in settings.egress_allowed_hosts


def is_public_address(address: str) -> bool:
    return ipaddress.ip_address(address).is_global


async def _open(host: str, port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Connects to a resolved public address only: an allowed name must not lead to db, loopback or the LAN."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = [info[4][0] for info in infos]
    if not addresses or not all(is_public_address(a) for a in addresses):
        raise OSError(f"{host} does not resolve to a public address")
    return await asyncio.open_connection(addresses[0], port)


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(RELAY_CHUNK_BYTES):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()


async def _reply(writer: asyncio.StreamWriter, status: str) -> None:
    writer.write(f"HTTP/1.1 {status}\r\nConnection: close\r\n\r\n".encode())
    await writer.drain()


async def _tunnel(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, host: str, port: int) -> None:
    try:
        upstream_reader, upstream_writer = await asyncio.wait_for(_open(host, port), CONNECT_TIMEOUT_S)
    except (OSError, asyncio.TimeoutError):
        return await _reply(writer, "502 Bad Gateway")
    await _reply(writer, "200 Connection established")
    await asyncio.gather(_pipe(reader, upstream_writer), _pipe(upstream_reader, writer))


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        head = await asyncio.wait_for(reader.readuntil(_CRLF + _CRLF), CONNECT_TIMEOUT_S)
        target = parse_connect(head.split(_CRLF, 1)[0].decode("latin-1"))
        if target is None:
            return await _reply(writer, "405 Method Not Allowed")
        if not is_allowed(*target):
            log.warning("egress proxy: refused %s:%s", *target)
            return await _reply(writer, "403 Forbidden")
        if _tunnels.locked():
            return await _reply(writer, "503 Service Unavailable")
        async with _tunnels:
            await _tunnel(reader, writer, *target)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ConnectionError):
        pass
    finally:
        writer.close()


async def start() -> asyncio.Server:
    return await asyncio.start_server(handle, "127.0.0.1", settings.egress_proxy_port, limit=MAX_HEADER_BYTES)
