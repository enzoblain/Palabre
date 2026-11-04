"""The only place that calls the VM tool (Tart); the worker knows only clone, start, exec, delete and list."""

import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass

VM_PREFIX = "job-"
DEFAULT_COMMAND_TIMEOUT_SECONDS = 600
CLONE_TIMEOUT_SECONDS = 1800
STOP_GRACE_SECONDS = 5
STOP_TIMEOUT_SECONDS = 30
PROCESS_WAIT_SECONDS = 30
DELETE_TIMEOUT_SECONDS = 120
LIST_TIMEOUT_SECONDS = 60
ERROR_TAIL_CHARS = 300


@dataclass(frozen=True)
class ExecResult:
    returncode: int
    output: str
    timed_out: bool


class TartVm:
    """Tart commands, one VM per job. Swapping the tool (Lume) means rewriting this class only."""

    def __init__(self, binary: str = "tart", net_args: Sequence[str] = ()) -> None:
        self._binary = binary
        self._net_args = list(net_args)
        self._running: dict[str, subprocess.Popen[bytes]] = {}

    def _run(self, *args: str, timeout: float = DEFAULT_COMMAND_TIMEOUT_SECONDS) -> subprocess.CompletedProcess[str]:
        return subprocess.run([self._binary, *args], capture_output=True, text=True, timeout=timeout, check=False)

    def clone(self, image: str, name: str) -> None:
        result = self._run("clone", image, name, timeout=CLONE_TIMEOUT_SECONDS)
        if result.returncode != 0:
            raise RuntimeError(f"tart clone failed: {result.stderr.strip()[-ERROR_TAIL_CHARS:]}")

    def start(self, name: str) -> None:
        """Boots the VM without a window, in the background; no shared folder is ever passed."""
        command = [self._binary, "run", "--no-graphics", *self._net_args, name]
        self._running[name] = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def is_alive(self, name: str) -> bool:
        process = self._running.get(name)
        return process is not None and process.poll() is None

    def exec(self, name: str, command: Sequence[str], stdin: str, timeout: float, max_output: int) -> ExecResult:
        """Runs a command in the guest; `stdin` carries the secrets so they never show in a process list."""
        process = subprocess.Popen(
            [self._binary, "exec", "-i", name, *command],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )  # fmt: skip
        try:
            output, _ = process.communicate(stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate()
            return ExecResult(-1, (output or "")[-max_output:], True)
        return ExecResult(process.returncode, (output or "")[-max_output:], False)

    def delete(self, name: str) -> None:
        """Stops and removes the VM; every step is tried even if the previous one failed, so `delete` always runs.

        Raises the last error only after all steps ran, so the caller can log a leftover.
        """
        process = self._running.pop(name, None)
        errors: list[Exception] = []
        try:
            self._run("stop", name, "--timeout", str(STOP_GRACE_SECONDS), timeout=STOP_TIMEOUT_SECONDS)
        except (subprocess.SubprocessError, OSError) as error:
            errors.append(error)
        if process is not None:
            try:
                process.wait(timeout=PROCESS_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
        try:
            self._run("delete", name, timeout=DELETE_TIMEOUT_SECONDS)
        except (subprocess.SubprocessError, OSError) as error:
            errors.append(error)
        if errors:
            raise RuntimeError(f"tart cleanup of {name} incomplete: {errors[-1]}")

    def list(self) -> list[str]:
        result = self._run("list", "--source", "local", "--format", "json", timeout=LIST_TIMEOUT_SECONDS)
        if result.returncode != 0:
            raise RuntimeError(f"tart list failed: {result.stderr.strip()[-ERROR_TAIL_CHARS:]}")
        return [str(vm["Name"]) for vm in json.loads(result.stdout or "[]")]
