"""SQLAlchemy models."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def created_at_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def updated_at_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


def str_enum(enum_cls: type[enum.Enum]) -> Enum:
    return Enum(enum_cls, native_enum=False, length=30)


class DecisionStatus(str, enum.Enum):
    proposed = "proposed"
    validated = "validated"
    rejected = "rejected"


class RequestAnswer(str, enum.Enum):
    """How a decision is settled (Decision.status, and the requests asking about it)."""

    validated = "validated"
    rejected = "rejected"


class RequestStatus(str, enum.Enum):
    """Where a request to the boss stands (Message.request_status): waiting, answered by the
    boss's next message (answered), settled with its decision (RequestAnswer values), or closed by the
    lead without an answer. nuanced is no longer produced: it only labels requests answered before the
    boss replied in free text."""

    pending = "pending"
    answered = "answered"
    validated = "validated"
    rejected = "rejected"
    nuanced = "nuanced"
    withdrawn = "withdrawn"
    merged = "merged"


REQUEST_STATUS_CHECK = "ck_messages_request_status"


class TaskKind(str, enum.Enum):
    feature = "feature"
    bug = "bug"


class TaskStatus(str, enum.Enum):
    todo = "todo"
    in_progress = "in_progress"
    review = "review"
    changes_requested = "changes_requested"
    done = "done"
    cancelled = "cancelled"


class Verdict(str, enum.Enum):
    approve = "approve"
    changes = "changes"
    comment = "comment"


room_members = Table(
    "room_members",
    Base.metadata,
    Column("room_id", ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True),
    Column("employee_id", ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True),
)


class AppSetting(Base):
    """Settings changed from the UI (e.g. the boss's name)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class ProjectPlatform(str, enum.Enum):
    """What the project's code is: `apple` is a Swift project built on the Mac builder (see docs/apple-mode.md)."""

    generic = "generic"
    apple = "apple"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    repo_url: Mapped[str] = mapped_column(String(500))
    default_branch: Mapped[str] = mapped_column(String(200), default="main")
    # Mode (catalog.toml) and the seed the team was drawn with
    mode: Mapped[str] = mapped_column(String(50))
    seed: Mapped[int] = mapped_column(BigInteger)
    platform: Mapped[ProjectPlatform] = mapped_column(
        str_enum(ProjectPlatform), default=ProjectPlatform.generic, server_default=ProjectPlatform.generic.value
    )
    # Release CI the lead was already told about: head SHA of the release PR, and of production
    # (main_ci_watch: a release was just merged, its CI on production is still to be announced)
    release_ci_sha: Mapped[str | None] = mapped_column(String(64))
    main_ci_sha: Mapped[str | None] = mapped_column(String(64))
    main_ci_watch: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Head SHA of the team's branch the lead was already told has unpublished changes
    release_reminded_sha: Mapped[str | None] = mapped_column(String(64))
    # Last direction message the boss has read (0 = none): the lead's messages after it are unread
    boss_read_message_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), default=0, server_default="0"
    )
    created_at: Mapped[datetime] = created_at_column()

    employees: Mapped[list[Employee]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Employee.id"
    )
    rooms: Mapped[list[Room]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Room.id"
    )


