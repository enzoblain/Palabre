"""A reviewer who commented without a verdict is woken up when the verification is done, or after a delay."""

from datetime import UTC, datetime, timedelta

from app import workflow
from app.config import settings
from app.models import TaskStatus, Verdict
from app.orchestrator import merge_watch

from .conftest import FakeSession, make_employee, make_review, make_task


def woken(session, type_):
    return [e for e in session.added if getattr(e, "type", None) == type_]


class RecordingSession(FakeSession):
    def __init__(self, reviews):
        super().__init__(reviews)
        self.added = []

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
    def __init__(self, tasks, reviewers, busy=None):
        super().__init__([])
        self.tasks, self.reviewers, self.busy = tasks, reviewers, busy

    async def scalars(self, query):
        table = str(query).split("FROM ")[1].split()[0]
        return {"tasks": self.tasks, "employees": self.reviewers}.get(table, [])

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
    assert overdue.target_role == "reviewer" and stalled.target_role == "lead"


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
