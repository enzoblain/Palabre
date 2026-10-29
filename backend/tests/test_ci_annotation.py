"""A failed test report becomes one ::error annotation with its own file, line and name."""

from types import SimpleNamespace

from tests.ci_annotation import annotation


def report(nodeid, line, message="assert 1 == 2"):
    path = nodeid.split("::")[0]
    longrepr = SimpleNamespace(reprcrash=SimpleNamespace(message=message))
    return SimpleNamespace(nodeid=nodeid, location=(path, line, "test"), longrepr=longrepr)


def test_two_failures_in_one_file_keep_their_own_line():
    first = annotation(report("tests/test_x.py::test_a", 4))
    second = annotation(report("tests/test_x.py::test_b[1,2]", 19))
    assert first.startswith("::error file=backend/tests/test_x.py,line=5,")
    assert "tests/test_x.py::test_a - assert 1 == 2" in first
    assert second.startswith("::error file=backend/tests/test_x.py,line=20,")
    assert "title=tests/test_x.py%3A%3Atest_b[1%2C2]::" in second


def test_message_newlines_are_escaped():
    assert "\n" not in annotation(report("tests/t.py::t", 0, "a\nb"))


def test_collection_error_points_at_the_file_line_1(monkeypatch, capsys):
    from tests import conftest

    longrepr = SimpleNamespace(reprcrash=SimpleNamespace(message="ImportError: nope"))
    collected = SimpleNamespace(nodeid="tests/test_x.py", failed=True, longrepr=longrepr)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    conftest.pytest_collectreport(collected)
    out = capsys.readouterr().out
    assert "::error file=backend/tests/test_x.py,line=1," in out
    assert "ImportError: nope" in out
    monkeypatch.delenv("GITHUB_ACTIONS")
    conftest.pytest_collectreport(collected)
    assert capsys.readouterr().out == ""
