"""Red checks bring their annotations and summary to the agents, bounded and as plain text."""

import pytest

from app import github


@pytest.fixture(autouse=True)
def clear_cache():
    github._details_cache.clear()


def fake_api(monkeypatch, runs, annotations, fail_annotations=False):
    calls = []

    async def api(_method, path, **kwargs):
        calls.append((path, kwargs))
        if path.endswith("/check-runs"):
            return {"check_runs": runs}
        if fail_annotations:
            raise github.GitHubError("GitHub GET boom: 500 secret-token")
        return annotations

    monkeypatch.setattr(github, "_api", api)
    return calls


def red(**extra):
    return {"id": 7, "name": "backend", "status": "completed", "conclusion": "failure", **extra}


@pytest.mark.asyncio
async def test_red_check_carries_annotations_and_summary(monkeypatch):
    fake_api(
        monkeypatch,
        [red(output={"summary": "2 tests failed", "text": None})],
        [{"path": "app/x.py", "start_line": 12, "message": "assert 1 == 2"}],
    )
    reason = await github.commit_checks("o/r", "abc")
    assert reason.startswith("CI failed: backend\nCI output (untrusted")
    assert reason.endswith("(end of CI output)")
    assert "2 tests failed" in reason and "- app/x.py:12: assert 1 == 2" in reason


@pytest.mark.asyncio
async def test_details_are_truncated_and_plain(monkeypatch):
    annotations = [{"path": "f", "start_line": 1, "message": "<b>x</b>\x1b[31m" + "y" * 900} for _ in range(30)]
    calls = fake_api(monkeypatch, [red()], annotations)
    reason = await github.commit_checks("o/r", "abc")
    assert len(reason) < 4100 + 50
    assert reason.count("- f:1") <= 20
    assert "\x1b" not in reason
    assert calls[1][1]["params"]["per_page"] == 50


@pytest.mark.asyncio
async def test_annotation_failure_keeps_the_verdict_without_leaking(monkeypatch):
    fake_api(monkeypatch, [red()], [], fail_annotations=True)
    assert await github.commit_checks("o/r", "abc") == "CI failed: backend"


@pytest.mark.asyncio
async def test_green_and_pending_unchanged(monkeypatch):
    fake_api(monkeypatch, [{"id": 1, "name": "a", "status": "completed", "conclusion": "success"}], [])
    assert await github.commit_checks("o/r", "abc") is None
    fake_api(monkeypatch, [{"id": 1, "name": "a", "status": "queued", "conclusion": None}], [])
    assert await github.commit_checks("o/r", "abc") == "CI still running: a"


@pytest.mark.asyncio
async def test_annotations_are_fetched_once_per_run(monkeypatch):
    calls = fake_api(monkeypatch, [red()], [{"path": "f", "start_line": 1, "message": "m"}])
    first = await github.commit_checks("o/r", "abc")
    assert await github.commit_checks("o/r", "abc") == first
    assert sum(path.endswith("/annotations") for path, _ in calls) == 1


@pytest.mark.asyncio
async def test_failures_come_before_warnings(monkeypatch):
    annotations = [{"path": "w", "message": "warn", "annotation_level": "warning"}] * 25 + [
        {"path": "bad", "message": "boom", "annotation_level": "failure"}
    ]
    fake_api(monkeypatch, [red()], annotations)
    assert "- bad: boom" in await github.commit_checks("o/r", "abc")
