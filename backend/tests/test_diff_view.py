"""get_diff output: lockfiles summarised, truncation by whole files with the omitted ones named."""

from app.diff_view import render_diff, split_diff


def file_diff(path: str, added: int, removed: int = 0) -> str:
    body = "".join(f"-old {n}\n" for n in range(removed)) + "".join(f"+new {n}\n" for n in range(added))
    return f"diff --git a/{path} b/{path}\nindex 111..222 100644\n--- a/{path}\n+++ b/{path}\n@@ -1,1 +1,1 @@\n{body}"


def test_lockfile_content_is_replaced_by_its_counts() -> None:
    diff = file_diff("mobile/package-lock.json", 5000, 3) + file_diff("mobile/src/app.ts", 2)
    out = render_diff(diff)
    assert "+new 1\n" in out and "mobile/src/app.ts" in out
    assert "+new 4999" not in out
    assert "mobile/package-lock.json (+5000 -3)" in out


def test_all_files_after_a_lockfile_are_kept() -> None:
    diff = file_diff("a/package-lock.json", 16000) + file_diff("b/src.ts", 3) + file_diff("c/tsconfig.json", 1)
    out = render_diff(diff, max_chars=1000)
    assert "diff --git a/b/src.ts" in out and "diff --git a/c/tsconfig.json" in out
    assert "truncated" not in out


def test_nested_lockfile_name_is_matched_on_basename() -> None:
    assert [f.is_lockfile for f in split_diff(file_diff("x/y/uv.lock", 1) + file_diff("uv.lock.md", 1))] == [True, False]


def test_truncation_drops_whole_files_and_names_them() -> None:
    small, big = file_diff("a.py", 2), file_diff("big.py", 500)
    out = render_diff(small + big + file_diff("z.py", 2), max_chars=len(small) * 2)
    assert "diff --git a/a.py" in out and "diff --git a/z.py" in out
    assert "diff --git a/big.py" not in out
    assert "these files are not shown, read them directly: big.py]" in out


def test_small_diff_is_returned_unchanged() -> None:
    diff = file_diff("a.py", 1) + file_diff("b.py", 1)
    assert render_diff(diff) == diff


def test_empty_diff() -> None:
    assert render_diff("") == ""


def test_quoted_path_after_a_lockfile_is_still_a_file_boundary() -> None:
    quoted = 'diff --git "a/caf\\303\\251.ts" "b/caf\\303\\251.ts"\n--- "a/caf\\303\\251.ts"\n+++ "b/caf\\303\\251.ts"\n@@ -1 +1 @@\n+secret code\n'
    out = render_diff(file_diff("package-lock.json", 10) + quoted)
    assert "+secret code" in out
    assert "package-lock.json (+10 -0)" in out
    assert [f.path for f in split_diff(quoted)] == ["café.ts"]


def test_text_before_the_first_file_is_kept() -> None:
    assert render_diff("warning\n" + file_diff("a.py", 1)).startswith("warning\n")


def test_quoted_path_with_a_non_latin1_character_is_decoded() -> None:
    quoted = 'diff --git "a/x\\t\u2603.py" "b/x\\t\u2603.py"\n+x\n'
    assert [f.path for f in split_diff(quoted)] == ["x\t\u2603.py"]
