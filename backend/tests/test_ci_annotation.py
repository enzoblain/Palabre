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


def test_collection_error_points_at_the_module():
    # A CollectReport carries no location: the nodeid is the module path
    longrepr = SimpleNamespace(reprcrash=SimpleNamespace(message="ImportError: nope"))
    collect = SimpleNamespace(nodeid="tests/test_broken.py", longrepr=longrepr)
    note = annotation(collect)
    assert note.startswith("::error file=backend/tests/test_broken.py,line=1,")
    assert "ImportError: nope" in note
