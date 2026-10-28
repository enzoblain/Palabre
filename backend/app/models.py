from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
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
    """How the boss answers a request of the lead (Message.request_status)."""

    validated = "validated"
    rejected = "rejected"
    nuanced = "nuanced"


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


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    repo_url: Mapped[str] = mapped_column(String(500))
    default_branch: Mapped[str] = mapped_column(String(200), default="main")
    # "company": a software company on a GitHub repository; "research": peers who
    # investigate `topic` (repo_url is then empty)
    kind: Mapped[str] = mapped_column(String(20), default="company", server_default="company")
    topic: Mapped[str | None] = mapped_column(Text)
    # Research: where the current question stands (orchestrator/research.py)
    research_phase: Mapped[str | None] = mapped_column(String(20))
    # Mode (catalog.toml) and the seed the team was drawn with
    mode: Mapped[str] = mapped_column(String(50))
    seed: Mapped[int] = mapped_column(BigInteger)
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
    # "team": the team's channels, which the boss reads but cannot write in
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
    __table_args__ = (Index("ix_messages_conversation_id_id", "conversation_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    # NULL = the boss
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    author_name: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)
    # Automatic line from the platform (employee_id is NULL too, but it is not the boss)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # A request to the boss ("decision", "release", "escalation", "question"), answered
    # once with validated / rejected / nuanced (+ comment); request_status is "pending" until then
    request_kind: Mapped[str | None] = mapped_column(String(20))
    request_status: Mapped[str | None] = mapped_column(String(20))
    request_comment: Mapped[str | None] = mapped_column(Text)
    request_answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    status: Mapped[TaskStatus] = mapped_column(str_enum(TaskStatus), default=TaskStatus.todo)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    # NULL = created by the boss
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    depends_on: Mapped[list[int]] = mapped_column(JSON, default=list)
    # Set by the orchestrator when the task run starts
    branch: Mapped[str | None] = mapped_column(String(300))
    worktree_path: Mapped[str | None] = mapped_column(String(500))
    pr_number: Mapped[int | None]
    pr_url: Mapped[str | None] = mapped_column(String(500))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Incremented on each submission; only reviews of the current round count
    review_round: Mapped[int] = mapped_column(default=0)
    # When the lead was told every merge rule is met, and when it was reminded (once); reset on submission
    merge_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lead_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class AgentSession(Base):
    """Claude session of an employee for a scope ("conversation:<id>" or "task:<id>"),
    reused with --resume."""

    __tablename__ = "agent_sessions"

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True
    )
    scope: Mapped[str] = mapped_column(String(50), primary_key=True)
    claude_session_id: Mapped[str] = mapped_column(String(100))
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
