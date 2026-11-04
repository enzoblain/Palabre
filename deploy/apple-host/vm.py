"""The only place that calls the VM tool (Tart); the worker knows only clone, start, exec, delete and list."""

import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass

VM_PREFIX = "job-"


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

    def _run(self, *args: str, timeout: float = 600) -> subprocess.CompletedProcess[str]:
        return subprocess.run([self._binary, *args], capture_output=True, text=True, timeout=timeout, check=False)

    def clone(self, image: str, name: str) -> None:
        result = self._run("clone", image, name, timeout=1800)
        if result.returncode != 0:
            raise RuntimeError(f"tart clone failed: {result.stderr.strip()[-300:]}")

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
        """Stops and removes the VM; never raises, the caller logs a leftover."""
        process = self._running.pop(name, None)
        self._run("stop", name, "--timeout", "5")
        if process is not None:
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
        self._run("delete", name)

    def list(self) -> list[str]:
        result = self._run("list", "--source", "local", "--format", "json", timeout=60)
        if result.returncode != 0:
            raise RuntimeError(f"tart list failed: {result.stderr.strip()[-300:]}")
        return [str(vm["Name"]) for vm in json.loads(result.stdout or "[]")]
