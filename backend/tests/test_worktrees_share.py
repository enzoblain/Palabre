"""Clones are opened to the agent group only in shared-account mode."""

import grp
import os
import stat

import pytest

from app import worktrees
from app.config import settings


@pytest.mark.parametrize(("user", "pool", "expected"), [("agent", 0, True), ("agent", 3, False), ("", 0, False)])
def test_shares_clones_only_without_pool(monkeypatch, user, pool, expected):
    monkeypatch.setattr(settings, "agent_user", user)
    monkeypatch.setattr(settings, "agent_pool_size", pool)
    assert worktrees._shares_clones() is expected


def test_share_with_group_sets_group_and_setgid(monkeypatch, tmp_path):
    gid = os.getgid()
    monkeypatch.setattr(worktrees, "SHARED_GROUP", grp.getgrgid(gid).gr_name)
    clone = tmp_path / "clone"
    (clone / "sub").mkdir(parents=True)
    clone.chmod(0o700)
    (clone / "sub" / "f").write_text("x")
    (clone / "link").symlink_to("sub")
    worktrees._share_with_group(clone)
    for d in (clone, clone / "sub"):
        mode = d.stat().st_mode
        assert mode & stat.S_ISGID
        assert mode & 0o070 == 0o070
    f = clone / "sub" / "f"
    assert f.stat().st_mode & 0o060 == 0o060
    assert f.stat().st_gid == gid
