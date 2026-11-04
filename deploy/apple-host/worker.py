"""Host worker of the Mac builder: polls the backend, builds each job in a throw-away VM, reports, deletes the VM."""

import argparse
import json
import logging
import re
import stat
import subprocess
import threading
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from vm import VM_PREFIX, ExecResult, TartVm

log = logging.getLogger("palabre-worker")

APPLE_MAX_VMS = 2  # Apple's licence limit per Mac
EXIT_PASSED = 0
EXIT_FAILED = 10  # the guest runner's code for a build or test failure; any other code is an infra error
HEARTBEAT_SECONDS = 15
RUNNER_PATH = "/usr/local/bin/palabre-job-runner"
LOG_MAX_BYTES = 200_000
HTTP_TIMEOUT_SECONDS = 30
RESULT_ATTEMPTS = 5
BOOT_ATTEMPTS = 60  # one try every 5 s: a macOS guest needs a while before `tart exec` answers
BOOT_RETRY_SECONDS = 5
DEFAULT_JOB_TIMEOUT_SECONDS = 1800
DEFAULT_POLL_INTERVAL_SECONDS = 5
GUEST_PROBE_COMMAND = ["/usr/bin/true"]  # answers 0 once the guest agent is up, whatever the job is
# The VM runs untrusted code: it must never reach the Mac or the LAN. Always applied, the config can only add to them.
BLOCKED_NETWORKS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")
ISOLATION_NET_ARGS = ("--net-softnet", *(f"--net-softnet-block={network}" for network in BLOCKED_NETWORKS))
PF_ANCHOR = "palabre/apple-vm"
PF_ANCHOR_LABELS = ("palabre-apple-vm-dns", "palabre-apple-vm-private", "palabre-apple-vm-mac")
PF_READ_COMMAND = ("sudo", "-n", "/sbin/pfctl", "-a", PF_ANCHOR, "-s", "rules")  # the one command sudoers allows
PF_READ_TIMEOUT_SECONDS = 10
IMAGE_PATTERN = re.compile(r"^[\w./-]+@sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class Config:
    backend_url: str
    token_file: Path
    image: str
    max_vms: int = APPLE_MAX_VMS
    job_timeout_seconds: int = DEFAULT_JOB_TIMEOUT_SECONDS
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS
    net_args: tuple[str, ...] = ISOLATION_NET_ARGS


def load_config(path: Path) -> Config:
    """Reads the config file; it must hold no secret, only the path of the token file."""
    raw = tomllib.loads(path.read_text())
    image = str(raw["image"])
    if not IMAGE_PATTERN.match(image):
        raise ValueError("image must be pinned by digest (name@sha256:...)")
    backend_url = str(raw["backend_url"]).rstrip("/")
    if not backend_url.startswith("https://"):
        raise ValueError("backend_url must use https://")
    max_vms = int(raw.get("max_vms", APPLE_MAX_VMS))
    if not 1 <= max_vms <= APPLE_MAX_VMS:
        raise ValueError(f"max_vms must be between 1 and {APPLE_MAX_VMS}")
    return Config(
        backend_url=backend_url, token_file=Path(raw["token_file"]), image=image,
        max_vms=max_vms, job_timeout_seconds=int(raw.get("job_timeout_seconds", DEFAULT_JOB_TIMEOUT_SECONDS)),
        poll_interval_seconds=int(raw.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS)),
        net_args=ISOLATION_NET_ARGS + tuple(str(arg) for arg in raw.get("net_extra_args", [])),
    )  # fmt: skip


def require_pf_anchor(read_rules: Callable[[], str] | None = None) -> None:
    """Second network barrier: refuses to start unless the pf anchor that blocks the LAN and the Mac is loaded."""
    try:
        rules = (read_rules or _read_pf_rules)()
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(f"cannot read the pf anchor {PF_ANCHOR}; run install.sh again") from error
    missing = [label for label in PF_ANCHOR_LABELS if label not in rules]
    if missing:
        raise RuntimeError(
            f"the pf anchor {PF_ANCHOR} is not active (missing rules: {', '.join(missing)}); run install.sh again"
        )