class Employee(Base):
    """An agent of the company, generated from the catalog (see company/team.py)."""

    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    roles: Mapped[list[str]] = mapped_column(JSON)
    title: Mapped[str] = mapped_column(String(300))
    model: Mapped[str] = mapped_column(String(50))
    permissions: Mapped[list[str]] = mapped_column(JSON)
    traits: Mapped[dict[str, int]] = mapped_column(JSON)
    quirks: Mapped[list[str]] = mapped_column(JSON)
    style: Mapped[dict[str, str]] = mapped_column(JSON)
    # Claude account it runs on (1, 2...), chosen by the boss; None: spread automatically
    account: Mapped[int | None]
    # Last fresh start of their conversation context (see orchestrator/context_reset.py); None: never
    context_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # MCP token; the backend needs it in clear text to write each run's --mcp-config.
    mcp_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = created_at_column()

    project: Mapped[Project] = relationship(back_populates="employees")


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    # "direction": only the boss and the lead, the one place the boss may write;
    # "team": the team's channels, which the boss does not see;
    # "dm": exactly 2 employees, named after them, one per pair
    kind: Mapped[str] = mapped_column(String(20), default="team", server_default="team")
    # Shared document: objective and summary (decisions, questions and tasks are rows)
    objective: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    project: Mapped[Project] = relationship(back_populates="rooms")
    members: Mapped[list[Employee]] = relationship(secondary=room_members, order_by="Employee.id")


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    rationale: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[DecisionStatus] = mapped_column(
        str_enum(DecisionStatus), default=DecisionStatus.proposed
    )
    proposed_by: Mapped[str] = mapped_column(String(100))
    # A release: the PR from the team's branch to production, merged when the boss validates
    pr_number: Mapped[int | None] = mapped_column(Integer)
    pr_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = created_at_column()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OpenQuestion(Base):
    __tablename__ = "open_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    asked_by: Mapped[str] = mapped_column(String(100))
    answer: Mapped[str | None] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at_column()


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    # Last message id the scribe was woken up for (conversation_idle)
    idle_notified_message_id: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = created_at_column()


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_id_id", "conversation_id", "id"),
        CheckConstraint(
            "request_status IN (" + ", ".join(f"'{s.value}'" for s in RequestStatus) + ")",
            name=REQUEST_STATUS_CHECK,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    # NULL = the boss. Not a foreign key: the id outlives a removed member, whose messages must not
    # read as the boss's
    employee_id: Mapped[int | None] = mapped_column(Integer)
    author_name: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)
    # Automatic line from the platform (employee_id is NULL too, but it is not the boss)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # A request to the boss ("decision", "release", "escalation", "question"); request_status is
    # "pending" until the boss's next message closes it ("answered", the comment is their reply),
    # or until the lead withdraws it (the comment is their reason) or merges it into another
    request_kind: Mapped[str | None] = mapped_column(String(20))
    request_status: Mapped[str | None] = mapped_column(String(20))
    request_comment: Mapped[str | None] = mapped_column(Text)
    request_answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The request that replaced this one (request_status "merged")
    request_merged_into: Mapped[int | None] = mapped_column(BigInteger().with_variant(Integer(), "sqlite"))
    # The member a request was relayed for (the message itself is signed by the lead); NULL = the lead's own.
    # Not a foreign key: the id must outlive the member, so their escalation stays out of the lead's reach
    request_author_id: Mapped[int | None] = mapped_column(Integer)
    # The decision (or release) the request is about
    request_decision_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at_column()


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"))
    # Conversation where progress and review updates are posted
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    kind: Mapped[TaskKind] = mapped_column(str_enum(TaskKind), default=TaskKind.feature)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    acceptance_criteria: Mapped[list[str]] = mapped_column(JSON, default=list)
    severity: Mapped[str | None] = mapped_column(String(20))
    # Touches auth, data, dependencies or secrets: requires a security approval when gated
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    # Set by the lead for a task that is risky by design: adds the security gate whatever the changed paths
    marked_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    status: Mapped[TaskStatus] = mapped_column(str_enum(TaskStatus), default=TaskStatus.todo)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    # NULL = created by the boss. Not a foreign key, like Message.employee_id
    created_by_id: Mapped[int | None] = mapped_column(Integer)
    depends_on: Mapped[list[int]] = mapped_column(JSON, default=list)
    # Who merged or cancelled it (NULL = the boss, or still open); counted for the context reset
    closed_by_id: Mapped[int | None] = mapped_column(Integer)
    # When it was merged or cancelled; the context reset counts on it, not on updated_at
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set by the orchestrator when the task run starts
    branch: Mapped[str | None] = mapped_column(String(300))
    worktree_path: Mapped[str | None] = mapped_column(String(500))
    pr_number: Mapped[int | None]
    pr_url: Mapped[str | None] = mapped_column(String(500))
    # English Conventional Commits title given at submission: the PR title and the squash commit's
    pr_title: Mapped[str | None] = mapped_column(String(200))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Incremented on each submission; only reviews of the current round count
    review_round: Mapped[int] = mapped_column(default=0)
    # Head SHA the current round was submitted with: a resubmission whose tree is that commit replayed
    # on the new base is a pure rebase and keeps the round and its approvals
    reviewed_head: Mapped[str | None] = mapped_column(String(64))
    # When the lead was told every merge rule is met, and when it was reminded (once); reset on submission
    merge_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lead_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Head SHA for which the dev was sent the PR back (conflict, no CI, red CI): once per SHA
    stuck_sha: Mapped[str | None] = mapped_column(String(64))
    # Head SHA ("none" before any PR) for which the lead got the idle-task alert: once per SHA
    idle_alert_sha: Mapped[str | None] = mapped_column(String(64))
    # Watchdog nudges sent to a dev who never started a todo or changes_requested task (reset on each wakeup)
    unstarted_nudges: Mapped[int] = mapped_column(default=0, server_default="0")
    # Times the dev was woken up again after a run that ended without submitting (reset on each wakeup by someone else)
    stalled_restarts: Mapped[int] = mapped_column(default=0, server_default="0")
    # Set when merge_task was refused because the CI was running: the lead is woken when it ends
    merge_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    assignee: Mapped[Employee | None] = relationship(foreign_keys=[assignee_id])


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    verdict: Mapped[Verdict] = mapped_column(str_enum(Verdict))
    round: Mapped[int]
    body: Mapped[str] = mapped_column(Text)
    head_sha: Mapped[str | None] = mapped_column(String(64), default=None)  # PR head the opinion was given on
    created_at: Mapped[datetime] = created_at_column()

    reviewer: Mapped[Employee] = relationship()


