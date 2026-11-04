"""Swift build of a task: queued at each submission, shown on the task, required before the merge."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import apple, github, workflow
from app.errors import ErrorCode, WorkflowError
from app.models import AppleJob, AppleJobStatus, Base, TaskStatus

from .conftest import make_project, make_task

HEAD = "b" * 40
OLD_HEAD = "a" * 40
NOW = datetime(2030, 1, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'gate.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def apple_project():
    return make_project(platform="apple")


@pytest.fixture(autouse=True)
def no_reviews(monkeypatch, process):
    async def task_reviews(_s, _task):
        return []

    monkeypatch.setattr(workflow, "task_reviews", task_reviews)
    process(required_approvals=0)


async def queue(db, task, sha=HEAD, status=AppleJobStatus.queued, log_excerpt=""):
    job = await apple.enqueue_job(db, task.project_id, task.branch, sha, task.id)
    job.status, job.log_excerpt = status, log_excerpt
    await db.commit()
    return job


# --- Queuing -----------------------------------------------------------------------


async def test_a_submission_queues_one_build_per_head(db, apple_project):
    task = make_task()
    first = await apple.queue_task_build(db, apple_project, task, HEAD)
    again = await apple.queue_task_build(db, apple_project, task, HEAD)
    assert again.id == first.id
    assert (first.task_id, first.commit_sha, first.status) == (task.id, HEAD, AppleJobStatus.queued)


async def test_a_new_head_queues_a_new_build(db, apple_project):
    task = make_task()
    old = await apple.queue_task_build(db, apple_project, task, OLD_HEAD)
    new = await apple.queue_task_build(db, apple_project, task, HEAD)
    assert new.id != old.id


async def test_resubmitting_after_an_infra_error_queues_again(db, apple_project):
    task = make_task()
    failed = await queue(db, task, status=AppleJobStatus.error)
    assert (await apple.queue_task_build(db, apple_project, task, HEAD)).id != failed.id


async def test_a_failed_build_is_not_requeued_for_the_same_head(db, apple_project):
    task = make_task()
    failed = await queue(db, task, status=AppleJobStatus.failed)
    assert (await apple.queue_task_build(db, apple_project, task, HEAD)).id == failed.id


@pytest.fixture
def submit(monkeypatch, db):
    """Submits a task of the given project with GitHub, git and the chat faked out."""

    async def noop(*_, **__):
        pass

    async def one(*_):
        return 1

    async def pushed_head(*_):
        return HEAD

    async def no_pull_request(*_):
        return None

    async def changed_files(*_):
        return []

    for name, fake in {
        "_commits_ahead": one, "_pushed_head": pushed_head, "_changed_files": changed_files, "_keep_reviewed_head": noop,
        "push_task_branch": noop, "announce": noop, "post_message": noop,
    }.items():  # fmt: skip
        monkeypatch.setattr(workflow, name, fake)
    monkeypatch.setattr(workflow, "emit_event", lambda *_, **__: None)
    monkeypatch.setattr(workflow, "wake_lead", lambda *_: None)  # Its pending changes are module state
    monkeypatch.setattr(workflow, "mode_process", lambda _: {"qa_gate": False, "security_gate": False})
    monkeypatch.setattr(github, "find_pull_request", no_pull_request)
    monkeypatch.setattr(github, "set_pull_request_title", noop)
    monkeypatch.setattr(github, "comment_pull_request", noop)

    async def run(project):
        task = SimpleNamespace(
            id=7, project_id=1, assignee_id=1, status=TaskStatus.changes_requested, branch="fix/7-x", worktree_path="/w",
            pr_number=12, pr_url="u", pr_title="t", review_round=1, sensitive=False, conversation_id=1,
            merge_ready_at=None, lead_reminded_at=None, reviewed_head=None,
        )  # fmt: skip

        async def get(*_):
            return project

        async def get_task(*_):
            return task

        monkeypatch.setattr(db, "get", get)
        monkeypatch.setattr(workflow, "get_task", get_task)
        await workflow.submit_for_review(db, 1, 7, SimpleNamespace(id=1, name="Malik"), "sum", False, title="fix(api): x")
        return task

    return run


async def test_submitting_an_apple_project_queues_the_build_of_the_head(db, apple_project, submit):
    task = await submit(apple_project)
    job = await apple.latest_task_job(db, task.id)
    assert (job.project_id, job.branch, job.commit_sha, job.status) == (apple_project.id, "fix/7-x", HEAD, AppleJobStatus.queued)


async def test_submitting_a_generic_project_queues_nothing(db, submit):
    await submit(make_project())
    assert (await db.scalars(select(AppleJob))).all() == []


# --- Merge gate --------------------------------------------------------------------


async def test_no_build_blocks_the_merge(db, apple_project, fake_github):
    assert await workflow.merge_blockers(db, apple_project, make_task()) == ["no Swift build for the PR head yet"]


@pytest.mark.parametrize(
    ("build_status", "expected"),
    [
        (AppleJobStatus.queued, "Swift build queued"),
        (AppleJobStatus.running, "Swift build still running"),
        (AppleJobStatus.failed, "Swift build failed: fix the errors and submit again"),
        (AppleJobStatus.error, "Swift build hit an infra error, not a test failure: relaunch it with retry_apple_build"),
    ],
)
async def test_an_unfinished_or_red_build_blocks_the_merge(db, apple_project, fake_github, build_status, expected):
    task = make_task()
    await queue(db, task, status=build_status)
    assert await workflow.merge_blockers(db, apple_project, task) == [expected]


async def test_a_passed_build_lets_the_merge_through(db, apple_project, fake_github):
    task = make_task()
    await queue(db, task, status=AppleJobStatus.passed)
    assert await workflow.merge_blockers(db, apple_project, task) == []


async def test_a_green_build_of_an_old_head_does_not_count(db, apple_project, fake_github):
    task = make_task()
    await queue(db, task, sha=OLD_HEAD, status=AppleJobStatus.passed)
    assert await workflow.merge_blockers(db, apple_project, task, ci_head=HEAD) == ["no Swift build for the PR head yet"]


async def test_the_build_of_another_task_does_not_count(db, apple_project, fake_github):
    await queue(db, make_task(), status=AppleJobStatus.passed)
    assert await workflow.merge_blockers(db, apple_project, make_task()) == ["no Swift build for the PR head yet"]


async def test_a_generic_project_has_no_build_gate(db, project, fake_github):
    assert await workflow.merge_blockers(db, project, make_task()) == []


# --- Retry -------------------------------------------------------------------------


async def test_an_infra_error_can_be_retried(db, apple_project):
    task = make_task()
    errored = await queue(db, task, status=AppleJobStatus.error)
    retried = await apple.retry_task_build(db, apple_project, task)
    assert (retried.id != errored.id, retried.commit_sha, retried.status) == (True, HEAD, AppleJobStatus.queued)
    assert len((await db.scalars(select(AppleJob))).all()) == 2


@pytest.mark.parametrize("build_status", [AppleJobStatus.failed, AppleJobStatus.running, AppleJobStatus.passed])
async def test_only_an_infra_error_can_be_retried(db, apple_project, build_status):
    task = make_task()
    await queue(db, task, status=build_status)
    with pytest.raises(WorkflowError) as error:
        await apple.retry_task_build(db, apple_project, task)
    assert error.value.code == ErrorCode.APPLE_BUILD_NOT_RETRYABLE


async def test_retry_without_any_build_is_refused(db, apple_project):
    with pytest.raises(WorkflowError):
        await apple.retry_task_build(db, apple_project, make_task())


# --- What the task shows -----------------------------------------------------------


def test_the_build_detail_keeps_the_error_lines_only():
    log = "Compiling A.swift\nA.swift:3:5: error: cannot find 'x' in scope\nLinking\nTest Case 'T.testX' failed\n"
    job = AppleJob(id=9, status=AppleJobStatus.failed, commit_sha=HEAD, summary="", log_excerpt=log, finished_at=NOW)
    detail = apple.build_detail(job)
    assert detail["errors"] == ["A.swift:3:5: error: cannot find 'x' in scope", "Test Case 'T.testX' failed"]
    assert (detail["status"], detail["infra_error"], detail["finished_at"]) == ("failed", False, NOW.isoformat())


def test_error_lines_are_capped():
    log = "\n".join(f"error: {number} " + "x" * 1000 for number in range(apple.MAX_ERROR_LINES + 5))
    lines = apple.error_lines(log)
    assert len(lines) == apple.MAX_ERROR_LINES
    assert lines[-1].startswith(f"error: {apple.MAX_ERROR_LINES + 4} ")
    assert all(len(line) <= apple.MAX_ERROR_LINE_CHARS for line in lines)


def test_an_infra_error_is_flagged_apart_from_a_failure():
    job = AppleJob(id=1, status=AppleJobStatus.error, commit_sha=HEAD, summary=apple.TIMEOUT_SUMMARY, log_excerpt="")
    assert apple.build_detail(job)["infra_error"] is True


def test_no_build_means_no_detail():
    assert apple.build_detail(None) is None
