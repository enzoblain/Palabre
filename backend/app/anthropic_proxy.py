"""Reverse proxy to the Anthropic API for the agents: adds the account's token and refuses unexpected server tools and remote content sources."""

import json
import logging

import httpx
from fastapi import APIRouter, Request, Response
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse, StreamingResponse

from app.config import settings
from app.mcp_server import run_tokens

log = logging.getLogger(__name__)

router = APIRouter()
# Credentials and hop-by-hop headers are never forwarded as the agent sent them
_DROPPED_REQUEST_HEADERS = {
    "host", "authorization", "x-api-key", "content-length", "connection", "accept-encoding", "transfer-encoding",
}  # fmt: skip
_DROPPED_RESPONSE_HEADERS = {"content-length", "content-encoding", "transfer-encoding", "connection"}
# A tool without a type, or "custom", runs client-side; anything else is run by Anthropic
_CLIENT_TOOL_TYPES = {None, "custom"}
# Request fields that make Anthropic reach other servers on the agent's behalf
_FORBIDDEN_FIELDS = ("mcp_servers",)
# Content sources Anthropic fetches itself (URL, uploaded file); base64 and text are sent inline
_REMOTE_SOURCE_TYPES = {"url", "file"}
# Keys whose content is data the model produced, not a content block of the request
_OPAQUE_KEYS = {"input"}
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=settings.anthropic_api_url, timeout=settings.anthropic_timeout_s)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def is_path_allowed(path: str) -> bool:
    return ".." not in path.split("/") and path in settings.anthropic_allowed_paths


def refused_server_tool(body: object) -> str | None:
    """Name of the first server tool or field the request declares that is not allowed, None if it is clean."""
    if not isinstance(body, dict):
        return None
    for field in _FORBIDDEN_FIELDS:
        if body.get(field):
            return field
    tools = body.get("tools")
    for tool in tools if isinstance(tools, list) else []:
        tool_type = tool.get("type") if isinstance(tool, dict) else None
        if tool_type in _CLIENT_TOOL_TYPES:
            continue
        if not isinstance(tool_type, str) or not tool_type.startswith(tuple(settings.anthropic_allowed_server_tools)):
            return str(tool_type)
    return None


def _find_remote_source(node: object) -> str | None:
    """Type of the first content source Anthropic would fetch itself, searched through nested blocks."""
    if isinstance(node, list):
        return next((found for item in node if (found := _find_remote_source(item))), None)
    if not isinstance(node, dict):
        return None
    source = node.get("source")
    if isinstance(source, dict) and source.get("type") in _REMOTE_SOURCE_TYPES:
        return source["type"]
    children = [value for key, value in node.items() if key not in _OPAQUE_KEYS]
    return _find_remote_source(children)


def refused_remote_source(body: object) -> str | None:
    """Source type of a remote content block in the messages or system prompt, None if the request is clean."""
    if not isinstance(body, dict):
        return None
    return _find_remote_source([body.get("messages"), body.get("system")])


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Refuse duplicated keys: parsers disagree on which value wins, so the checks could be bypassed."""
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate key")
    return dict(pairs)


def _bearer(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


def _refuse(status: int, message: str) -> JSONResponse:
    return JSONResponse({"type": "error", "error": {"type": "permission_error", "message": message}}, status_code=status)


def _forwarded_headers(request: Request, credential: str) -> dict[str, str]:
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROPPED_REQUEST_HEADERS}
    return headers | {"Authorization": f"Bearer {credential}"}


async def _forward(request: Request, path: str, body: bytes, credential: str) -> Response:
    upstream_request = _get_client().build_request(
        request.method, f"/{path}", params=request.query_params, headers=_forwarded_headers(request, credential), content=body
    )
    try:
        upstream = await _get_client().send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        log.warning("anthropic proxy: upstream error on %s: %s", path, type(exc).__name__)
        return _refuse(502, "Cannot reach the Anthropic API")
    headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _DROPPED_RESPONSE_HEADERS}
    return StreamingResponse(
        upstream.aiter_bytes(), status_code=upstream.status_code, headers=headers, background=BackgroundTask(upstream.aclose)
    )


@router.api_route("/anthropic/{path:path}", methods=["POST"])
async def proxy(path: str, request: Request) -> Response:
    credential = run_tokens.credential_of(_bearer(request))
    if credential is None:
        return _refuse(401, "Unknown or finished run")
    if not is_path_allowed(path):
        log.warning("anthropic proxy: refused path %s", path)
        return _refuse(403, "This API path is not available to agents")
    if request.headers.get("content-encoding"):
        return _refuse(415, "Encoded request bodies are not accepted")
    body = await request.body()
    if len(body) > settings.anthropic_max_body_bytes:
        return _refuse(413, "Request too large")
    if body:
        try:
            parsed = json.loads(body, object_pairs_hook=_reject_duplicate_keys)
        except ValueError:
            return _refuse(400, "The body is not valid JSON without duplicated keys")
        if (refused := refused_server_tool(parsed)) is not None:
            log.warning("anthropic proxy: refused server tool %s", refused)
            return _refuse(403, f"Server tool {refused!r} is not available to agents")
        if (remote_source := refused_remote_source(parsed)) is not None:
            log.warning("anthropic proxy: refused %s content source", remote_source)
            return _refuse(403, f"Content sources of type {remote_source!r} are not available to agents")
    return await _forward(request, path, body, credential)
