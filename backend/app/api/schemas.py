"""Pydantic models of the REST API."""

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.company.catalog import KEY_PATTERN, MAX_TEAM_SIZE, Category, Effort, ExtendedCategory, Model, Permission
from app.github import BRANCH_PATTERN
from app.models import RequestStatus


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


# --- Catalog -----------------------------------------------------------------------


class RoleToolsOut(BaseModel):
    mcp: list[str]
    claude: list[str]


class RoleOut(BaseModel):
    """A job of the catalog, with the tools its permissions give."""

    key: str
    title: str
    description: str
    category: Category | ExtendedCategory
    archetype: str | None = None
    order: int
    model: Model
    effort: Effort | None = None
    mission: str
    responsibilities: list[str]
    forbidden: list[str]
    deliverables: list[str]
    escalation: str
    success: str
    expertise: list[str] = []
    method: list[str] = []
    watch_points: list[str] = []
    deliverable_format: str | None = None
    permissions: list[Permission]
    wakes_on: list[str]
    tools: RoleToolsOut


class CatalogLimitsOut(BaseModel):
    models: list[str]
    max_agents: int
    min_team_size: int
    mandatory_role: str


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


class PresenceOut(BaseModel):
    employee_id: int
    name: str
    roles: list[str]
    # working: a run is open; idle: none. "Blocked" is deferred: not derived yet.
    state: Literal["working", "idle"]
    # Of the open run: "task" / "conversation" ... and what it is about
    kind: str | None
    task_id: int | None
    conversation_id: int | None
    # Start of the employee's latest run; None: never launched
    last_run_at: datetime | None


class EmployeeDetail(EmployeeOut):
    system_prompt: str


PERSONALITY_KEY_MAX_LENGTH = 40


class EmployeePatch(BaseModel):
    # New roles (not the lead's): title, permissions and, unless `model` is given, model follow them
    roles: list[str] | None = Field(default=None, min_length=1)
    # Key of a personality preset, applied before the explicit traits, quirks and style
    personality: str | None = Field(default=None, pattern=KEY_PATTERN, max_length=PERSONALITY_KEY_MAX_LENGTH)
    model: Literal["haiku", "sonnet", "opus"] | None = None
    traits: dict[str, int] | None = None
    quirks: list[str] | None = None
    style: dict[str, str] | None = None
    # Claude account (1, 2...); null: spread automatically
    account: int | None = Field(default=None, ge=1)


# --- Projects ----------------------------------------------------------------------


PROJECT_NAME_MAX_LENGTH = 200
PROJECTS_DELETE_MAX = 100


class MemberIn(BaseModel):
    """An agent of a team built by hand. Personality parts left out are drawn at random."""

    # One word: colleagues mention them with @Name
    name: str = Field(pattern=r"^[\w-]{1,40}$")
    roles: list[str] = Field(min_length=1)
    model: Literal["haiku", "sonnet", "opus"] | None = None
    traits: dict[str, int] | None = None
    quirks: list[Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(default=None, max_length=5)
    style: dict[str, str] | None = None
    # Key of a personality preset; traits, quirks and style given here override it
    personality: str | None = Field(default=None, pattern=KEY_PATTERN, max_length=PERSONALITY_KEY_MAX_LENGTH)
    account: int | None = Field(default=None, ge=1)


class EmployeeIn(BaseModel):
    """A member added to a running team. The name is drawn from the catalog when left out."""

    name: str | None = Field(default=None, pattern=r"^[\w-]{1,40}$")
    roles: list[str] = Field(min_length=1)
    model: Literal["haiku", "sonnet", "opus"] | None = None
    personality: str | None = Field(default=None, pattern=KEY_PATTERN, max_length=PERSONALITY_KEY_MAX_LENGTH)
    account: int | None = Field(default=None, ge=1)


class PersonalityPresetOut(BaseModel):
    """A named personality: the axes it leans on (the others are neutral), quirks and style."""

    key: str
    label: str
    description: str
    traits: dict[str, int]
    quirks: list[str]
    style: dict[str, str]


class RandomPersonalityOut(BaseModel):
    """A drawn personality, ready to be used as a member's traits, quirks and style."""

    traits: dict[str, int]
    quirks: list[str]
    style: dict[str, str]


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=PROJECT_NAME_MAX_LENGTH)
    # Mode (startup...). It sets the rules and, without `employees`, the seats
    mode: str = "startup"
    # The GitHub repository
    repo_url: str = ""
    seed: int | None = None
    # Employee first name → Claude account; the others are spread automatically
    accounts: dict[str, int] = {}
    # How a company team is made: "manual" (the `employees` list, the lead included) or "auto"
    # (`description` and `employee_count`); none: drawn for the mode, as before
    creation_mode: Literal["manual", "auto"] | None = None
    # Auto: what the project is about, and how many employees to hire (the lead included)
    description: str | None = Field(default=None, max_length=10000)
    employee_count: int | None = Field(default=None, le=MAX_TEAM_SIZE)
    # Team built by hand (instead of drawn at random for the mode)
    employees: list[MemberIn] | None = Field(default=None, min_length=1, max_length=MAX_TEAM_SIZE)


