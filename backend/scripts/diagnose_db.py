"""Production database diagnostic, to run once and paste the output back to the team (#266).

    docker compose exec backend python -m scripts.diagnose_db

Reads DATABASE_URL like the app does. Two parts:
1. conversation_throttled events of the last 24 h, per hour and per conversation (read only).
2. messages.request_status values outside the RequestStatus enum (read only), then
   _add_missing_checks (the only write: it adds the missing CHECK constraints, NOT VALID), then
   whether ck_messages_request_status exists.
"""

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import _add_missing_checks, engine
from app.models import REQUEST_STATUS_CHECK, RequestStatus


async def throttling(conn: AsyncConnection) -> None:
    print("== 1. conversation_throttled (last 24 h) ==")
    total = (await conn.execute(text("SELECT count(*) FROM events WHERE type = 'conversation_throttled'"))).scalar_one()
    rows = (
        await conn.execute(
            text(
                "SELECT date_trunc('hour', created_at AT TIME ZONE 'UTC') AS hour, project_id, payload->>'conversation_id' AS conv,"
                " count(*) AS n, max((payload->>'runs')::int) AS max_runs"
                " FROM events WHERE type = 'conversation_throttled' AND created_at > now() - interval '24 hours'"
                " GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"
            )
        )
    ).all()
    print(f"all time: {total}; last 24 h: {sum(r.n for r in rows)}")
    for r in rows:
        print(f"{r.hour:%Y-%m-%d %H}:00 UTC  project {r.project_id}  conversation {r.conv}  x{r.n}  runs={r.max_runs}")
    if not rows:
        print("none in the last 24 h")


async def check_state(conn: AsyncConnection):
    return (
        await conn.execute(
            text("SELECT convalidated FROM pg_constraint WHERE conname = :n AND contype = 'c'"), {"n": REQUEST_STATUS_CHECK}
        )
    ).first()


async def request_status(conn: AsyncConnection) -> None:
    print("\n== 2. request_status / CHECK constraint ==")
    valid = [s.value for s in RequestStatus]
    rows = (
        await conn.execute(
            text(
                "SELECT request_status, count(*) AS n, min(id) AS first_id, max(id) AS last_id FROM messages"
                " WHERE request_status IS NOT NULL AND request_status <> ALL(:valid) GROUP BY 1 ORDER BY 1"
            ),
            {"valid": valid},
        )
    ).all()
    if rows:
        print(f"{sum(r.n for r in rows)} message(s) outside the enum {valid}:")
        for r in rows:
            print(f"  {r.request_status!r}: {r.n} (ids {r.first_id}..{r.last_id})")
    else:
        print(f"no message outside the enum {valid}")
    existed = await check_state(conn) is not None
    await conn.run_sync(_add_missing_checks)
    print(f"{REQUEST_STATUS_CHECK}: {'already present' if existed else 'added'}")
    found = await check_state(conn)
    if found is None:
        print(f"{REQUEST_STATUS_CHECK}: MISSING")
    else:
        print(f"{REQUEST_STATUS_CHECK}: present ({'validated' if found[0] else 'NOT VALID: new writes checked, old rows not'})")


async def main() -> None:
    # One transaction, committed at the end: part 1 and the checks only read, _add_missing_checks may add constraints
    try:
        async with engine.begin() as conn:
            # Fail fast instead of queueing behind a long transaction, which would block every query on messages
            await conn.execute(text("SET LOCAL lock_timeout = '5s'"))
            await throttling(conn)
            await request_status(conn)
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) != "55P03":
            raise
        print("\nLock timeout: the messages table is busy (long transaction?). Nothing was changed, run it again later.")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
