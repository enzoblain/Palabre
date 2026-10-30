"""Database engine, sessions and schema setup."""

from collections.abc import AsyncIterator

from sqlalchemy import Connection, inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

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
    # Create_all skips indexes of existing tables: add the DM uniqueness one (idempotent)
    from app.models import Room

    for index in Room.__table__.indexes:
        if index.name == "uq_rooms_dm_name":
            index.create(conn, checkfirst=True)
    # Conversations are never resumed: drop the rows stored before that (idempotent)
    conn.exec_driver_sql("DELETE FROM agent_sessions WHERE scope LIKE 'conversation:%'")
