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


def lockfile_diff(added_lines: list[str]) -> str:
    body = "".join(f"+{line}\n" for line in added_lines)
    return f"diff --git a/package-lock.json b/package-lock.json\n--- a/package-lock.json\n+++ b/package-lock.json\n@@ -1,1 +1,1 @@\n{body}"


def test_lockfile_line_with_non_default_registry_is_listed() -> None:
    diff = lockfile_diff(['"resolved": "https://evil.example.com/x/-/x-1.0.0.tgz",'])
    out = render_diff(diff)
    assert "https://evil.example.com/x/-/x-1.0.0.tgz" in out
    assert "review dependency changes in the file" in out


def test_lockfile_with_only_default_registries_keeps_the_short_note() -> None:
    diff = lockfile_diff(['"resolved": "https://registry.npmjs.org/x/-/x-1.0.0.tgz",', '"integrity": "sha512-abc"'])
    out = render_diff(diff)
    assert "non-default registry" not in out
    assert "package-lock.json (+2 -0)" in out and "review dependency changes in the file" in out


def test_code_is_shown_before_lockfile_notes() -> None:
    diff = lockfile_diff(['source = "git+https://evil.example.com/x.git"']) + file_diff("src/app.ts", 2)
    out = render_diff(diff)
    assert out.index("src/app.ts") < out.index("evil.example.com")


def test_flagged_lines_are_capped() -> None:
    out = render_diff(lockfile_diff([f'"resolved": "https://evil.example.com/{n}",' for n in range(50)]))
    assert "and 40 more" in out
