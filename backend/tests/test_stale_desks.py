"""Leftover stale-desk-* folders are deleted at startup."""

import asyncio

from app import worktrees
from app.config import settings


def test_remove_stale_desks_deletes_only_stale_ones(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", tmp_path)
    monkeypatch.setattr(worktrees.agent_pool, "users", lambda: [])
    stale = tmp_path / "project-8" / "stale-desk-employee-53-1"
    (stale / ".git").mkdir(parents=True)
    (stale / "file").write_text("secret")
    stale.chmod(0o2775)
    live = tmp_path / "project-8" / "desks" / "employee-53"
    live.mkdir(parents=True)
    asyncio.run(worktrees.remove_stale_desks())
    assert not stale.exists()
    assert live.exists()


def test_remove_stale_desks_without_projects(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "missing")
    asyncio.run(worktrees.remove_stale_desks())
