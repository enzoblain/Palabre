"""MCP tools per position: each role only gets its own tools, anything else is refused."""

from types import SimpleNamespace

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, ListToolsResult, Tool

from app.company.team import load_catalog
from app.mcp_server import auth, server
from app.mcp_server.auth import AgentAuthMiddleware, Caller
from app.mcp_server.permissions import MCP_TOOLS, TASK_ONLY_TOOLS, claude_tools_for, mcp_tools_for
from app.orchestrator.research import DRAFTS_GLOB

CONVERSATION_TOOLS = {name for name, perms in MCP_TOOLS.items() if perms == {"conversation"}}
SHIP_TOOLS = {"merge_release", "publish_version", "fix_release"}
MERGE_TOOLS = {"merge_task", "set_working_branch", "propose_release", "list_pull_requests", "close_pull_request"} | SHIP_TOOLS
MANAGE_TOOLS = {"create_task", "assign_task", "update_task"}
REVIEW_TOOLS = {"review_task"}


def tools_of(role: str, task_run: bool = False) -> frozenset[str]:
    return mcp_tools_for(load_catalog()["roles"][role]["permissions"], task_run)


# --- What each position gets ----------------------------------------------------------


def test_every_position_can_talk():
    for role, cfg in load_catalog()["roles"].items():
        assert CONVERSATION_TOOLS <= mcp_tools_for(cfg["permissions"], False), role


def test_lead_manages_tasks_and_merges():
    tools = tools_of("lead")
    assert MANAGE_TOOLS | MERGE_TOOLS | {"add_decision", "install_toolchain"} <= tools
    assert not tools & (REVIEW_TOOLS | {"report_bug", "start_task", "submit_for_review"})


@pytest.mark.parametrize("role", ["dev", "dev_backend", "dev_frontend"])
def test_developer_works_on_tasks_but_cannot_merge_or_manage(role):
    tools = tools_of(role, task_run=True)
    assert {"start_task", "report_progress", "submit_for_review"} <= tools
    assert not tools & (MERGE_TOOLS | MANAGE_TOOLS | REVIEW_TOOLS | {"report_bug", "get_diff", "install_toolchain"})


def test_reviewer_reads_diffs_and_reviews_only():
    tools = tools_of("reviewer")
    assert {"get_diff", "review_task"} <= tools
    assert not tools & (MERGE_TOOLS | MANAGE_TOOLS | {"start_task", "submit_for_review", "report_bug", "add_decision"})


def test_qa_reviews_and_reports_bugs_but_cannot_merge():
    tools = tools_of("qa")
    assert {"get_diff", "review_task", "report_bug"} <= tools
    assert not tools & (MERGE_TOOLS | MANAGE_TOOLS | {"submit_for_review"})


def test_security_audits_and_reports_bugs_but_cannot_merge():
    tools = tools_of("security")
    assert {"get_diff", "review_task", "report_bug", "add_decision"} <= tools
    assert not tools & (MERGE_TOOLS | MANAGE_TOOLS | {"submit_for_review"})


def test_only_the_lead_can_merge():
    for role, cfg in load_catalog()["roles"].items():
        has_merge = bool(MERGE_TOOLS & mcp_tools_for(cfg["permissions"], True))
        assert has_merge == (role == "lead"), role


def test_scribe_edits_the_room_document_only():
    tools = tools_of("scribe")
    assert {"update_summary", "resolve_question"} <= tools
    assert not tools & (MERGE_TOOLS | MANAGE_TOOLS | REVIEW_TOOLS | {"add_decision"})


def test_task_only_tools_need_a_task_run():
    for role in ("dev_backend", "devops"):
        assert not tools_of(role, task_run=False) & TASK_ONLY_TOOLS
        assert TASK_ONLY_TOOLS <= tools_of(role, task_run=True)


def test_task_run_does_not_grant_tools_beyond_permissions():
    assert not tools_of("reviewer", task_run=True) & TASK_ONLY_TOOLS


def test_unknown_permission_grants_nothing():
    assert mcp_tools_for(["nonsense"], task_run=True) == frozenset()
    assert mcp_tools_for([], task_run=True) == frozenset()


def test_every_mcp_tool_is_held_by_someone():
    held = {p for cfg in load_catalog()["roles"].values() for p in cfg["permissions"]}
    for name, required in MCP_TOOLS.items():
        assert required & held, name


def test_claude_tools_follow_permissions():
    assert "Edit" in claude_tools_for(["code"])
    assert "Bash" not in claude_tools_for(["read_code"])
    assert "Edit" not in claude_tools_for(["read_code", "review"])
    assert claude_tools_for(["conversation"]) == []


# --- Refusal at call time -------------------------------------------------------------


def caller_with(tools) -> Caller:
    return Caller(1, 1, 1, 1, None, frozenset(tools))


