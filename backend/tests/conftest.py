"""Shared fixtures.

No database: the business logic is tested against `FakeSession`, which serves in-memory
objects to the `select(...)` calls of the code under test. This keeps the suite fast and
free of extra dependencies (no Postgres, no SQLite driver). Code that really needs SQL
should get its own strategy, discussed first.

GitHub and git calls are replaced by `fake_github`, so nothing touches the network.
"""

import os
from datetime import UTC, datetime
from itertools import count
from types import SimpleNamespace

import pytest

# Settings() requires it at import time
os.environ.setdefault("ADMIN_TOKEN", "test-token-" + "x" * 32)

from app import github, workflow  # noqa: E402
from app.models import TaskStatus, Verdict  # noqa: E402

_ids = count(1)


class FakeSession:
    """Just enough of AsyncSession: `scalars()` returns the preloaded `scalar_results`
    in order; every query of the code under test must be queued by the test.
    The query itself is ignored: SQL filters (e.g. reviews of the current round) are not tested."""

    def __init__(self, *scalar_results: list):
        self.scalar_results = list(scalar_results)

    async def scalars(self, _query):
        return self.scalar_results.pop(0)


def make_employee(name: str = "Alice", *roles: str) -> SimpleNamespace:
    return SimpleNamespace(id=next(_ids), name=name, title=roles[0] if roles else "", roles=list(roles))


def make_review(reviewer, verdict: Verdict, round: int = 1, head_sha: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=next(_ids), reviewer=reviewer, reviewer_id=reviewer.id, verdict=verdict, round=round, head_sha=head_sha,
        created_at=datetime.now(UTC),
    )  # fmt: skip


def make_project(mode: str = "enterprise") -> SimpleNamespace:
    return SimpleNamespace(
        id=next(_ids), mode=mode, repo_url="https://github.com/acme/app", default_branch="main"
    )


def make_task(**overrides) -> SimpleNamespace:
    fields = dict(
        id=next(_ids), status=TaskStatus.review, review_round=1, reviewed_head=None, sensitive=False,
        pr_number=42, branch="task/1-demo", assignee_id=None, merge_retry_at=None, unstarted_nudges=0,
        idle_alert_sha=None, project_id=1, depends_on=[], worktree_path=None,
    )  # fmt: skip
    return SimpleNamespace(**(fields | overrides))


@pytest.fixture
def project():
    return make_project()


@pytest.fixture
def task():
    return make_task()


@pytest.fixture
def reviewer():
    return make_employee("Karim", "reviewer")


@pytest.fixture
def qa():
    return make_employee("Samuel", "qa")


@pytest.fixture
def security():
    return make_employee("Noa", "security")


@pytest.fixture
def process(monkeypatch):
    """Sets the merge gates of the mode under test, whatever the catalog says."""

    def set_process(**gates):
        full = dict(
            required_approvals=1, qa_gate=False, security_gate=False, ci_required=False, docs_required=False
        ) | gates
        monkeypatch.setattr(workflow, "mode_process", lambda _mode: full)

    return set_process


@pytest.fixture
def fake_github(monkeypatch):
    """CI is green and the diff holds a README, unless the test changes it."""
    state = SimpleNamespace(ci=None, changed_files=["app/x.py", "README.md"], git_calls=[])

    async def checks_status(_repo, _number, sha=None):
        return state.ci

    async def git(_cwd, *args, **_kwargs):
        state.git_calls.append(args)
        return "\n".join(state.changed_files)

    monkeypatch.setattr(github, "checks_status", checks_status)
    monkeypatch.setattr(github, "git", git)
    return state


@pytest.fixture(autouse=True)
def no_network_no_agent(monkeypatch):
    """Safety net: a test that forgets to mock GitHub, git or `claude -p` fails instead of running it."""
    import asyncio
    import socket

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Real network/subprocess call in a test: mock it")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def pytest_runtest_logreport(report):
    """On GitHub Actions, one ::error annotation per failed test, so names show on the PR."""
    if report.failed and os.environ.get("GITHUB_ACTIONS"):
        from tests.ci_annotation import annotation

        print(f"\n{annotation(report)}")


def pytest_collectreport(report):
    """Same for collection errors (e.g. an ImportError in a test module), reported at line 1."""
    if report.failed and os.environ.get("GITHUB_ACTIONS"):
        from tests.ci_annotation import annotation

        print(f"\n{annotation(report)}")
