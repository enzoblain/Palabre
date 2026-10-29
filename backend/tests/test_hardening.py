import os
import subprocess
import sys

import pytest

from app.hardening import make_non_dumpable


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")
def test_environ_unreadable_by_sibling_process():
    code = (
        "import os,sys,subprocess\n"
        "from app.hardening import make_non_dumpable\n"
        "assert make_non_dumpable()\n"
        "r = subprocess.run([sys.executable,'-c',"
        "f'open(\"/proc/{os.getpid()}/environ\",\"rb\").read()'],capture_output=True)\n"
        "sys.exit(0 if r.returncode != 0 else 1)\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=os.getcwd())
    assert r.returncode == 0, r.stderr


def test_no_error_off_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert make_non_dumpable() is False


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")
def test_warns_when_prctl_fails(monkeypatch, caplog):
    class FakeLibc:
        def prctl(self, *args):
            return -1

    monkeypatch.setattr("app.hardening.ctypes.CDLL", lambda *a, **k: FakeLibc())
    with caplog.at_level("WARNING", logger="app.hardening"):
        assert make_non_dumpable() is False
    assert "PR_SET_DUMPABLE" in caplog.text


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")
def test_warns_when_libc_unavailable(monkeypatch, caplog):
    def boom(*a, **k):
        raise OSError("no libc")

    monkeypatch.setattr("app.hardening.ctypes.CDLL", boom)
    with caplog.at_level("WARNING", logger="app.hardening"):
        assert make_non_dumpable() is False
    assert "stays dumpable" in caplog.text
