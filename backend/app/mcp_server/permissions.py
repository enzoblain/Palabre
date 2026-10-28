"""Which tools each catalog permission (catalog.toml → roles.*.permissions) unlocks."""

# MCP tools of this server. A tool is available if the employee holds any listed permission.
MCP_TOOLS: dict[str, set[str]] = {
    "read_messages": {"conversation"},
    "send_message": {"conversation"},
    "get_room_context": {"conversation"},
    "list_tasks": {"conversation"},
    "get_task": {"conversation"},
    "add_question": {"conversation"},
    "escalate": {"conversation"},
    "read_notes": {"conversation"},
    "write_notes": {"conversation"},
    "add_decision": {"propose_decision"},
    "create_task": {"manage_tasks"},
    "assign_task": {"manage_tasks"},
    "update_task": {"manage_tasks"},
    "start_task": {"request_review"},
    "report_progress": {"request_review"},
    "submit_for_review": {"request_review"},
    "get_diff": {"review", "read_code"},
    "review_task": {"review"},
    "report_bug": {"report_bug"},
    "update_summary": {"edit_room_document"},
    "resolve_question": {"edit_room_document"},
    "merge_task": {"merge"},
    "set_working_branch": {"merge"},
    "propose_release": {"merge"},
    "create_channel": {"manage_channels"},
    "ask_ceo": {"manage_channels"},  # the lead, who alone talks to the boss
    "install_toolchain": {"manage_toolchains"},
}

# Only exposed during a task run (X-Palabre-Task header), on the caller's own task
TASK_ONLY_TOOLS = {"report_progress", "submit_for_review"}

# Claude Code built-in tools, for `claude -p --allowedTools` (set by the runner)
CLAUDE_TOOLS: dict[str, list[str]] = {
    "code": ["Read", "Grep", "Glob", "Edit", "Write", "Bash"],
    "run_tests": ["Read", "Grep", "Glob", "Bash"],
    "read_code": ["Read", "Grep", "Glob"],
    "edit_docs": ["Read", "Grep", "Glob", "Edit(**/*.md)", "Write(**/*.md)"],
    # Research groups: the web, and drafts in their own folder
    "research": ["WebSearch", "WebFetch", "Read", "Grep", "Glob", "Write", "Edit"],
}


def mcp_tools_for(permissions: list[str], task_run: bool) -> frozenset[str]:
    held = set(permissions)
    return frozenset(
        tool
        for tool, required in MCP_TOOLS.items()
        if held & required and (task_run or tool not in TASK_ONLY_TOOLS)
    )


def claude_tools_for(permissions: list[str]) -> list[str]:
    return sorted({tool for p in permissions for tool in CLAUDE_TOOLS.get(p, [])})
