"""Unit tests of the Mac worker logic with a fake VM tool and a fake backend: no Mac, no Tart."""

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

import worker  # noqa: E402
from vm import ExecResult  # noqa: E402

DIGEST = "ghcr.io/example/macos-xcode@sha256:" + "a" * 64


def make_config(**overrides: Any) -> worker.Config:
    values: dict[str, Any] = {
        "backend_url": "https://palabre.example", "token_file": Path("/nonexistent"), "image": DIGEST,
        "job_timeout_seconds": 60, "poll_interval_seconds": 0,
    }  # fmt: skip
    return worker.Config(**{**values, **overrides})


def make_job(job_id: int) -> dict[str, Any]:
    return {"id": job_id, "job_token": f"pjob_secret{job_id}", "source_url": f"/api/apple-host/jobs/{job_id}/source",
            "commit_sha": "c" * 40, "branch": "task/1", "project_id": 1}  # fmt: skip


class FakeVm:
    def __init__(self, exec_result: ExecResult | None = None, hold: float = 0, fail_clone: bool = False) -> None:
        self.exec_result = exec_result or ExecResult(0, "ok", False)
        self.hold = hold
        self.fail_clone = fail_clone
        self.existing: list[str] = []
        self.lock = threading.Lock()
        self.live = 0
        self.max_live = 0
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.stdin: list[str] = []
        self.dead = False

    def clone(self, image: str, name: str) -> None:
        if self.fail_clone:
            raise RuntimeError("clone failed")
        with self.lock:
            self.live += 1
            self.max_live = max(self.max_live, self.live)
            self.created.append(name)

    def start(self, name: str) -> None:
        pass

    def is_alive(self, name: str) -> bool:
        return not self.dead

    def exec(self, name: str, command: Any, stdin: str, timeout: float, max_output: int) -> ExecResult:
        self.stdin.append(stdin)
        time.sleep(self.hold)
        return self.exec_result

    def delete(self, name: str) -> None:
        with self.lock:
            if name in self.created:
                self.live -= 1
            self.deleted.append(name)

    def list(self) -> list[str]:
        return self.existing


class FakeBackend:
    def __init__(self, jobs: list[dict[str, Any]]) -> None:
        self.jobs = jobs
        self.results: list[tuple[int, str, str]] = []
        self.fail_results = 0
        self.lock = threading.Lock()

    def claim(self) -> dict[str, Any] | None:
        with self.lock:
            return self.jobs.pop(0) if self.jobs else None

    def heartbeat(self) -> None:
        pass

    def result(self, job: dict[str, Any], status: str, log_excerpt: str) -> None:
        if self.fail_results:
            self.fail_results -= 1
            raise RuntimeError("network")
        self.results.append((job["id"], status, log_excerpt))


def make_worker(vm: FakeVm, backend: FakeBackend, **config: Any) -> worker.Worker:
    return worker.Worker(make_config(**config), backend, vm, sleep=lambda _: None)  # type: ignore[arg-type]


class VerdictTest(unittest.TestCase):
    def test_exit_codes(self) -> None:
        self.assertEqual(worker.verdict(ExecResult(0, "", False)), "passed")
        self.assertEqual(worker.verdict(ExecResult(worker.EXIT_FAILED, "", False)), "failed")
        self.assertEqual(worker.verdict(ExecResult(137, "", False)), "error")
        self.assertEqual(worker.verdict(ExecResult(-1, "", True)), "error")


