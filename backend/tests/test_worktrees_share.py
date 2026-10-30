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
    (clone / "sub" / "f").chmod(0o600)
    (clone / "sub" / "x").write_text("x")
    (clone / "sub" / "x").chmod(0o700)
    (clone / "link").symlink_to("sub")
    worktrees._share_with_group(clone)
    for d in (clone, clone / "sub"):
        mode = d.stat().st_mode
        assert mode & stat.S_ISGID
        assert mode & 0o070 == 0o070
    f = clone / "sub" / "f"
    assert f.stat().st_mode & 0o060 == 0o060
    assert f.stat().st_gid == gid
    assert not f.stat().st_mode & 0o010
    assert (clone / "sub" / "x").stat().st_mode & 0o070 == 0o070


def test_share_with_group_missing_group_is_oserror(monkeypatch, tmp_path):
    monkeypatch.setattr(worktrees, "SHARED_GROUP", "no-such-group-xyz")
    with pytest.raises(OSError):
        worktrees._share_with_group(tmp_path)


def test_share_with_group_unreadable_subdir_is_oserror(monkeypatch, tmp_path):
    monkeypatch.setattr(worktrees, "SHARED_GROUP", grp.getgrgid(os.getgid()).gr_name)
    (tmp_path / "sub").mkdir()
    real_scandir = os.scandir

    def scandir(path):
        if str(path).endswith("sub"):
            raise PermissionError(13, "denied", str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)  # chmod 000 does not stop root
    with pytest.raises(PermissionError):
        worktrees._share_with_group(tmp_path)


@pytest.mark.parametrize(("pool", "called"), [(0, True), (2, False)])
async def test_clone_from_reference_wiring(monkeypatch, tmp_path, pool, called):
    monkeypatch.setattr(settings, "agent_user", "agent")
    monkeypatch.setattr(settings, "agent_pool_size", pool)
    monkeypatch.setattr(worktrees, "repo_dir", lambda p: tmp_path / "ref")

    async def noop(*a, **k):
        return ""

    seen = []
    monkeypatch.setattr(worktrees, "git", noop)
    monkeypatch.setattr(worktrees, "_pull_from_reference", noop)
    monkeypatch.setattr(worktrees, "_share_with_group", seen.append)
    project = type("P", (), {"repo_url": "u"})()
    await worktrees._clone_from_reference(project, tmp_path / "clones" / "c")
    assert bool(seen) is called


async def test_clone_from_reference_removes_clone_on_share_error(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "agent_user", "agent")
    monkeypatch.setattr(settings, "agent_pool_size", 0)
    monkeypatch.setattr(worktrees, "repo_dir", lambda p: tmp_path / "ref")

    async def noop(*a, **k):
        return ""

    def boom(path):
        raise PermissionError(13, "denied")

    monkeypatch.setattr(worktrees, "git", noop)
    monkeypatch.setattr(worktrees, "_pull_from_reference", noop)
    monkeypatch.setattr(worktrees, "_share_with_group", boom)
    clone = tmp_path / "clones" / "c"
    with pytest.raises(PermissionError):
        await worktrees._clone_from_reference(type("P", (), {"repo_url": "u"})(), clone)
    assert not clone.exists()
