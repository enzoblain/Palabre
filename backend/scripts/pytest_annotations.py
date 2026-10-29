"""Turns a pytest log (-rfE --tb=line) into GitHub ::error annotations, one per failed test."""

import re
import sys

SUMMARY = re.compile(r"^(?:FAILED|ERROR) (\S+?\.py)(::\S.*?)?(?: - (.*))?$")
TB_LINE = re.compile(r"^(/?[^\s:][^:]*\.py):(\d+): ")


def escape(text: str, prop: bool = False) -> str:
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return text.replace(":", "%3A").replace(",", "%2C") if prop else text


def annotations(log: str) -> list[str]:
    lines = [line.rstrip() for line in log.splitlines()]
    # --tb=line gives "path:line: error" per failure, before the summary
    locations = [(m[1], int(m[2])) for line in lines if (m := TB_LINE.match(line))]
    out = []
    for line in lines:
        m = SUMMARY.match(line)
        if not m:
            continue
        path, test, message = m[1], m[2] or "", m[3] or "failed"
        found = next((n for p, n in locations if p.endswith(path) or path.endswith(p)), 1)
        title = f"{path}{test}"
        # Annotation paths are relative to the repository root, pytest's to backend/
        out.append(f"::error file={escape('backend/' + path, True)},line={found},title={escape(title, True)}::{escape(f'{title} - {message}')}")
    return out


if __name__ == "__main__":
    with open(sys.argv[1], errors="replace") as f:
        print("\n".join(annotations(f.read())))
