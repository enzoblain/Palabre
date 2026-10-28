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
    """Create missing tables, and add the nullable columns added since a table was
    created (until Alembic migrations exist)."""
    Base.metadata.create_all(conn)
    existing = inspect(conn)
    for table in Base.metadata.sorted_tables:
        present = {c["name"] for c in existing.get_columns(table.name)}
        for column in table.columns:
            if column.name not in present and column.nullable:
                ddl_type = column.type.compile(dialect=conn.dialect)
                conn.exec_driver_sql(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {ddl_type}')