class ProjectOut(ORM):
    id: int
    name: str
    repo_url: str
    default_branch: str
    mode: str
    seed: int
    created_at: datetime


class LastMessageOut(BaseModel):
    content: str
    author: str
    created_at: datetime


class ProjectListItem(ProjectOut):
    # The team's messages in direction the boss has not read yet
    unread_count: int
    # The lead has an open run in direction: the front shows the "typing" dots
    lead_writing: bool
    # The latest message of direction, None when there is none
    last_message: LastMessageOut | None


class RoomOut(ORM):
    id: int
    project_id: int
    name: str
    kind: str
    objective: str
    summary: str
    created_at: datetime
    updated_at: datetime
    members: list[EmployeeBrief]


class ProjectDetail(ProjectOut):
    employees: list[EmployeeOut]
    rooms: list[RoomOut]


class ProjectPatch(BaseModel):
    """Editable infos of a project: its name and its main (production) branch, at least one of
    them. The description is generated and the repository is fixed."""

    name: str | None = Field(default=None, min_length=1, max_length=PROJECT_NAME_MAX_LENGTH)
    main_branch: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("name must not be blank")
        return value.strip()

    @field_validator("main_branch")
    @classmethod
    def _valid_main_branch(cls, value: str | None) -> str | None:
        if value is not None and not re.match(BRANCH_PATTERN, value):
            raise ValueError("not a valid branch name")
        return value

    @model_validator(mode="after")
    def _something_to_change(self) -> "ProjectPatch":
        if self.name is None and self.main_branch is None:
            raise ValueError("name or main_branch is required")
        return self


class ProjectUpdated(ProjectDetail):
    """The project after an edit, with a warning when the change deserves the boss's attention."""

    warning: str | None = None


class ProjectsDelete(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=PROJECTS_DELETE_MAX)


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
    request_status: RequestStatus | None = None
    request_comment: str | None = None
    request_answered_at: datetime | None = None
    request_merged_into: int | None = None
    request_decision_id: int | None = None
    request_author_id: int | None = None


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
    marked_sensitive: bool
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


class ExhaustedAccountOut(BaseModel):
    account: int
    resets_at: datetime
    estimated: bool


class OrchestratorStatus(BaseModel):
    enabled: bool
    running_employee_ids: list[int]
    pending_wakeups: int
    # Accounts out of Claude credits (the app shows a banner), with the expected return
    exhausted_accounts: list[ExhaustedAccountOut] = []


class SessionOut(BaseModel):
    """A session token and when it stops being accepted (Unix seconds)."""

    token: str
    expires_at: int
