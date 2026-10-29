"""Pydantic models of the REST API."""

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.github import BRANCH_PATTERN


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _name_of(value: Any) -> Any:
    """Relationship to an employee → their name."""
    return getattr(value, "name", value)


class AppSettingsIn(BaseModel):
    # Fields left out are unchanged
    boss_name: str | None = Field(default=None, max_length=100)
    language: str | None = None


class AppSettingsOut(BaseModel):
    boss_name: str
    # Language the employees speak and write in (a key of `languages`)
    language: str
    languages: dict[str, str]
    # Claude accounts configured in CLAUDE_CODE_OAUTH_TOKENS
    claude_accounts: int


# --- Employees ---------------------------------------------------------------------


class EmployeeBrief(ORM):
    id: int
    name: str
    title: str


class EmployeeOut(EmployeeBrief):
    project_id: int
    roles: list[str]
    model: str
    permissions: list[str]
    traits: dict[str, int]
    quirks: list[str]
    style: dict[str, str]
    # Claude account chosen by the boss (None: spread automatically)
    account: int | None


class EmployeeDetail(EmployeeOut):
    system_prompt: str


class EmployeePatch(BaseModel):
    model: Literal["haiku", "sonnet", "opus"] | None = None
    traits: dict[str, int] | None = None
    quirks: list[str] | None = None
    style: dict[str, str] | None = None
    # Claude account (1, 2...); null: spread automatically
    account: int | None = Field(default=None, ge=1)


# --- Projects ----------------------------------------------------------------------


