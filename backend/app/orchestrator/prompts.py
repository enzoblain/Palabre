"""What agents are told when they are woken up."""

from collections import defaultdict

from app.models import Task

# Why an employee is woken up, per event type ({...} = event payload fields)
REASONS: dict[str, str] = {
    "mention": "You were mentioned in the conversation (message #{message_id}). Read the new messages and answer if it is useful.",
    "task_assigned": "You have been assigned task #{task_id}.",
    "task_unblocked": "Task #{task_id}, assigned to you, is no longer waiting for other tasks.",
    "changes_requested": "{reviewer} requested changes on task #{task_id}. Read the reviews with get_task and address them.",
    "review_requested": "Task #{task_id} is waiting for review ({pr_url}). Read it with get_task and get_diff, then give your verdict with review_task.",
    "pr_ready": "Task #{task_id} is ready for QA ({pr_url}). Check it against its acceptance criteria (get_task, get_diff) and give your verdict with review_task. File each bug with report_bug.",
    "sensitive_pr": "Task #{task_id} touches sensitive code ({pr_url}). Audit it (get_task, get_diff) and give your verdict with review_task.",
    "pr_approved": "Task #{task_id} was approved by {reviewer}. If every merge rule is met, merge it with merge_task.",
    "pr_merged": "Task #{task_id} was merged ({pr_url}). Do what your position requires after a merge, if anything.",
    "bug_reported": "A {severity} bug was reported as task #{task_id}. Triage it: assign it with assign_task, or cancel it with update_task.",
    "escalation": "{from} escalated something to you (message #{message_id}). Read it and decide.",
    "boss_message": "The boss posted in the conversation (message #{message_id}). Read it and react according to your position.",
    "objective_set": "The boss set the objective of this room. Read it with get_room_context and act according to your position.",
    "decision_changed": "The boss {status} decision #{decision_id}. Take it into account.",
    "daily": "It is time for the daily stand-up. Do your part of it according to your position.",
    "review_rounds_exceeded": "Task #{task_id} went through {rounds} rounds of requested changes without converging. Step in: decide, reassign it, or split it.",
    "conversation_throttled": "The team posted too much in conversation #{conversation_id} within an hour; agents are paused there until you step in.",
    "conversation_idle": "The conversation has gone quiet. Update the room document (summary, open questions) with what was said and decided.",
}


def reason_for(event_type: str, payload: dict) -> str:
    template = REASONS.get(event_type, "Event '{_type}': {_payload}. Act according to your position if it concerns you.")
    return template.format_map(defaultdict(lambda: "?", payload, _type=event_type, _payload=payload))


OPERATING_RULES = """## How Palabre works
- You only communicate through the "palabre" MCP tools. Anything you write outside send_message or report_progress is seen by nobody.
- You are woken up when something concerns you. Do what your position requires, then stop.
- Keep messages short and useful. Do not post only to agree, to thank, or to say you have nothing to add.
- Mention a colleague with @Name only when you need them: it wakes them up.
- Your notebook (read_notes / write_notes) is how you remember things from one session to the next."""

TASK_RULES = """## Your current task
You are working on task #{task_id} « {title} », in its own git worktree (your current directory), on branch `{branch}`.
- Start with get_task to read the description and acceptance criteria.
- Stay within the task. Run the tests before submitting.
- Commit your work with clear messages (`git commit`). Never push: submit_for_review pushes and opens the pull request.
- Post short progress updates with report_progress. If you are blocked, say so, or escalate.
- When the work is done and committed, call submit_for_review."""


def task_rules(task: Task) -> str:
    return TASK_RULES.format(task_id=task.id, title=task.title, branch=task.branch)


def wake_prompt(reasons: list[str]) -> str:
    lines = "\n".join(f"- {r}" for r in dict.fromkeys(reasons))
    return f"You are being woken up because:\n{lines}"
