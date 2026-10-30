"""Agent account pool inside the real image: run by check-isolation.sh as the palabre user (#162).

Same stub `claude` as check_isolation_flow.py, so the runs go through the real runner and the real
lease (sudo -u agentN, MCP config, process group, kill when the account goes back to the pool).
Needs no GitHub access. Prints `ok   ...` / `FAIL ...` lines; exit code 1 on any FAIL.
"""

import asyncio
import subprocess
import sys
from pathlib import Path

from app import agent_pool, runner, worktrees
from app.config import settings
from app.runner import RunSpec

failed = False
PROJECT_ID = 99998
UID_BASE = 2000  # agentN has uid 2000 + N (see the Dockerfile)
SLEEP = "sleep 4242"  # what a run leaves behind, recognisable among the other sleeps


def report(ok: bool, desc: str) -> None:
    global failed
    failed |= not ok
    print(f"{'ok  ' if ok else 'FAIL'} {desc}", flush=True)


def spec(prompt: str, cwd: Path) -> RunSpec:
    return RunSpec(
        author_name="Check Bot", system_prompt="x", prompt=prompt, cwd=cwd, employee_id=0,
        mcp_headers={}, mcp_tools=[], claude_tools=["Read"], model="x", oauth_token="check-token",
    )  # fmt: skip


def parse(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def left_behind(uid: str) -> list[str]:
    out = subprocess.run(["pgrep", "-u", uid, "-f", SLEEP], capture_output=True, text=True)
    return out.stdout.split()


async def concurrent_runs(cwd: Path) -> None:
    """Two live runs at once: each tries to read the other's environment and MCP config."""
    settings.agent_pool_size = 2
    agent_pool.reset()
    a, b = await asyncio.gather(
        runner.run_claude(spec(f"pair {cwd} a b", cwd)), runner.run_claude(spec(f"pair {cwd} b a", cwd))
    )
    a, b = parse(a.text), parse(b.text)
    uids = {a.get("uid"), b.get("uid")}
    report(
        len(uids) == 2 and all(u and int(u) > UID_BASE for u in uids),
        f"two simultaneous runs have two different pool uids (got {a.get('uid')} and {b.get('uid')})",
    )
    for name, got in (("first run", a), ("second run", b)):
        report(got.get("peer") == "found", f"the {name} was alive together with the other (else the checks mean nothing)")
        report(got.get("ownenviron") == "allowed" and got.get("ownmcp") == "ok", f"the {name} reads its own environ and MCP config")
        report(got.get("environ") == "denied", f"the {name} cannot read the other run's /proc/<pid>/environ")
        report(got.get("mcpconfig") == "denied", f"the {name} cannot read the other run's MCP config")


async def leftover_process(cwd: Path) -> None:
    """A process a run leaves behind (setsid) is gone when the account is leased again."""
    settings.agent_pool_size = 1  # every run gets agent1 again
    agent_pool.reset()
    first = parse((await runner.run_claude(spec(f"leave {cwd}", cwd))).text)
    uid = first.get("uid") or ""
    report(first.get("alive") == "1", "the first run left a setsid process behind (else the check means nothing)")
    await asyncio.sleep(1)
    report(not left_behind(uid), f"the process is killed when the account goes back to the pool ({left_behind(uid)})")
    second = parse((await runner.run_claude(spec(f"seen {cwd}", cwd))).text)
    report(second.get("uid") == uid, f"the next run gets the same account (uid {uid}, got {second.get('uid')})")
    report(second.get("alive") == "0", "the run that re-leases the account finds nothing left by the previous one")


async def main() -> None:
    report(settings.agent_pool_size > 0, f"AGENT_POOL_SIZE is set in the image (got {settings.agent_pool_size})")
    image_pool = settings.agent_pool_size
    scratch = settings.projects_dir / f"project-{PROJECT_ID}" / "worktrees" / "scratch"
    scratch.mkdir(mode=0o2775, parents=True, exist_ok=True)
    scratch.chmod(0o2775)
    try:
        if image_pool >= 2:
            await concurrent_runs(scratch)
            await leftover_process(scratch)
        else:
            report(False, "the image has fewer than two pool accounts")
    finally:
        settings.agent_pool_size = image_pool
        agent_pool.reset()
        await worktrees.remove_project_files(PROJECT_ID)


asyncio.run(main())
sys.exit(1 if failed else 0)