def _read_pf_rules() -> str:
    result = subprocess.run(
        PF_READ_COMMAND, capture_output=True, text=True, timeout=PF_READ_TIMEOUT_SECONDS, check=False
    )
    if result.returncode != 0:
        raise OSError(result.stderr.strip()[-200:])
    return result.stdout


def read_host_token(path: Path) -> str:
    """The builder token, refused if other users can read the file."""
    if path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise PermissionError(f"{path} must be readable by its owner only (chmod 600)")
    return path.read_text().strip()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuses redirects so a proxy cannot make the Authorization header leave for another host."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


class Vm(Protocol):
    def clone(self, image: str, name: str) -> None: ...
    def start(self, name: str) -> None: ...
    def is_alive(self, name: str) -> bool: ...
    def exec(self, name: str, command: Sequence[str], stdin: str, timeout: float, max_output: int) -> ExecResult: ...
    def delete(self, name: str) -> None: ...
    def list(self) -> list[str]: ...


class Backend(Protocol):
    def claim(self) -> dict[str, Any] | None: ...
    def heartbeat(self) -> None: ...
    def result(self, job: dict[str, Any], status: str, log_excerpt: str) -> None: ...


class HttpBackend:
    """The `/api/apple-host/*` calls; the host token is only used on claim and heartbeat."""

    def __init__(self, base_url: str, host_token: str) -> None:
        self._base = base_url
        self._host_token = host_token

    def _call(self, method: str, path: str, token: str, body: dict[str, Any] | None = None) -> tuple[int, bytes]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self._base + path, data=data, method=method)
        request.add_header("Authorization", f"Bearer {token}")
        request.add_header("Content-Type", "application/json")
        try:
            with _OPENER.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, b""

    def claim(self) -> dict[str, Any] | None:
        code, body = self._call("POST", "/api/apple-host/claim", self._host_token)
        if code == 204:
            return None
        if code != 200:
            raise RuntimeError(f"claim answered {code}")
        return json.loads(body)

    def heartbeat(self) -> None:
        code, _ = self._call("POST", "/api/apple-host/heartbeat", self._host_token)
        if code != 204:
            raise RuntimeError(f"heartbeat answered {code}")

    def result(self, job: dict[str, Any], status: str, log_excerpt: str) -> None:
        code, _ = self._call(
            "POST", f"/api/apple-host/jobs/{job['id']}/result", job["job_token"],
            {"status": status, "log_excerpt": log_excerpt},
        )  # fmt: skip
        if code != 204:
            raise RuntimeError(f"result answered {code}")


def redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def verdict(result: ExecResult) -> str:
    """A broken test is `failed`; a timeout, a crashed guest or an unknown exit code is an infra `error`."""
    if result.timed_out:
        return "error"
    if result.returncode == EXIT_PASSED:
        return "passed"
    return "failed" if result.returncode == EXIT_FAILED else "error"


