"""A reviewer who commented without a verdict is woken up when the verification is done, or after a delay."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import workflow
from app.config import settings
from app.models import Base, Event, Project, TaskStatus, Verdict
from app.orchestrator import merge_watch

from .conftest import FakeSession, make_employee, make_review, make_task


def woken(session, type_):
    return [e for e in session.added if getattr(e, "type", None) == type_]


class RecordingSession(FakeSession):
    def __init__(self, reviews, sent=()):
        super().__init__(reviews)
        self.added, self.sent = [], list(sent)

    async def scalars(self, query):
        if str(query).split("FROM ")[1].split()[0] == "events":
            return self.sent  # reminders already sent for the head
        return await super().scalars(query)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass


async def test_qa_report_wakes_the_reviewer_who_only_commented(reviewer, qa):
    task = make_task()
    s = RecordingSession([make_review(reviewer, Verdict.comment), make_review(qa, Verdict.comment)])
    await workflow._wake_waiting_reviewers(s, task, qa)
    [event] = woken(s, "verification_done")
    assert event.target_employee_id == reviewer.id and event.payload["task_id"] == task.id


async def test_security_report_wakes_the_reviewer_too(reviewer, security):
    s = RecordingSession([make_review(reviewer, Verdict.comment)])
    await workflow._wake_waiting_reviewers(s, make_task(), security)
    assert len(woken(s, "verification_done")) == 1


async def test_reviewer_who_gave_a_verdict_is_not_woken(reviewer, qa):
    reviews = [make_review(reviewer, Verdict.comment), make_review(reviewer, Verdict.approve)]
    s = RecordingSession(reviews)
    await workflow._wake_waiting_reviewers(s, make_task(), qa)
    assert not woken(s, "verification_done")


async def test_comment_on_an_old_round_does_not_wake(reviewer, qa):
    s = RecordingSession([make_review(reviewer, Verdict.comment, round=1)])
    await workflow._wake_waiting_reviewers(s, make_task(review_round=2), qa)
    assert not woken(s, "verification_done")


async def test_a_reviewer_report_does_not_wake_anyone(reviewer):
    other = make_employee("Lina", "reviewer")
    s = RecordingSession([make_review(other, Verdict.comment)])
    await workflow._wake_waiting_reviewers(s, make_task(), reviewer)
    assert not woken(s, "verification_done")


# --- Safety net --------------------------------------------------------------------


class SilenceSession(RecordingSession):
    def __init__(self, tasks, reviewers, busy=None, sent=()):
        super().__init__([], sent)
        self.tasks, self.reviewers, self.busy = tasks, reviewers, busy

    async def scalars(self, query):
        table = str(query).split("FROM ")[1].split()[0]
        if table == "events" and "events.created_at" in str(query):
            return []  # Timestamps of past reminders: none, the silence is old
        return {"tasks": self.tasks, "employees": self.reviewers, "events": self.sent}.get(table, [])

    async def scalar(self, _query):
        return self.busy


def silent_task(minutes_ago: int, **fields):
    submitted = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return make_task(
        status=TaskStatus.review, pr_number=4, submitted_at=submitted, pr_url="https://x/pull/4", **fields
    )


def patch_reviews(monkeypatch, reviews):
    async def task_reviews(*_):
        return reviews

    monkeypatch.setattr(workflow, "task_reviews", task_reviews)


async def test_silent_review_wakes_the_reviewer_and_tells_the_lead(reviewer, monkeypatch):
    patch_reviews(monkeypatch, [])
    s = SilenceSession([silent_task(settings.review_silence_minutes + 1)], [reviewer])
    await merge_watch.watch_silent_reviews(s)
    [overdue] = woken(s, "review_overdue")
    [stalled] = woken(s, "review_stalled")
    assert overdue.target_employee_id == reviewer.id and stalled.target_role == "lead"


async def test_recent_review_is_left_alone(reviewer, monkeypatch):
    patch_reviews(monkeypatch, [])
    s = SilenceSession([silent_task(1)], [reviewer])
    await merge_watch.watch_silent_reviews(s)
    assert not s.added


async def test_review_with_a_verdict_is_left_alone(reviewer, monkeypatch):
    patch_reviews(monkeypatch, [make_review(reviewer, Verdict.approve)])
    s = SilenceSession([silent_task(1000, review_round=1)], [reviewer])
    await merge_watch.watch_silent_reviews(s)
    assert not s.added


async def test_busy_reviewer_is_not_woken_again(reviewer, monkeypatch):
    patch_reviews(monkeypatch, [])
    s = SilenceSession([silent_task(1000)], [reviewer], busy=7)
    await merge_watch.watch_silent_reviews(s)
    assert not s.added


async def test_assignee_holding_the_reviewer_role_is_not_asked_to_review(reviewer, monkeypatch):
    patch_reviews(monkeypatch, [])
    other = make_employee("Lina", "reviewer")
    task = silent_task(1000, assignee_id=reviewer.id)
    s = SilenceSession([task], [reviewer, other])
    await merge_watch.watch_silent_reviews(s)
    [overdue] = woken(s, "review_overdue")
    assert overdue.target_employee_id == other.id


async def test_changes_verdict_of_qa_does_not_wake_the_waiting_reviewer(qa, monkeypatch):
    task = make_task(status=TaskStatus.review, assignee_id=99, pr_number=None, reviewed_head=None)

    class ReviewSession(RecordingSession):
        async def get(self, model, _id):
            return None

        async def flush(self):
            pass

    async def noop(*_args, **_kwargs):
        pass

    async def get_task(*_args):
        return task

    async def merge_blockers(*_args):
        return []

    waking = []
    monkeypatch.setattr(workflow, "get_task", get_task)
    monkeypatch.setattr(workflow, "announce", noop)
    monkeypatch.setattr(workflow, "wake_lead", lambda *_: None)
    monkeypatch.setattr(workflow, "wake_dev", noop)
    monkeypatch.setattr(workflow, "merge_blockers", merge_blockers)
    monkeypatch.setattr(workflow, "_wake_waiting_reviewers", lambda *args: waking.append(args) or noop())
    s = ReviewSession([])
    await workflow.review_task(s, task.project_id, task.id, qa, "changes", "broken", "a" * 12)
    assert task.status == TaskStatus.changes_requested and not waking


# --- Cap of reminders per head SHA ---------------------------------------------------


async def test_reminders_stop_at_the_cap_and_the_lead_is_told_once(reviewer, monkeypatch):
    patch_reviews(monkeypatch, [])
    sent = ["review_stalled"] * settings.max_review_reminders
    s = SilenceSession([silent_task(1000, reviewed_head="a" * 12)], [reviewer], sent=sent)
    await merge_watch.watch_silent_reviews(s)
    assert not woken(s, "review_overdue") and not woken(s, "review_stalled")
    [abandoned] = woken(s, "review_abandoned")
    assert abandoned.target_role == "lead" and abandoned.payload["head_sha"] == "a" * 12


async def test_no_second_notification_once_the_lead_was_told(reviewer, monkeypatch):
    patch_reviews(monkeypatch, [])
    sent = ["review_stalled"] * settings.max_review_reminders + ["review_abandoned"]
    s = SilenceSession([silent_task(1000)], [reviewer], sent=sent)
    await merge_watch.watch_silent_reviews(s)
    assert not s.added


async def test_below_the_cap_the_reviewer_is_still_reminded(reviewer, monkeypatch):
    patch_reviews(monkeypatch, [])
    sent = ["review_stalled"] * (settings.max_review_reminders - 1)
    s = SilenceSession([silent_task(1000)], [reviewer], sent=sent)
    await merge_watch.watch_silent_reviews(s)
    assert len(woken(s, "review_overdue")) == 1 and not woken(s, "review_abandoned")


async def test_qa_reports_stop_waking_the_reviewer_at_the_cap(reviewer, qa):
    s = RecordingSession([make_review(reviewer, Verdict.comment)], ["verification_done"] * settings.max_review_reminders)
    await workflow._wake_waiting_reviewers(s, make_task(), qa)
    assert not woken(s, "verification_done")


# --- The counting query, run on a real session -----------------------------------------


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add(Project(name="P", repo_url="https://github.com/o/r", mode="enterprise", seed=1, kind="company"))
        await session.flush()
        yield session
    await engine.dispose()


def reminder(project_id, type_, task_id, head):
    return Event(project_id=project_id, type=type_, payload={"task_id": task_id, "head_sha": head})


async def test_count_is_per_task_and_per_head_sha(db):
    project = (await db.scalars(select(Project))).one()
    task = make_task(project_id=project.id, reviewed_head="a" * 12)
    db.add_all([
        reminder(project.id, "review_stalled", task.id, "a" * 12),
        reminder(project.id, "review_stalled", task.id, "a" * 12),
        reminder(project.id, "review_stalled", task.id, "b" * 12),  # another head: starts from zero
        reminder(project.id, "review_stalled", task.id + 1, "a" * 12),  # another task
        reminder(project.id, "review_overdue", task.id, "a" * 12),  # not counted
    ])  # fmt: skip
    await db.flush()
    assert await workflow.review_reminders_sent(db, task, "review_stalled") == ["review_stalled"] * 2
    task.reviewed_head = "b" * 12
    assert await workflow.review_reminders_sent(db, task, "review_stalled") == ["review_stalled"]


async def test_the_json_filters_compile_to_postgres_operators():
    query = select(Event.type).where(
        Event.payload["task_id"].as_integer() == 1, Event.payload["head_sha"].as_string() == "x"
    )
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "events.payload ->> %(payload_1)s" in sql and "CAST" in sql