def request_ctx(method: str, caller: Caller | None, name: str | None = None) -> SimpleNamespace:
    state = SimpleNamespace(palabre_caller=caller) if caller else SimpleNamespace()
    return SimpleNamespace(method=method, params={"name": name} if name else {}, request=SimpleNamespace(state=state))


async def call_through_filter(role: str, name: str):
    reached = []

    async def call_next(_ctx):
        reached.append(name)
        return CallToolResult(content=[])

    result = await server.position_filter(
        request_ctx("tools/call", caller_with(tools_of(role)), name), call_next
    )
    return result, reached


async def test_unauthorized_tool_call_is_refused_cleanly():
    result, reached = await call_through_filter("reviewer", "merge_task")
    assert result.is_error
    assert "'merge_task' is not part of your position" in result.content[0].text
    assert reached == []  # the tool never ran


async def test_unknown_tool_call_is_refused():
    result, reached = await call_through_filter("lead", "drop_database")
    assert result.is_error and reached == []


@pytest.mark.parametrize(
    "role, name",
    [("dev_backend", "merge_task"), ("qa", "merge_task"), ("security", "assign_task"),
     ("reviewer", "report_bug"), ("lead", "review_task"), ("scribe", "create_task")],
)  # fmt: skip
async def test_forbidden_calls_by_role(role, name):
    result, reached = await call_through_filter(role, name)
    assert result.is_error and reached == []


async def test_authorized_tool_call_goes_through():
    result, reached = await call_through_filter("lead", "merge_task")
    assert not result.is_error
    assert reached == ["merge_task"]


async def test_non_tool_requests_are_not_filtered():
    async def call_next(_ctx):
        return "ok"

    ctx = request_ctx("resources/list", None)
    assert await server.position_filter(ctx, call_next) == "ok"


async def test_tool_listing_only_shows_own_tools():
    listed = [Tool(name=n, inputSchema={"type": "object"}) for n in MCP_TOOLS]

    async def call_next(_ctx):
        return ListToolsResult(tools=listed)

    result = await server.position_filter(request_ctx("tools/list", caller_with(tools_of("reviewer"))), call_next)
    assert {t.name for t in result.tools} == set(tools_of("reviewer"))


# --- The boss and anonymous callers ---------------------------------------------------


def test_boss_is_not_an_employee_role():
    # The boss talks through the app, never through MCP: no catalog position gives boss tools
    assert "boss" not in load_catalog()["roles"]


def test_request_without_caller_is_refused():
    with pytest.raises(ToolError, match="Unauthenticated"):
        server.caller_of(SimpleNamespace(state=SimpleNamespace()))


async def test_tool_call_without_caller_is_refused():
    async def call_next(_ctx):
        raise AssertionError("must not run")

    with pytest.raises(ToolError):
        await server.position_filter(request_ctx("tools/call", None, "merge_task"), call_next)


async def test_resolve_caller_refuses_empty_token():
    assert await auth.resolve_caller("", "1", "") is None


async def test_middleware_answers_401_without_token():
    sent = []

    async def app(scope, receive, send):
        raise AssertionError("must not reach the app")

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "headers": [], "method": "POST", "path": "/mcp"}
    await AgentAuthMiddleware(app)(scope, None, send)
    assert sent[0]["status"] == 401


async def test_middleware_passes_the_resolved_caller(monkeypatch):
    caller = caller_with({"read_messages"})

    async def resolve(token, conversation, task):
        assert (token, conversation, task) == ("secret", "7", "")
        return caller

    monkeypatch.setattr(auth, "resolve_caller", resolve)
    seen = {}

    async def app(scope, receive, send):
        seen["caller"] = scope["state"]["palabre_caller"]

    scope = {
        "type": "http",
        "headers": [(b"authorization", b"Bearer secret"), (b"x-palabre-conversation", b"7")],
    }
    await AgentAuthMiddleware(app)(scope, None, None)
    assert seen["caller"] is caller


def test_only_the_lead_can_create_channels():
    for role, cfg in load_catalog()["roles"].items():
        has_it = "create_channel" in mcp_tools_for(cfg["permissions"], False)
        assert has_it == (role == "lead"), role


def test_only_the_lead_can_ship_releases():
    for role, cfg in load_catalog()["roles"].items():
        has_it = SHIP_TOOLS <= mcp_tools_for(cfg["permissions"], True)
        assert has_it == (role == "lead"), role
    assert "propose_release" in tools_of("lead")


@pytest.mark.parametrize("role", ["dev_backend", "qa", "security", "devops", "architect", "reviewer"])
@pytest.mark.parametrize("name", sorted(SHIP_TOOLS))
async def test_others_cannot_ship_releases(role, name):
    result, reached = await call_through_filter(role, name)
    assert result.is_error and reached == []


def test_research_writes_only_in_drafts_folder():
    tools = claude_tools_for(["research"])
    assert f"Write({DRAFTS_GLOB})" in tools
    assert f"Edit({DRAFTS_GLOB})" in tools
    assert "Write" not in tools and "Edit" not in tools
