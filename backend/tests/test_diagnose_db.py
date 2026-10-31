"""Tests for the messages.request_author_id foreign key check of scripts.diagnose_db."""

from unittest.mock import AsyncMock, MagicMock

from scripts.diagnose_db import request_author_fk


def conn_returning(names: list[str]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = names
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=result)
    return conn


async def test_fk_absent(capsys):
    await request_author_fk(conn_returning([]))
    assert "FK request_author_id: absent (OK)" in capsys.readouterr().out


async def test_fk_present_shows_constraint_name(capsys):
    conn = conn_returning(["messages_request_author_id_fkey"])
    await request_author_fk(conn)
    assert "FK request_author_id: present (KO), constraint messages_request_author_id_fkey" in capsys.readouterr().out
    assert "SELECT" in str(conn.execute.await_args.args[0])
