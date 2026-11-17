"""Tests of the guest job runner with fake curl, git and swift (no Mac, no network)."""

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

RUNNER = Path(__file__).with_name("palabre-job-runner.sh")
TOKEN = "pjob_secret_token"


def fake(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class RunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.work = self.root / "work"
        self.args_log = self.root / "args.log"
        curl = 'echo "$@" >> ARGS; cat > /dev/null; while [ $# -gt 0 ]; do [ "$1" = --output ] && echo b > "$2"; shift; done'
        fake(self.bin, "curl", curl.replace("ARGS", str(self.args_log)))
        fake(self.bin, "git", "case $1 in clone) for last; do :; done; mkdir -p \"$last\";; esac; exit 0")
        fake(self.bin, "swift", "exit 0")

    def run_runner(self, stdin: str = TOKEN + "\n", args: list[str] | None = None) -> subprocess.CompletedProcess[str]:
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "PALABRE_BUILD_USER": "", "PALABRE_WORK_ROOT": str(self.work)}
        arguments = args or ["https://palabre.example.com", "7", "/api/apple-host/jobs/7/source", "abc123"]
        return subprocess.run([str(RUNNER), *arguments], input=stdin, capture_output=True, text=True, env=env, check=False)

    def test_passes_with_exit_zero_and_keeps_the_token_out_of_the_arguments(self) -> None:
        result = self.run_runner()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(TOKEN, self.args_log.read_text())
        self.assertFalse((self.work / "job-7").exists())

    def test_build_failure_exits_ten(self) -> None:
        fake(self.bin, "swift", "exit 1")
        self.assertEqual(self.run_runner().returncode, 10)
        self.assertFalse((self.work / "job-7").exists())

    def test_download_failure_is_an_infra_error(self) -> None:
        fake(self.bin, "curl", "cat > /dev/null; exit 22")
        result = self.run_runner()
        self.assertEqual(result.returncode, 20)
        self.assertNotIn(TOKEN, result.stderr)

    def test_missing_token_is_an_infra_error(self) -> None:
        self.assertEqual(self.run_runner(stdin="").returncode, 20)

    def test_refuses_plain_http_and_bad_arguments(self) -> None:
        self.assertEqual(self.run_runner(args=["http://x", "7", "/s", "abc"]).returncode, 20)
        self.assertEqual(self.run_runner(args=["https://x", "7;rm", "/s", "abc"]).returncode, 20)
        self.assertEqual(self.run_runner(args=["https://x"]).returncode, 20)

    def test_refuses_a_source_url_that_is_not_a_path(self) -> None:
        for source in ("https://evil.example.com/x", "api/source", ""):
            result = self.run_runner(args=["https://x", "7", source, "abc"])
            self.assertEqual(result.returncode, 20, source)
            self.assertFalse(self.args_log.exists())

    def test_refuses_a_token_outside_the_allowed_characters(self) -> None:
        for token in ('abc"\nurl = "https://evil.example.com', "abc def", "abc;x", "ab\\c"):
            result = self.run_runner(stdin=token + "\n")
            self.assertEqual(result.returncode, 20, token)
            self.assertFalse(self.args_log.exists())

    def test_refuses_an_invalid_commit_sha(self) -> None:
        for sha in ("xyz;", "ABC123", ""):
            args = ["https://x", "7", "/s", sha]
            self.assertEqual(self.run_runner(args=args).returncode, 20, sha)


if __name__ == "__main__":
    unittest.main()
