"""Shapes a git diff for an agent: generated lockfiles are summarised and the size limit drops whole files."""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

MAX_DIFF_CHARS = 100_000
# Generated files whose content is noise for a reviewer: listed with their line counts only
LOCKFILE_NAMES = frozenset({
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock", "bun.lockb",
    "uv.lock", "poetry.lock", "Pipfile.lock", "pdm.lock", "Cargo.lock", "Gemfile.lock", "composer.lock",
    "go.sum", "packages.lock.json", "gradle.lockfile", "pubspec.lock", "Podfile.lock", "flake.lock",
})
_FILE_HEADER = re.compile(r"^diff --git a/.+ b/(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class FileDiff:
    path: str
    text: str

    @property
    def is_lockfile(self) -> bool:
        return PurePosixPath(self.path).name in LOCKFILE_NAMES

    @property
    def line_counts(self) -> tuple[int, int]:
        """(added, removed) lines; only what follows the first hunk header is content."""
        _, _, hunks = self.text.partition("\n@@")
        lines = hunks.split("\n")[1:]  # The first one is the rest of the header line
        return (sum(line.startswith("+") for line in lines), sum(line.startswith("-") for line in lines))


def split_diff(diff: str) -> list[FileDiff]:
    """One FileDiff per file of a `git diff` output, in the order git printed them."""
    starts = [match.start() for match in _FILE_HEADER.finditer(diff)]
    ends = [*starts[1:], len(diff)]
    return [
        FileDiff(path=_FILE_HEADER.match(diff, start).group(1), text=diff[start:end])
        for start, end in zip(starts, ends, strict=False)
    ]


def render_diff(diff: str, max_chars: int = MAX_DIFF_CHARS) -> str:
    """The diff without lockfile content, cut by whole files at max_chars. What is not shown
    (lockfiles, files that did not fit) is listed at the end so the reader knows what to open."""
    files = split_diff(diff)
    shown: list[str] = []
    lockfiles: list[str] = []
    skipped: list[str] = []
    used = 0
    for file in files:
        if file.is_lockfile:
            added, removed = file.line_counts
            lockfiles.append(f"{file.path} (+{added} -{removed})")
        elif used + len(file.text) <= max_chars:
            shown.append(file.text)
            used += len(file.text)
        else:
            skipped.append(file.path)
    notes = []
    if lockfiles:
        notes.append("[lockfiles, content not shown: " + ", ".join(lockfiles) + "]")
    if skipped:
        notes.append("[diff truncated, these files are not shown, read them directly: " + ", ".join(skipped) + "]")
    return "".join(shown) + ("\n" + "\n".join(notes) if notes else "")
