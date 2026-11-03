"""Reviewer diff: lockfiles summarized, sources first, truncation lists the omitted files."""

from app.diff_view import render_diff


def file_diff(path: str, added: int) -> str:
    body = "".join(f"+line {i}\n" for i in range(added))
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1,{added} @@\n{body}"


def test_lockfile_is_one_summary_line_and_sources_stay():
    diff = file_diff("web/package-lock.json", 5000) + file_diff("web/src/app.ts", 3)
    out = render_diff(diff)
    assert "+line 2\n" in out and "web/src/app.ts" in out
    assert "[lockfile web/package-lock.json: +5000 -0, content not shown]" in out
    assert "line 4999" not in out
    assert "truncated" not in out


def test_smaller_files_come_before_larger_ones():
    out = render_diff(file_diff("big.py", 50) + file_diff("small.py", 1))
    assert out.index("small.py") < out.index("big.py")


def test_truncation_lists_omitted_files():
    diff = file_diff("a.py", 1) + file_diff("huge.py", 500) + file_diff("huge2.py", 600)
    out = render_diff(diff, max_chars=300)
    assert "[diff truncated: 2 file(s) not shown" in out
    assert "- huge.py" in out and "- huge2.py" in out
    assert "line 499" not in out


def test_empty_diff():
    assert render_diff("") == ""