class MemberIn(BaseModel):
    """An agent of a team built by hand. Personality parts left out are drawn at random."""

    # One word: colleagues mention them with @Name
    name: str = Field(pattern=r"^[\w-]{1,40}$")
    roles: list[str] = Field(min_length=1)
    model: Literal["haiku", "sonnet", "opus"] | None = None
    traits: dict[str, int] | None = None
    quirks: list[Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(default=None, max_length=5)
    style: dict[str, str] | None = None
    account: int | None = Field(default=None, ge=1)


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Mode: company (startup...) or research (duo...). It sets the rules and, without
    # `employees`, the seats
    mode: str = "startup"
    # Company: the GitHub repository
    repo_url: str = ""
    # Research: what the group investigates (posted as your first message)
    topic: str | None = Field(default=None, max_length=10000)
    # Research: the peer who writes the report (a name); none: drawn at random
    rapporteur: str | None = None
    seed: int | None = None
    # Employee first name → Claude account; the others are spread automatically
    accounts: dict[str, int] = {}
    # Team built by hand (instead of drawn at random for the mode)
    employees: list[MemberIn] | None = Field(default=None, min_length=1, max_length=30)


class ProjectOut(ORM):
    id: int
    name: str
    kind: str
    topic: str | None
    # Research: research, debate, conclusion, report or done
    research_phase: str | None
    repo_url: str
    default_branch: str
    mode: str
    seed: int
    created_at: datetime


class RoomOut(ORM):
    id: int
    project_id: int
    name: str
    kind: str
    objective: str
    summary: str
    created_at: datetime
    members: list[EmployeeBrief]


class ProjectDetail(ProjectOut):
    employees: list[EmployeeOut]
    rooms: list[RoomOut]


class ModeChange(BaseModel):
    mode: str


class BranchChange(BaseModel):
    branch: str

    # Python's re, not pydantic's pattern: the pattern uses look-arounds
    @field_validator("branch")
    @classmethod
    def _valid_branch(cls, value: str) -> str:
        if not re.match(BRANCH_PATTERN, value):
            raise ValueError("not a valid branch name")
        return value


# --- Rooms and their document ------------------------------------------------------


class RoomIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    objective: str = ""
    # Default: the whole company
    member_ids: list[int] | None = None


class RoomPatch(BaseModel):
    name: str | None = None
    objective: str | None = None
    summary: str | None = None


class DecisionOut(ORM):
    id: int
    room_id: int
    title: str
    rationale: str
    status: str
    proposed_by: str
    pr_number: int | None = None
    pr_url: str | None = None
    created_at: datetime
    decided_at: datetime | None


class DecisionPatch(BaseModel):
    status: Literal["validated", "rejected"]


class QuestionIn(BaseModel):
    question: str = Field(min_length=1)


class QuestionOut(ORM):
    id: int
    room_id: int
    question: str
    asked_by: str
    answer: str | None
    resolved: bool
    created_at: datetime


class QuestionPatch(BaseModel):
    answer: str


# --- Conversations -----------------------------------------------------------------


class ConversationIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class ConversationOut(ORM):
    id: int
    room_id: int
    title: str
    created_at: datetime


class MessageIn(BaseModel):
    content: str = Field(min_length=1)


class MessageOut(ORM):
    id: int
    conversation_id: int
    employee_id: int | None
    author_name: str
    content: str
    created_at: datetime
    # Automatic line from the platform, not from the boss
    is_system: bool = False
    # Set when the message asks the boss something (see services.ask_boss)
    request_kind: str | None = None
    request_status: str | None = None
    request_comment: str | None = None
    request_answered_at: datetime | None = None
    request_decision_id: int | None = None


class RequestAnswerIn(BaseModel):
    answer: Literal["validated", "rejected", "nuanced"]
    comment: str = ""

    @model_validator(mode="after")
    def nuance_needs_a_comment(self):
        if self.answer == "nuanced" and not self.comment.strip():
            raise ValueError("A nuanced answer needs a comment")
        return self


# --- Tasks -------------------------------------------------------------------------


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    acceptance_criteria: list[str] = []
    assignee: str | None = None
    depends_on: list[int] = []
    # Where progress is posted; default: the room's latest conversation
    conversation_id: int | None = None


class TaskPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    acceptance_criteria: list[str] | None = None
    depends_on: list[int] | None = None
    status: Literal["todo", "cancelled"] | None = None
    assignee: str | None = None


class TaskOut(ORM):
    id: int
    project_id: int
    room_id: int
    conversation_id: int
    kind: str
    title: str
    status: str
    assignee: str | None
    severity: str | None
    sensitive: bool
    pr_url: str | None
    review_round: int
    created_at: datetime
    updated_at: datetime

    _assignee_name = field_validator("assignee", mode="before")(_name_of)


class ReviewOut(ORM):
    id: int
    reviewer: str
    verdict: str
    body: str
    round: int
    created_at: datetime

    _reviewer_name = field_validator("reviewer", mode="before")(_name_of)


class TaskDetail(TaskOut):
    description: str
    acceptance_criteria: list[str]
    depends_on: list[int]
    branch: str | None
    reviews: list[ReviewOut]


class MergeIn(BaseModel):
    # Merge even if the mode's rules (approvals, QA, security, CI...) are not met
    force: bool = False


# --- Runs ----------------------------------------------------------------------------


class RunOut(ORM):
    id: int
    employee_id: int
    employee: str
    kind: str
    conversation_id: int | None
    task_id: int | None
    reasons: list[str]
    started_at: datetime
    finished_at: datetime | None
    ok: bool | None
    error: str | None
    num_turns: int | None
    cost_usd: float | None

    _employee_name = field_validator("employee", mode="before")(_name_of)


class UsageTotals(BaseModel):
    """Sums over the runs that reported the data; the runs_without_* counters say how many did not."""

    runs: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    runs_without_tokens: int = 0
    runs_without_cost: int = 0


class UsageEntry(BaseModel):
    """One account, employee or project; id and name are None where unknown (account: runs before it was recorded)."""

    id: int | None
    name: str | None = None
    day: UsageTotals
    week: UsageTotals
    total: UsageTotals


class UsageOut(BaseModel):
    accounts: list[UsageEntry]
    employees: list[UsageEntry]
    projects: list[UsageEntry]
    day: UsageTotals
    week: UsageTotals
    total: UsageTotals


class EmployeeStatus(BaseModel):
    """working: a run is in progress; waiting: woken up, about to run; resting: nothing
    to do; offline: the orchestrator is disabled."""

    employee_id: int
    name: str
    title: str
    status: Literal["working", "waiting", "resting", "offline"]
    # Claude account the employee runs on
    account: int
    # What the current run is about
    kind: str | None = None
    conversation_id: int | None = None
    task_id: int | None = None
    since: datetime | None = None


class OrchestratorStatus(BaseModel):
    enabled: bool
    running_employee_ids: list[int]
    pending_wakeups: int


class UsageWindowOut(BaseModel):
    used_percent: float
    resets_at: datetime | None


class ModelUsageOut(UsageWindowOut):
    model: str


class AccountQuotaOut(BaseModel):
    """What /usage shows for one account; on error, `error` says why and the windows are empty."""

    account: int
    error: str | None = None
    session: UsageWindowOut | None = None
    week: UsageWindowOut | None = None
    models: list[ModelUsageOut] = []


class QuotaOut(BaseModel):
    accounts: list[AccountQuotaOut]
