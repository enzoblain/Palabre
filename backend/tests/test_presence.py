"""Presence: open run, finished run, employee never launched."""

from datetime import UTC, datetime
from types import SimpleNamespace

from app.presence import team_presence

T1 = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)


class Result:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows):
        self.rows, self.calls = rows, 0

    async def execute(self, _query):
        self.calls += 1
        return Result(self.rows)


def row(id, name, kind=None, task_id=None, conversation_id=None, started_at=None, last=None):
    return SimpleNamespace(
        id=id, name=name, roles=["dev"], kind=kind, task_id=task_id,
        conversation_id=conversation_id, started_at=started_at, last_run_at=last,
    )  # fmt: skip


async def test_open_finished_and_never_launched():
    s = FakeSession([
        row(1, "Ann", "task", task_id=7, started_at=T2, last=T2),
        row(2, "Bob", last=T1),
        row(3, "Cy"),
    ])  # fmt: skip
    ann, bob, cy = await team_presence(s, 1)
    assert s.calls == 1
    assert (ann["state"], ann["kind"], ann["task_id"], ann["last_run_at"]) == ("working", "task", 7, T2)
    assert (bob["state"], bob["kind"], bob["last_run_at"]) == ("idle", None, T1)
    assert (cy["state"], cy["last_run_at"]) == ("idle", None)


async def test_most_recent_open_run_wins():
    s = FakeSession([
        row(1, "Ann", "task", task_id=7, started_at=T1, last=T2),
        row(1, "Ann", "conversation", conversation_id=4, started_at=T2, last=T2),
    ])  # fmt: skip
    (ann,) = await team_presence(s, 1)
    assert (ann["kind"], ann["conversation_id"], ann["task_id"]) == ("conversation", 4, None)