class ProcessTest(unittest.TestCase):
    def run_job(self, vm: FakeVm, **config: Any) -> FakeBackend:
        backend = FakeBackend([])
        make_worker(vm, backend, **config).process(make_job(7))
        return backend

    def test_passed_job_deletes_vm_and_sends_token_on_stdin_only(self) -> None:
        vm = FakeVm()
        backend = self.run_job(vm)
        self.assertEqual(backend.results, [(7, "passed", "ok")])
        self.assertEqual(vm.created, ["job-7"])
        self.assertEqual(vm.deleted, ["job-7"])
        self.assertEqual(vm.stdin, ["pjob_secret7\n"])

    def test_broken_test_is_failed(self) -> None:
        backend = self.run_job(FakeVm(ExecResult(worker.EXIT_FAILED, "1 test failed", False)))
        self.assertEqual(backend.results[0][1], "failed")

    def test_timeout_is_infra_error_and_vm_deleted(self) -> None:
        vm = FakeVm(ExecResult(-1, "partial", True))
        backend = self.run_job(vm)
        self.assertEqual(backend.results[0][1], "error")
        self.assertIn("Time limit", backend.results[0][2])
        self.assertEqual(vm.deleted, ["job-7"])

    def test_crashed_vm_is_infra_error(self) -> None:
        vm = FakeVm(ExecResult(255, "lost", False))
        vm.dead = True
        backend = self.run_job(vm)
        self.assertEqual(backend.results[0][1], "error")
        self.assertEqual(vm.deleted, ["job-7"])

    def test_clone_failure_is_error_and_still_cleans(self) -> None:
        vm = FakeVm(fail_clone=True)
        backend = self.run_job(vm)
        self.assertEqual(backend.results[0][1], "error")
        self.assertEqual(vm.deleted, ["job-7"])

    def test_exception_in_exec_still_deletes(self) -> None:
        vm = FakeVm()
        vm.exec = lambda *a, **k: (_ for _ in ()).throw(OSError("boom"))  # type: ignore[method-assign]
        backend = self.run_job(vm)
        self.assertEqual(backend.results[0][1], "error")
        self.assertEqual(vm.deleted, ["job-7"])

    def test_token_is_redacted_from_the_log(self) -> None:
        backend = self.run_job(FakeVm(ExecResult(0, "token pjob_secret7 leaked", False)))
        self.assertNotIn("pjob_secret7", backend.results[0][2])

    def test_result_delivery_is_retried(self) -> None:
        backend = FakeBackend([])
        backend.fail_results = 2
        make_worker(FakeVm(), backend).process(make_job(7))
        self.assertEqual(len(backend.results), 1)


class QueueTest(unittest.TestCase):
    def drain(self, count: int, max_vms: int = 2) -> tuple[FakeVm, FakeBackend]:
        vm = FakeVm(hold=0.05)
        backend = FakeBackend([make_job(i) for i in range(1, count + 1)])
        w = make_worker(vm, backend, max_vms=max_vms)
        while backend.jobs or w._threads and any(t.is_alive() for t in w._threads):
            w.poll_once()
        for thread in w._threads:
            thread.join()
        return vm, backend

    def test_never_more_than_two_vms_and_all_jobs_finish(self) -> None:
        vm, backend = self.drain(6)
        self.assertEqual(len(backend.results), 6)
        self.assertLessEqual(vm.max_live, 2)
        self.assertEqual(sorted(vm.deleted), sorted(vm.created))

    def test_max_vms_one_serialises(self) -> None:
        vm, _ = self.drain(3, max_vms=1)
        self.assertEqual(vm.max_live, 1)

    def test_slot_is_released_when_claim_finds_nothing(self) -> None:
        w = make_worker(FakeVm(), FakeBackend([]))
        for _ in range(5):
            self.assertFalse(w.poll_once())

    def test_leftover_job_vms_are_deleted_at_start(self) -> None:
        vm = FakeVm()
        vm.existing = ["job-3", "base-image", "job-9"]
        make_worker(vm, FakeBackend([])).cleanup_leftovers()
        self.assertEqual(vm.deleted, ["job-3", "job-9"])


class ConfigTest(unittest.TestCase):
    def write(self, directory: str, text: str) -> Path:
        path = Path(directory) / "w.toml"
        path.write_text(text)
        return path

    def test_unpinned_image_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self.write(d, 'backend_url="https://x"\ntoken_file="/t"\nimage="img:latest"\n')
            with self.assertRaises(ValueError):
                worker.load_config(path)

    def test_more_than_two_vms_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = self.write(d, f'backend_url="https://x"\ntoken_file="/t"\nimage="{DIGEST}"\nmax_vms=3\n')
            with self.assertRaises(ValueError):
                worker.load_config(path)

    def test_token_file_must_be_private(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            token = Path(d) / "token"
            token.write_text("pmac_x\n")
            os.chmod(token, 0o644)
            with self.assertRaises(PermissionError):
                worker.read_host_token(token)
            os.chmod(token, 0o600)
            self.assertEqual(worker.read_host_token(token), "pmac_x")


if __name__ == "__main__":
    unittest.main()
