"""Release arithmetic without any I/O: next SemVer version, version files and CHANGELOG entry."""

import re

from app.github import COMMIT_TITLE_RE

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
# Keep a Changelog sections, by Conventional Commits type; other types (chore, docs, test...) are not listed
CHANGELOG_SECTIONS = {"feat": "Added", "fix": "Fixed", "perf": "Changed", "refactor": "Changed"}
SECTION_ORDER = ["Added", "Changed", "Fixed"]


def is_release_commit(message: str) -> bool:
    """The version bump itself: it never counts as a change to publish."""
    return message.lstrip().startswith("chore(release)")


def _parse(message: str) -> tuple[str, str, bool, str] | None:
    """(type, description with scope, breaking, ...) of a Conventional Commits message; None for others."""
    title, _, body = message.strip().partition("\n")
    match = COMMIT_TITLE_RE.match(title.strip())
    if not match:
        return None
    desc = f"{match['scope']}: {match['desc']}" if match["scope"] else match["desc"]
    breaking = bool(match["bang"]) or "BREAKING CHANGE" in body
    return match["type"], desc, breaking, title


def bump_level(commits: list[str]) -> str | None:
    """"major", "minor" or "patch" from the commits, None if none of them is worth a release."""
    level = None
    for message in commits:
        parsed = _parse(message)
        if parsed is None or is_release_commit(message):
            continue
        kind, _, breaking, _ = parsed
        if breaking:
            return "major"
        if kind == "feat":
            level = "minor"
        elif kind in ("fix", "perf") and level is None:
            level = "patch"
    return level


def next_version(current: str, commits: list[str]) -> str | None:
    """The version after `current` (X.Y.Z), per SemVer 2.0.0 and the Conventional Commits: fix and perf
    patch, feat minor, a breaking change major (minor while in 0.x). None when nothing deserves a release."""
    level = bump_level(commits)
    if level is None:
        return None
    major, minor, patch = (int(n) for n in current.split("."))
    if level == "major" and major == 0:
        level = "minor"
    if level == "major":
        return f"{major + 1}.0.0"
    return f"{major}.{minor + 1}.0" if level == "minor" else f"{major}.{minor}.{patch + 1}"


def changelog_body(commits: list[str]) -> str:
    """The sections of a Keep a Changelog entry, from the commits that change something for users."""
    sections: dict[str, list[str]] = {}
    for message in commits:
        parsed = _parse(message)
        if parsed is None or is_release_commit(message):
            continue
        kind, desc, breaking, _ = parsed
        name = CHANGELOG_SECTIONS.get(kind)
        if name is None and not breaking:
            continue
        line = desc
        sections.setdefault(name or "Changed", []).append(f"**Breaking:** {line}" if breaking else line)
    return "\n\n".join(f"### {name}\n\n" + "\n".join(f"- {line}" for line in sections[name]) for name in SECTION_ORDER if name in sections)


def changelog_entry(version: str, date: str, commits: list[str]) -> str:
    return f"## [{version}] - {date}\n\n{changelog_body(commits)}\n"


def entry_date(text: str, version: str) -> str | None:
    """The date of the `## [version] - date` entry already in the changelog, if any."""
    match = re.search(rf"(?m)^## \[{re.escape(version)}\] - (\S+)$", text)
    return match[1] if match else None


def update_changelog(text: str, version: str, previous: str | None, entry: str) -> str:
    """Replace the content of [Unreleased] by `entry` (the changelog is generated, nobody edits it by hand),
    drop the entries of versions never released (newer than `previous`: a stale bump) and move the links on."""
    if "## [Unreleased]" not in text:
        raise ValueError("CHANGELOG.md has no [Unreleased] section")
    head, _, rest = text.partition("## [Unreleased]\n")
    sections = re.split(r"(?m)^(?=## \[)", rest)
    kept = [sec for sec in sections[1:] if not _newer(sec, previous)]
    tail = "".join(kept)
    text = f"{head}## [Unreleased]\n\n{entry}\n{tail}"
    stale = {m[1] for sec in sections[1:] if _newer(sec, previous) for m in [re.match(r"## \[([^\]]+)\]", sec)]}
    text = "".join(line for line in text.splitlines(keepends=True) if not any(line.startswith(f"[{v}]:") for v in stale))
    link = re.search(r"^\[Unreleased\]: (?P<base>\S+?)/compare/\S+$", text, re.M)
    if link:
        base = link["base"]
        new = f"[Unreleased]: {base}/compare/v{version}...HEAD"
        if previous:
            new += f"\n[{version}]: {base}/compare/v{previous}...v{version}"
        text = text[: link.start()] + new + text[link.end():]
    return re.sub(r"\n{3,}", "\n\n", text)


def _newer(section: str, previous: str | None) -> bool:
    """Whether a `## [X.Y.Z]` section is a version after `previous` (so not released)."""
    match = re.match(r"## \[(\d+)\.(\d+)\.(\d+)\]", section)
    if not match or previous is None:
        return False  # Without a tag, nothing proves a section was never released: keep it
    return tuple(int(n) for n in match.groups()) > tuple(int(n) for n in previous.split("."))


def set_version(path: str, text: str, version: str, package: str = "") -> str:
    """`text` of a version file with its version replaced; unchanged if the file is not one we know."""
    name = path.rsplit("/", 1)[-1]
    top = re.compile(r'(?m)^(  "version": ")[^"]*(")')
    if name in ("package.json", "tauri.conf.json"):
        return top.sub(rf"\g<1>{version}\g<2>", text, count=1)
    if name == "package-lock.json":
        text = top.sub(rf"\g<1>{version}\g<2>", text, count=1)
        return re.sub(r'(\n    "": \{[^}]*?"version": ")[^"]*(")', rf"\g<1>{version}\g<2>", text, count=1)
    if name == "Cargo.toml":
        return re.sub(r'(?m)^(version = ")[^"]*(")', rf"\g<1>{version}\g<2>", text, count=1)
    if name == "docker-compose.yml":  # The pinned image version, so the compose file and its images match
        return re.sub(r"(\$\{PALABRE_VERSION:-)[^}]*(\})", rf"\g<1>{version}\g<2>", text)
    if name == "Cargo.lock" and package:
        return re.sub(rf'(name = "{re.escape(package)}"\nversion = ")[^"]*(")', rf"\g<1>{version}\g<2>", text, count=1)
    return text
