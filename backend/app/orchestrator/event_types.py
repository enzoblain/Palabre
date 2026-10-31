"""The events that wake employees up, kept free of imports so the catalog loader can validate against them."""

from typing import Literal

# Events that can wake a role up (catalog `wakes_on`)
EventType = Literal[
    "objective_set", "escalation", "pr_approved", "daily", "mention", "technical_choice", "structural_pr",
    "pr_merged", "task_assigned", "changes_requested", "ci_failed", "task_done", "frontend_pr",
    "review_requested", "pr_ready", "before_merge", "milestone_end", "sensitive_pr", "dependency_change",
    "conversation_idle", "decision_changed", "research_start", "research_debate", "research_conclude",
]

# Events that make the assignee work on the task (task run) rather than talk
TASK_EVENTS = frozenset(
    {"task_assigned", "task_unblocked", "changes_requested", "pr_blocked", "task_retry", "task_resume", "task_nudge"}
)
