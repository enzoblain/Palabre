"""Database engine, sessions and schema setup."""

import logging
from collections.abc import AsyncIterator

from sqlalchemy import CheckConstraint, Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)
RESEARCH_COLUMNS = ("kind", "topic", "research_phase")

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def upgrade_schema(conn: Connection) -> None:
    """Create missing tables, and add the columns added since a table was created:
    nullable ones, or ones with a text server default (until Alembic migrations exist)."""
    Base.metadata.create_all(conn)
    existing = inspect(conn)
    for table in Base.metadata.sorted_tables:
        present = {c["name"] for c in existing.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue
            ddl = f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {column.type.compile(dialect=conn.dialect)}'
            default = column.server_default.arg if column.server_default is not None else None
            if isinstance(default, str):
                conn.exec_driver_sql(ddl + " NOT NULL DEFAULT '" + default.replace("'", "''") + "'")
                if (table.name, column.name) == ("agent_sessions", "runs"):
                    # Existing sessions have an unknown size: forget them once, so none is resumed
                    conn.exec_driver_sql("DELETE FROM agent_sessions")
            elif column.nullable:
                conn.exec_driver_sql(ddl)
    _widen_request_status_check(conn)
    _add_missing_checks(conn)
    _drop_request_author_foreign_key(conn)
    _drop_research_projects(conn)
    # Conversations are never resumed: drop the rows stored before that (idempotent)
    conn.exec_driver_sql("DELETE FROM agent_sessions WHERE scope LIKE 'conversation:%'")


def _add_missing_checks(conn: Connection) -> None:
    """Add the CHECK constraints declared since a table was created (create_all leaves existing tables
    alone). SQLite cannot add one afterwards, and only PostgreSQL runs in production."""
    if conn.dialect.name != "postgresql":
        return
    have = {row[0] for row in conn.exec_driver_sql("SELECT conname FROM pg_constraint WHERE contype = 'c'")}
    for table in Base.metadata.sorted_tables:
        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint) and constraint.name not in have:
                # NOT VALID: new writes are checked, rows that predate the constraint cannot block startup
                conn.exec_driver_sql(
                    f'ALTER TABLE {table.name} ADD CONSTRAINT {constraint.name} CHECK ({constraint.sqltext}) NOT VALID'
                )


def _widen_request_status_check(conn: Connection) -> None:
    """The request status CHECK predates the "answered" status: replace it so the boss's replies can be stored
    (idempotent). _add_missing_checks then recreates it from the model. Only PostgreSQL has it in production."""
    if conn.dialect.name != "postgresql":
        return
    from app.models import REQUEST_STATUS_CHECK, RequestStatus  # models import this module

    definition = conn.execute(
        text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name"),
        {"name": REQUEST_STATUS_CHECK},
    ).scalar()
    if definition is not None and RequestStatus.answered.value not in definition:
        conn.exec_driver_sql(f"ALTER TABLE messages DROP CONSTRAINT {REQUEST_STATUS_CHECK}")


def _drop_request_author_foreign_key(conn: Connection) -> None:
    """messages.request_author_id was a foreign key with ON DELETE SET NULL, which erased who a relayed
    request was for when the member left the team: drop it (idempotent). Only PostgreSQL has it in production."""
    if conn.dialect.name != "postgresql":
        return
    for foreign_key in inspect(conn).get_foreign_keys("messages"):
        if foreign_key["constrained_columns"] == ["request_author_id"]:
            conn.exec_driver_sql(f'ALTER TABLE messages DROP CONSTRAINT "{foreign_key["name"]}"')


def _drop_research_projects(conn: Connection) -> None:
    """The research feature is gone: delete the research projects (their rooms, messages and
    employees go with them) and drop the columns that only served it (idempotent)."""
    present = {c["name"] for c in inspect(conn).get_columns("projects")}
    if "kind" in present:
        removed = conn.exec_driver_sql("DELETE FROM projects WHERE kind = 'research'").rowcount
        if removed:
            logger.info("Removed %d research project(s) with their data", removed)
    for column in RESEARCH_COLUMNS:
        if column in present:
            conn.exec_driver_sql(f'ALTER TABLE projects DROP COLUMN "{column}"')
