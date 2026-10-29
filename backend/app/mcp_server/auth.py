"""Identifies the employee behind each MCP request.

Every request carries headers written by the backend into the run's --mcp-config:
  - Authorization: Bearer <token of this run, revoked when it ends>
  - X-Palabre-Conversation: <id>  for a conversation turn, or
  - X-Palabre-Task: <id>          for a task run (work on the employee's own task)
The agent therefore chooses neither who it is nor where it acts.
The scope (task or conversation) is also recorded server-side with the token when the run starts:
headers that do not match it are refused and logged, so they are never trusted on their own.

A token is also bound to the first MCP session that uses it (the Mcp-Session-Id of its initialize):
a run that stole another run's token from the process list cannot open a second session with it.
The legitimate run then fails visibly and the lead is told.
With MCP_SESSION_BINDING=warn (default) a second session is only logged and reported once, never refused:
this is not checked yet on a real `claude -p` run. Every initialize is logged, without the token.
"""

import logging

from dataclasses import dataclass

from sqlalchemy import select
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings
from app.db import SessionLocal
from app.mcp_server import run_tokens
from app.mcp_server.permissions import mcp_tools_for
from app.models import Conversation, Employee, Task, room_members
from app.services import direction_conversation_id, post_system_message

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

        session_id = headers.get("mcp-session-id", "")
        if not session_id:
            n = run_tokens.count_initialize(token)
            log.info(
                "MCP initialize: session #%d of the run of employee %s (conversation %s, task %s)",
                n, caller.employee_id, caller.conversation_id, caller.task_id,
            )  # fmt: skip
            if n == 2 and settings.mcp_session_binding == "warn":
                log.warning("MCP token of employee %s used on a second session: allowed (warn mode)", caller.employee_id)
                await alert_lead(caller, refused=False)
        if settings.mcp_session_binding != "enforce":
            await self._forward(scope, receive, send, caller, token, claimed=False)
            return

        claimed = False
        if session_id:
            allowed = run_tokens.session_allowed(token, session_id)
        else:
            allowed = claimed = run_tokens.claim_initialize(token)
        if not allowed:
            run_tokens.revoke(token)  # fail closed: both sessions die, later attempts get a 401 without alert
            await alert_lead(caller)
            await JSONResponse({"error": "token bound to another session"}, status_code=403)(scope, receive, send)
            return
        await self._forward(scope, receive, send, caller, token, claimed)

    async def _forward(
        self, scope: Scope, receive: Receive, send: Send, caller: Caller, token: str, claimed: bool
    ) -> None:
        async def send_bound(message: Message) -> None:
            if claimed and message["type"] == "http.response.start":
                sid = Headers(raw=message["headers"]).get("mcp-session-id")
                if sid:
                    run_tokens.bind_session(token, sid)
                else:
                    run_tokens.release_claim(token)
            await send(message)

        scope.setdefault("state", {})["palabre_caller"] = caller
        try:
            await self.app(scope, receive, send_bound if claimed else send)
        except BaseException:
            if claimed:
                run_tokens.release_claim(token)
            raise


async def alert_lead(caller: Caller, refused: bool = True) -> None:
    """Leave a system line in the direction channel (the refusal itself is logged by the caller in warn mode)."""
    if refused:
        log.warning("MCP token of employee %s used on a second session: refused", caller.employee_id)
    outcome = "refused" if refused else "allowed (MCP_SESSION_BINDING=warn)"
    async with SessionLocal() as s:
        conversation_id = await direction_conversation_id(s, caller.project_id)
        if conversation_id is not None:
            await post_system_message(
                s, conversation_id,
                f"Security: the MCP token of employee #{caller.employee_id} was used on a second "
                f"session: {outcome}. Another process may have read it, or claude reopened a session.",
            )  # fmt: skip
            await s.commit()


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