class Note(Base):
    """Personal notebook of an employee, kept across sessions."""

    __tablename__ = "notes"

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True
    )
    content: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = updated_at_column()


class Event(Base):
    """Something happened that should wake someone up; consumed by the orchestrator.

    Target: an employee (target_employee_id), every employee holding a role
    (target_role, "boss" for the user), or nobody in particular (broadcast).
    """

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_unprocessed", "processed_at", "id"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    target_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE")
    )
    target_role: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = created_at_column()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- Orchestration -----------------------------------------------------------------


class Wakeup(Base):
    """An event resolved to one employee: a run they still have to do.

    kind "conversation": a turn in `conversation_id`; kind "task": work on `task_id`.
    """

    __tablename__ = "wakeups"
    __table_args__ = (Index("ix_wakeups_pending", "started_at", "employee_id"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(50))
    kind: Mapped[str] = mapped_column(String(20))
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Throttled chatter waits in the queue until then instead of being lost
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentSession(Base):
    """Claude session of an employee for a task scope ("task:<id>"; conversations are never stored),
    reused with --resume. `runs` counts the runs this session served (see orchestrator/context_reset.py);
    `updated_at` is the end of the last one."""

    __tablename__ = "agent_sessions"

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True
    )
    scope: Mapped[str] = mapped_column(String(50), primary_key=True)
    claude_session_id: Mapped[str] = mapped_column(String(100))
    runs: Mapped[int] = mapped_column(Integer, server_default="1", default=1)
    updated_at: Mapped[datetime] = updated_at_column()


class AgentRun(Base):
    """One `claude -p` execution, for monitoring and rate limits."""

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = created_at_column()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ok: Mapped[bool | None]
    error: Mapped[str | None] = mapped_column(Text)
    claude_session_id: Mapped[str | None] = mapped_column(String(100))
    num_turns: Mapped[int | None]
    cost_usd: Mapped[float | None]
    # Usage reported by claude's JSON output; None when the run failed before reporting it
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cache_creation_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cache_read_tokens: Mapped[int | None] = mapped_column(BigInteger)
    # Claude account (from 1) the run was billed on, kept because the assignment can change
    account: Mapped[int | None]

    employee: Mapped[Employee] = relationship()


class AppleJobStatus(str, enum.Enum):
    """Where a build job of the Mac builder stands; `error` is an infra failure (timeout, lost Mac)."""

    queued = "queued"
    running = "running"
    passed = "passed"
    failed = "failed"
    error = "error"


class AppleHost(Base):
    """A Mac builder: only the SHA-256 of its bearer token is stored; revoking sets revoked_at (see apple.py)."""

    __tablename__ = "apple_hosts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class AppleEnrollmentCode(Base):
    """A one-time code a Mac exchanges for its first token: only its SHA-256 is stored (see apple.py)."""

    __tablename__ = "apple_enrollment_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class AppleJob(Base):
    """A build of a project's branch at one commit, queued for the Mac builder (see apple.py)."""

    __tablename__ = "apple_jobs"
    __table_args__ = (Index("ix_apple_jobs_status_id", "status", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    branch: Mapped[str] = mapped_column(String(300))
    commit_sha: Mapped[str] = mapped_column(String(40))
    # The task whose PR head this job builds (NULL for a job queued by hand)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), index=True, default=None)
    status: Mapped[AppleJobStatus] = mapped_column(str_enum(AppleJobStatus), default=AppleJobStatus.queued)
    host_id: Mapped[int | None] = mapped_column(ForeignKey("apple_hosts.id", ondelete="SET NULL"), default=None)
    # SHA-256 of the job token, cleared when the job ends in error (revoked); the token itself is never stored
    job_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, default=None)
    source_downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    summary: Mapped[str] = mapped_column(Text, default="")
    log_excerpt: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = created_at_column()
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class DeviceSession(Base):
    """A paired phone: only the HMAC of its token is stored; revoking deletes the row (see devices.py)."""

    __tablename__ = "device_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = created_at_column()
    last_used_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
