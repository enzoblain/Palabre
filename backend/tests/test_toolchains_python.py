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
    assert calls[1][-2:] == ["pytest", "pytest-asyncio==0.23.0"]
    assert (tmp_path / "bin" / "python").read_text().startswith("#!/bin/sh")
    assert (tmp_path / "bin" / "pytest").is_symlink()
