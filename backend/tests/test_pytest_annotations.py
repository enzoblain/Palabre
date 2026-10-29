"""The CI script turns a pytest log into one ::error annotation per failed test."""

from scripts.pytest_annotations import annotations

LOG = """\
/home/runner/work/r/r/backend/tests/test_x.py:5: AssertionError: assert 1 == 2
=== short test summary info ===
FAILED tests/test_x.py::test_a[1,2] - assert 1 == 2
ERROR tests/test_y.py::test_b
1 failed
"""


def test_one_annotation_per_failure_with_file_line_and_name():
    first, second = annotations(LOG)
    assert first.startswith("::error file=backend/tests/test_x.py,line=5,")
    assert "tests/test_x.py::test_a[1,2] - assert 1 == 2" in first
    assert second.startswith("::error file=backend/tests/test_y.py,line=1,")


def test_green_log_has_no_annotation():
    assert annotations("5 passed in 1.2s\n") == []
