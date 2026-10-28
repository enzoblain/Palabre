from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _name_of(value: Any) -> Any:
    """Relationship to an employee → their name."""
    return getattr(value, "name", value)


class AppSettings(BaseModel):
    boss_name: str = Field(max_length=100)


class AppSettingsOut(AppSettings):
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


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    repo_url: str
    mode: str = "startup"
    default_branch: str = "main"
    seed: int | None = None
    # Employee first name → Claude account; the others are spread automatically
    accounts: dict[str, int] = {}


class ProjectOut(ORM):
    id: int
    name: str
    repo_url: str
    default_branch: str
    mode: str
    seed: int
    created_at: datetime


class RoomOut(ORM):
    id: int
    project_id: int
    name: str
    objective: str
    summary: str
    created_at: datetime
    members: list[EmployeeBrief]


class ProjectDetail(ProjectOut):
    employees: list[EmployeeOut]
    rooms: list[RoomOut]


class ModeChange(BaseModel):
    mode: str


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


# --- Notifications and runs --------------------------------------------------------


class NotificationOut(ORM):
    id: int
    project_id: int
    type: str
    payload: dict
    created_at: datetime
    read: bool


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
