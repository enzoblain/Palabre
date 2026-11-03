"""Reviewer view of a diff: lockfiles summarized, sources first, explicit list of what was cut."""

from dataclasses import dataclass
from pathlib import PurePosixPath

MAX_DIFF_CHARS = 100_000
FILE_HEADER = "diff --git "
# Generated files whose content is noise for a reviewer: shown as one summary line
LOCKFILE_NAMES = frozenset({
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock", "bun.lockb",
    "poetry.lock", "Pipfile.lock", "uv.lock", "Cargo.lock", "Gemfile.lock", "composer.lock", "go.sum",
    "pubspec.lock", "Podfile.lock", "gradle.lockfile", "packages.lock.json",
})


@dataclass(frozen=True)
class FileDiff:
    path: str
    text: str

    @property
    def is_lockfile(self) -> bool:
        return PurePosixPath(self.path).name in LOCKFILE_NAMES

    def count_changes(self) -> tuple[int, int]:
        """Added and removed lines, ignoring the ---/+++ headers."""
        lines = self.text.splitlines()
        added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
        return added, removed

    def summary_line(self) -> str:
        added, removed = self.count_changes()
        return f"[lockfile {self.path}: +{added} -{removed}, content not shown]\n"


def split_files(diff: str) -> list[FileDiff]:
    """Cut a git diff into one chunk per file, in order."""
    if not diff.startswith(FILE_HEADER):
        return [FileDiff(path="(unparsed diff)", text=diff)] if diff else []
    bodies = diff.removeprefix(FILE_HEADER).split("\n" + FILE_HEADER)
    return [FileDiff(path=_path_of(body), text=FILE_HEADER + body.rstrip("\n") + "\n") for body in bodies]


def _path_of(body: str) -> str:
    """The new path from the `a/x b/y` header line."""
    header = body.split("\n", 1)[0]
    return header.rsplit(" b/", 1)[-1] if " b/" in header else header


def render_diff(diff: str, max_chars: int = MAX_DIFF_CHARS) -> str:
    """Lockfiles become a summary line; the other files come smallest first so that the sources
    fit before the limit. Files that still do not fit are listed, never cut in the middle."""
    files = split_files(diff)
    sources = sorted((f for f in files if not f.is_lockfile), key=lambda f: len(f.text))
    parts: list[str] = []
    used = 0
    omitted: list[str] = []
    for file in sources:
        if used + len(file.text) <= max_chars and not omitted:
            parts.append(file.text)
            used += len(file.text)
        else:
            omitted.append(file.path)
    parts.extend(f.summary_line() for f in files if f.is_lockfile)
    if omitted:
        listing = "\n".join(f"- {path}" for path in omitted)
        parts.append(f"\n[diff truncated: {len(omitted)} file(s) not shown, read them directly]\n{listing}\n")
    return "".join(parts)
