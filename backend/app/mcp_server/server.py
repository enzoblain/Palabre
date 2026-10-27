import functools
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, ListToolsResult, TextContent

from app.github import GitHubError
from app.mcp_server.auth import Caller
from app.services import WorkflowError

SERVER_NAME = "palabre"


def caller_of(request: Any) -> Caller:
    caller = getattr(getattr(request, "state", None), "palabre_caller", None)
    if caller is None:
        raise ToolError("Unauthenticated request")
    return caller


def current_caller(ctx: Context) -> Caller:
    return caller_of(ctx.request_context.request)


async def position_filter(ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
    """Only list, and only run, the tools of the caller's position."""
    if ctx.method not in ("tools/list", "tools/call"):
        return await call_next(ctx)
    allowed = caller_of(ctx.request).tools

    if ctx.method == "tools/call":
        name = (ctx.params or {}).get("name")
        if name not in allowed:
            return CallToolResult(
                content=[TextContent(type="text", text=f"'{name}' is not part of your position")],
                is_error=True,
            )
        return await call_next(ctx)

    result = await call_next(ctx)
    if isinstance(result, ListToolsResult):
        return result.model_copy(update={"tools": [t for t in result.tools if t.name in allowed]})
    if isinstance(result, dict):
        return {**result, "tools": [t for t in result["tools"] if t["name"] in allowed]}
    return result


mcp = MCPServer(SERVER_NAME, middleware=[position_filter])


def tool(fn: Callable[..., Awaitable[Any]]):
    """Register a tool; company rule violations reach the agent as readable errors
    (any other exception is hidden from the client by the SDK)."""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except (WorkflowError, GitHubError) as exc:
            raise ToolError(str(exc)) from exc

    return mcp.tool()(wrapper)