class Worker:
    def __init__(self, config: Config, backend: Backend, vm: Vm, sleep: Callable[[float], None] = time.sleep) -> None:
        self._config = config
        self._backend = backend
        self._vm = vm
        self._sleep = sleep
        self._slots = threading.BoundedSemaphore(config.max_vms)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def stop(self) -> None:
        self._stop.set()

    def cleanup_leftovers(self) -> None:
        """Deletes every job VM of a previous run: nothing survives a restart of the worker."""
        for name in self._vm.list():
            if name.startswith(VM_PREFIX):
                log.warning("deleting leftover VM %s", name)
                self._vm.delete(name)

    def run_forever(self) -> None:
        self.cleanup_leftovers()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        while not self._stop.is_set():
            self.poll_once()
        for thread in self._threads:
            thread.join()

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(HEARTBEAT_SECONDS):
            try:
                self._backend.heartbeat()
            except Exception:
                log.exception("heartbeat failed")

    def poll_once(self) -> bool:
        """Waits for a free slot, claims one job and runs it in a thread. Returns whether a job started."""
        while not self._slots.acquire(timeout=1):
            if self._stop.is_set():
                return False
        try:
            job = self._backend.claim()
        except Exception:
            self._slots.release()
            log.exception("claim failed")
            self._sleep(self._config.poll_interval_seconds)
            return False
        if job is None:
            self._slots.release()
            self._sleep(self._config.poll_interval_seconds)
            return False
        thread = threading.Thread(target=self._run_slot, args=(job,))
        self._threads = [t for t in self._threads if t.is_alive()] + [thread]
        thread.start()
        return True

    def _run_slot(self, job: dict[str, Any]) -> None:
        try:
            self.process(job)
        finally:
            self._slots.release()

    def process(self, job: dict[str, Any]) -> None:
        """One job: fresh VM, build, delete the VM whatever happened, then report."""
        name = f"{VM_PREFIX}{int(job['id'])}"
        status, excerpt = "error", "Mac builder failed before the build started"
        try:
            status, excerpt = self._build(job, name)
        except Exception as error:
            log.exception("job %s failed", name)
            excerpt = f"Mac builder error: {type(error).__name__}"
        finally:
            self._destroy(name)
        self._report(job, status, redact(excerpt, [job["job_token"]]))

    def _build(self, job: dict[str, Any], name: str) -> tuple[str, str]:
        self._vm.clone(self._config.image, name)
        self._vm.start(name)
        command = [RUNNER_PATH, self._config.backend_url, str(int(job["id"])), job["source_url"], job["commit_sha"]]
        deadline = time.monotonic() + self._config.job_timeout_seconds
        result = self._exec_when_booted(name, command, job["job_token"], deadline)
        if result.timed_out:
            return "error", f"Time limit of {self._config.job_timeout_seconds} s reached\n{result.output}"
        if not self._vm.is_alive(name) and verdict(result) == "error":
            return "error", f"The VM stopped unexpectedly\n{result.output}"
        return verdict(result), result.output

    def _exec_when_booted(self, name: str, command: list[str], token: str, deadline: float) -> ExecResult:
        """Probes the guest until it answers, then runs the job once, all within the job's time limit.

        The probe is a command of ours, so a job that fails never looks like a guest that is not ready
        and is never run twice.
        """
        for _ in range(BOOT_ATTEMPTS):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return ExecResult(-1, "VM did not become ready in time", True)
            if not self._vm.is_alive(name):
                return ExecResult(-1, "The VM stopped while booting", False)
            probe = self._vm.exec(name, GUEST_PROBE_COMMAND, "", remaining, LOG_MAX_BYTES)
            if probe.timed_out:
                return probe
            if probe.returncode == EXIT_PASSED:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return ExecResult(-1, "", True)
                return self._vm.exec(name, command, token + "\n", remaining, LOG_MAX_BYTES)
            self._sleep(BOOT_RETRY_SECONDS)
        return ExecResult(-1, "VM did not become ready", False)

    def _destroy(self, name: str) -> None:
        try:
            self._vm.delete(name)
        except Exception:
            log.exception("could not delete %s; it is removed at the next start", name)

    def _report(self, job: dict[str, Any], status: str, excerpt: str) -> None:
        for attempt in range(RESULT_ATTEMPTS):
            try:
                self._backend.result(job, status, excerpt[-LOG_MAX_BYTES:])
                return
            except Exception:
                log.exception("result of job %s not delivered (attempt %d)", job["id"], attempt + 1)
                self._sleep(2**attempt)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("/etc/palabre-apple-worker.toml"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(args.config)
    require_pf_anchor()
    backend = HttpBackend(config.backend_url, read_host_token(config.token_file))
    Worker(config, backend, TartVm(net_args=config.net_args)).run_forever()


if __name__ == "__main__":
    main()
