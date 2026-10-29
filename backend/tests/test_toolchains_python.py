import os
import subprocess
import sys

import pytest

from app import toolchains
from app.services import WorkflowError


@pytest.mark.parametrize("spec", ["pytest", "pytest==8.2.0", "httpx[http2]>=0.27", "ruff~=0.5"])
def test_package_spec_accepted(spec):
    assert toolchains.PACKAGE_RE.match(spec)


@pytest.mark.parametrize("spec", ["-e .", "--index-url", "http://x/y.whl", "./local", "a b", "a;rm"])
def test_package_spec_refused(spec):
    assert not toolchains.PACKAGE_RE.match(spec)


async def test_python_refuses_option_as_package():
    with pytest.raises(WorkflowError):
        await toolchains.install("python", packages="--target=/tmp/x")


async def test_python_install_links_wrappers_and_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(toolchains.settings, "toolchains_dir", tmp_path)
    calls = []

    async def fake_run(cmd):
        calls.append(cmd)
        if "venv" in cmd:
            (tmp_path / "python-venv" / "bin").mkdir(parents=True)
            (tmp_path / "python-venv" / "bin" / "python").touch()
        else:
            (tmp_path / "python-venv" / "bin" / "pytest").touch()

    monkeypatch.setattr(toolchains, "_run", fake_run)
    await toolchains.install("python", packages="pytest, pytest-asyncio==0.23.0")
    assert "--only-binary=:all:" in calls[1]
    assert calls[1][-2:] == ["pytest", "pytest-asyncio==0.23.0"]
    assert (tmp_path / "bin" / "python").read_text().startswith("#!/bin/sh")
    assert (tmp_path / "bin" / "pytest").is_symlink()


async def test_python_refuses_version():
    with pytest.raises(WorkflowError):
        await toolchains.install("python", version="3.11")


async def test_run_uses_private_umask_and_no_cache(monkeypatch):
    seen = {}

    class Proc:
        returncode = 0

        async def communicate(self):
            return b"", None

    async def fake_exec(*cmd, **kwargs):
        seen.update(kwargs)
        return Proc()

    monkeypatch.setattr(toolchains.asyncio, "create_subprocess_exec", fake_exec)
    await toolchains._run(["true"])
    assert seen["umask"] == 0o022
    assert seen["env"]["PIP_NO_CACHE_DIR"] == "1"


async def test_python_wrapper_keeps_venv_and_system_packages(tmp_path, monkeypatch):
    monkeypatch.setattr(toolchains.settings, "toolchains_dir", tmp_path)
    old = os.umask(0o022)

    async def real_venv(cmd):
        if "venv" in cmd:
            subprocess.run(cmd, check=True)

    monkeypatch.setattr(toolchains, "_run", real_venv)
    try:
        await toolchains.install("python")
    finally:
        os.umask(old)
    venv = tmp_path / "python-venv"
    assert toolchains._venv_is_private(venv)
    out = subprocess.run(
        [str(tmp_path / "bin" / "python"), "-c", "import sys, fastapi; print(sys.prefix)"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert out == str(venv)


async def test_group_writable_venv_is_recreated(tmp_path, monkeypatch):
    monkeypatch.setattr(toolchains.settings, "toolchains_dir", tmp_path)
    venv = tmp_path / "python-venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    (venv / "lib").chmod(0o775)
    assert not toolchains._venv_is_private(venv)
    calls = []

    async def fake_run(cmd):
        calls.append(cmd)
        if "venv" in cmd:
            (venv / "bin").mkdir(parents=True)
            (venv / "bin" / "python").touch()
            (venv / "pyvenv.cfg").write_text(f"version = {sys.version.split()[0]}\n")

    monkeypatch.setattr(toolchains, "_run", fake_run)
    await toolchains.install("python")
    assert any("venv" in c for c in calls)
