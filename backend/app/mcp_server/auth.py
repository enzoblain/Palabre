"""Identifies the employee behind each MCP request.

Every request carries headers written by the backend into the run's --mcp-config:
  - Authorization: Bearer <employee's MCP token>
  - X-Palabre-Conversation: <id>  for a conversation turn, or
  - X-Palabre-Task: <id>          for a task run (work on the employee's own task)
The agent therefore chooses neither who it is nor where it acts.
"""

from dataclasses import dataclass

from sqlalchemy import select
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.db import SessionLocal
from app.mcp_server.permissions import mcp_tools_for
from app.models import Conversation, Employee, Task, room_members


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

        scope.setdefault("state", {})["palabre_caller"] = caller
        await self.app(scope, receive, send)


async def resolve_caller(token: str, conversation_raw: str, task_raw: str) -> Caller | None:
    if not token:
        return None
    async with SessionLocal() as s:
        employee = await s.scalar(select(Employee).where(Employee.mcp_token == token))
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
