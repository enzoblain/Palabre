"""Context reset every N finished tasks: counter, threshold, off at 0, what is kept."""

from types import SimpleNamespace

import pytest

from app.config import settings
from app import workflow
from app.orchestrator import context_reset


class FakeDb:
    """Counts the finished tasks it is told about; records deletions and commits."""

    def __init__(self, finished: int):
        self.finished, self.executed, self.commits = finished, [], 0

    async def scalar(self, _query):
        return self.finished

    async def execute(self, query):
        self.executed.append(str(query))

    async def commit(self):
        self.commits += 1


def employee():
    return SimpleNamespace(id=1, name="Malik", context_reset_at=None, created_at=None)


@pytest.fixture(autouse=True)
def every_five(monkeypatch):
    monkeypatch.setattr(settings, "context_reset_every_tasks", 5)


async def test_counter_is_read_from_the_database():
    assert await context_reset.finished_tasks_since_reset(FakeDb(3), employee()) == 3


async def test_below_threshold_nothing_happens():
    s, who = FakeDb(4), employee()
    assert not await context_reset.reset_context_if_due(s, who)
    assert s.executed == [] and who.context_reset_at is None


@pytest.mark.parametrize("finished", [5, 7])
async def test_at_threshold_sessions_are_deleted_and_counter_restarts(finished):
    s, who = FakeDb(finished), employee()
    assert await context_reset.reset_context_if_due(s, who)
    assert len(s.executed) == 1 and s.executed[0].startswith("DELETE FROM agent_sessions")
    assert who.context_reset_at is not None and s.commits == 1


async def test_only_agent_sessions_are_deleted():
    s = FakeDb(5)
    await context_reset.reset_context_if_due(s, employee())
    assert [q for q in s.executed if "notes" in q or "tasks" in q or "messages" in q] == []


async def test_zero_disables_the_reset(monkeypatch):
    monkeypatch.setattr(settings, "context_reset_every_tasks", 0)
    s, who = FakeDb(50), employee()
    assert not await context_reset.reset_context_if_due(s, who)
    assert s.executed == [] and who.context_reset_at is None


# --- Who counts: reviewers, QA, security and the lead -------------------------------------


class QueryDb(FakeDb):
    """Keeps the compiled counting query to check which tasks it matches."""

    async def scalar(self, query):
        self.sql = str(query.compile(compile_kwargs={"literal_binds": True}))
        return 0


async def counting_sql():
    s = QueryDb(0)
    await context_reset.finished_tasks_since_reset(s, employee())
    return s.sql


async def test_reviews_and_closing_count_next_to_the_assignment():
    sql = await counting_sql()
    assert "tasks.assignee_id = 1" in sql and "tasks.closed_by_id = 1" in sql
    # Reviewers, QA and security all review through `reviews`; EXISTS: one count per task
    assert "EXISTS" in sql and "reviews.reviewer_id = 1" in sql and "reviews.task_id = tasks.id" in sql
    assert "done" in sql and "cancelled" in sql


async def test_a_task_is_counted_once_per_person():
    sql = await counting_sql()
    assert "JOIN" not in sql and "count(*)" in sql.lower()


def lead_flow(monkeypatch):
    from tests.conftest import make_employee, make_task

    task = make_task(project_id=1, depends_on=[], title="T", conversation_id=1, pr_url=None, pr_title="feat: x", closed_by_id=None)
    lead = make_employee("Élise", "lead")

    async def get_task(*_):
        return task

    async def nothing(*_, **__):
        pass

    for name in ("clean_up_task", "announce", "merge_blockers"):
        monkeypatch.setattr(workflow, name, nothing)

    async def merge_pull_request(*_):
        pass

    monkeypatch.setattr(workflow, "get_task", get_task)
    monkeypatch.setattr(workflow.github, "merge_pull_request", merge_pull_request)
    return task, lead


class WorkflowDb(FakeDb):
    async def get(self, *_):
        from tests.conftest import make_project

        return make_project()

    async def scalars(self, _query):
        return []

    def add(self, _obj):
        pass

    async def flush(self):
        pass


async def test_the_lead_is_recorded_at_merge(monkeypatch):
    task, lead = lead_flow(monkeypatch)

    async def post_message(*_):
        pass

    monkeypatch.setattr(workflow, "post_message", post_message)
    await workflow.merge_task(WorkflowDb(0), 1, task.id, lead, force=True)
    assert task.closed_by_id == lead.id


async def test_the_boss_merging_is_recorded_as_nobody(monkeypatch):
    task, _ = lead_flow(monkeypatch)
    task.closed_by_id = 99
    await workflow.merge_task(WorkflowDb(0), 1, task.id, None, force=True)
    assert task.closed_by_id is None


async def test_the_lead_is_recorded_when_cancelling(monkeypatch):
    task, lead = lead_flow(monkeypatch)
    await workflow.update_task(
        WorkflowDb(0), 1, task.id, title=None, description=None, acceptance_criteria=None,
        depends_on=None, status="cancelled", author=lead,
    )  # fmt: skip
    assert task.closed_by_id == lead.id
