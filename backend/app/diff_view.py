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
# Registries a lockfile may point to without drawing attention; any other source URL on an added line is listed
DEFAULT_REGISTRY_PREFIXES = (
    "https://registry.npmjs.org/",
    "https://registry.yarnpkg.com/",
    "https://pypi.org/",
    "https://files.pythonhosted.org/",
    "https://index.crates.io/",
    "https://static.crates.io/",
    "https://rubygems.org/",
    "https://repo.packagist.org/",
    "https://proxy.golang.org/",
    "https://github.com/rust-lang/crates.io-index",
)
MAX_FLAGGED_LINES_PER_LOCKFILE = 10
MAX_FLAGGED_LINE_CHARS = 200
LOCKFILE_REVIEW_HINT = "review dependency changes in the file"
_SOURCE_URL = re.compile(r"(?:[a-z+]+)://[^\s\"',)]+", re.IGNORECASE)
_FILE_HEADER = re.compile(r"^diff --git (.*)$", re.MULTILINE)
_PLAIN_NEW_PATH = re.compile(r" b/(.+)$")
_QUOTED_NEW_PATH = re.compile(r'"b/((?:[^"\\]|\\.)*)"$')
_ESCAPE = re.compile(rb"\\([0-7]{3}|.)", re.DOTALL)
_SIMPLE_ESCAPES = {"t": b"\t", "n": b"\n", "r": b"\r", "a": b"\a", "b": b"\b", "f": b"\f", "v": b"\v"}
PREAMBLE_LABEL = "(text before the first file)"


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


    @property
    def non_default_source_lines(self) -> list[str]:
        """Added lines pointing to a URL outside the default registries (the content is hidden otherwise)."""
        _, _, hunks = self.text.partition("\n@@")
        added = (line[1:].strip() for line in hunks.split("\n")[1:] if line.startswith("+"))
        return [
            line for line in added
            if any(not url.startswith(DEFAULT_REGISTRY_PREFIXES) for url in _SOURCE_URL.findall(line))
        ]


def _unquote_path(quoted: str) -> str:
    """Decodes the C-style escapes git applies to unusual paths (octal bytes are UTF-8)."""
    def decode(match: re.Match[bytes]) -> bytes:
        token = match.group(1)
        return bytes([int(token, 8)]) if len(token) == 3 and token.isdigit() else _SIMPLE_ESCAPES.get(token.decode(), token)
    return _ESCAPE.sub(decode, quoted.encode()).decode("utf-8", errors="replace")


def _header_path(header_rest: str) -> str:
    """The new path of a `diff --git` header, quoted or not; the raw remainder if it is neither."""
    quoted = _QUOTED_NEW_PATH.search(header_rest)
    if quoted:
        return _unquote_path(quoted.group(1))
    plain = _PLAIN_NEW_PATH.search(header_rest)
    return plain.group(1) if plain else header_rest


def split_diff(diff: str) -> list[FileDiff]:
    """One FileDiff per file of a `git diff` output, in the order git printed them. Every
    `diff --git` line starts a file, whatever its path looks like; leading text is kept apart."""
    matches = list(_FILE_HEADER.finditer(diff))
    if not matches:
        return [FileDiff(path=PREAMBLE_LABEL, text=diff)] if diff else []
    starts = [match.start() for match in matches]
    ends = [*starts[1:], len(diff)]
    files = [
        FileDiff(path=_header_path(match.group(1)), text=diff[start:end])
        for match, start, end in zip(matches, starts, ends, strict=True)
    ]
    if starts[0] > 0:
        files.insert(0, FileDiff(path=PREAMBLE_LABEL, text=diff[: starts[0]]))
    return files


def _flagged_note(file: FileDiff) -> list[str]:
    """One note line per lockfile listing its added lines that use a non-default registry."""
    lines = file.non_default_source_lines
    if not lines:
        return []
    shown = [line[:MAX_FLAGGED_LINE_CHARS] for line in lines[:MAX_FLAGGED_LINES_PER_LOCKFILE]]
    more = len(lines) - len(shown)
    suffix = f"\n  ... and {more} more" if more else ""
    return [f"[{file.path}: added lines using a non-default registry:\n  " + "\n  ".join(shown) + suffix + "]"]


def render_diff(diff: str, max_chars: int = MAX_DIFF_CHARS) -> str:
    """The diff without lockfile content, cut by whole files at max_chars. What is not shown
    (lockfiles, files that did not fit) is listed at the end so the reader knows what to open."""
    files = split_diff(diff)
    shown: list[str] = []
    lockfiles: list[str] = []
    flagged: list[str] = []
    skipped: list[str] = []
    used = 0
    for file in files:
        if file.is_lockfile:
            added, removed = file.line_counts
            lockfiles.append(f"{file.path} (+{added} -{removed})")
            flagged.extend(_flagged_note(file))
        elif used + len(file.text) <= max_chars:
            shown.append(file.text)
            used += len(file.text)
        else:
            skipped.append(file.path)
    notes = []
    if lockfiles:
        notes.append(f"[lockfiles, content not shown, {LOCKFILE_REVIEW_HINT}: " + ", ".join(lockfiles) + "]")
        notes.extend(flagged)
    if skipped:
        notes.append("[diff truncated, these files are not shown, read them directly: " + ", ".join(skipped) + "]")
    return "".join(shown) + ("\n" + "\n".join(notes) if notes else "")
