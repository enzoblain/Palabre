"""Builds the GitHub ::error annotation of a failed test report (file, line, test name)."""


def annotation(report) -> str:
    # Collection reports (import errors) have no line: point at the top of the module
    path, line, _ = getattr(report, "location", None) or (report.nodeid.split("::")[0], 0, "")
    crash = getattr(report.longrepr, "reprcrash", None)
    message = getattr(crash, "message", None) or "failed"

    def esc(text: str, prop: bool = False) -> str:
        text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        return text.replace(":", "%3A").replace(",", "%2C") if prop else text

    # Paths are relative to backend/ for pytest, to the repository root for annotations;
    # pytest's line is 0-based
    return (
        f"::error file={esc('backend/' + path, True)},line={(line or 0) + 1},"
        f"title={esc(report.nodeid, True)}::{esc(f'{report.nodeid} - {message}')}"
    )
