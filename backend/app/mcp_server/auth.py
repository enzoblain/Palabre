"""Identifies the employee behind each MCP request.

Every request carries headers written by the backend into the run's --mcp-config:
  - Authorization: Bearer <token of this run, revoked when it ends>
  - X-Palabre-Conversation: <id>  for a conversation turn, or
  - X-Palabre-Task: <id>          for a task run (work on the employee's own task)
The agent therefore chooses neither who it is nor where it acts.
The scope (task or conversation) is also recorded server-side with the token when the run starts:
headers that do not match it are refused and logged, so they are never trusted on their own.

The token itself lives only while its run does (revoked at the end). It is not bound to one MCP session:
claude legitimately reopens sessions during a run, so every initialize is only logged (without the token).
"""

import logging

from dataclasses import dataclass

from sqlalchemy import select
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.db import SessionLocal
from app.mcp_server import run_tokens
from app.mcp_server.permissions import mcp_tools_for
from app.models import Conversation, Employee, Task, room_members

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Caller:
    employee_id: int
    project_id: int
    room_id: int
    conversation_id: int
    task_id: int | None
    tools: frozenset[str]


class AgentAuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        auth = headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        caller = await resolve_caller(
            token, headers.get("x-palabre-conversation", ""), headers.get("x-palabre-task", "")
        )
        if caller is None:
            await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
            return

        if not headers.get("mcp-session-id"):
            n = run_tokens.count_initialize(token)
            log.info(
                "MCP initialize: session #%d of the run of employee %s (conversation %s, task %s)",
                n, caller.employee_id, caller.conversation_id, caller.task_id,
            )  # fmt: skip
        scope.setdefault("state", {})["palabre_caller"] = caller
        await self.app(scope, receive, send)


async def resolve_caller(token: str, conversation_raw: str, task_raw: str) -> Caller | None:
    employee_id = run_tokens.employee_of(token) if token else None
    if employee_id is None:
        return None
    if not run_tokens.scope_matches(token, conversation_raw, task_raw):
        scope_task, scope_conversation = run_tokens.scope_of(token)
        log.warning(
            "MCP request refused: headers (task %r, conversation %r) do not match the scope of the token of employee %s "
            "(task %s, conversation %s)",
            task_raw, conversation_raw, employee_id, scope_task, scope_conversation,
        )  # fmt: skip
        return None
    async with SessionLocal() as s:
        employee = await s.get(Employee, employee_id)
        if employee is None:
            return None

        if task_raw.isdigit():
            task = await s.get(Task, int(task_raw))
            if task is None or task.project_id != employee.project_id or task.assignee_id != employee.id:
                return None
            return Caller(
                employee.id, employee.project_id, task.room_id, task.conversation_id, task.id,
                mcp_tools_for(employee.permissions, task_run=True),
            )  # fmt: skip

        if conversation_raw.isdigit():
            conversation = await s.get(Conversation, int(conversation_raw))
            if conversation is None:
                return None
            is_member = await s.scalar(
                select(room_members.c.employee_id).where(
                    room_members.c.room_id == conversation.room_id,
                    room_members.c.employee_id == employee.id,
                )
            )
            if is_member is None:
                return None
            return Caller(
                employee.id, employee.project_id, conversation.room_id, conversation.id, None,
                mcp_tools_for(employee.permissions, task_run=False),
            )  # fmt: skip

    return None
