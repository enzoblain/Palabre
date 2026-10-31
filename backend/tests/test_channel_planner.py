"""Channels of a project: targeted catalog channels, and the model's plan for a custom team (runner mocked)."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app import projects
from app.company import channel_planner as planner
from app.models import Employee, Project, Room
from app.company.catalog import load_catalog
from app.company.team import generate_team
from app.runner import ClaudeRunError, RunResult

MEMBERS = [
    planner.Member(name="Ana", roles=["lead"]),
    planner.Member(name="Bob", roles=["dev_backend"]),
    planner.Member(name="Cy", roles=["dev_frontend"]),
    planner.Member(name="Di", roles=["qa"]),
]


def answer(text: str, is_error: bool = False) -> RunResult:
    return RunResult(session_id="s", text=text, is_error=is_error, num_turns=1, cost_usd=0)


@pytest.fixture
def run(monkeypatch):
    """Replaces the claude run: `run.result` is returned (or raised, or awaited forever)."""
    state = SimpleNamespace(result=answer("[]"), specs=[])

    async def fake(spec):
        state.specs.append(spec)
        if isinstance(state.result, BaseException):
            raise state.result
        if state.result == "hang":
            await asyncio.sleep(3600)
        return state.result

    monkeypatch.setattr(planner, "run_claude", fake)
    return state


async def plan():
    return await planner.plan_channels(MEMBERS, lead_id=1, lead_name="Ana", token="t", cwd="/tmp")


async def test_valid_plan_is_returned(run):
    run.result = answer(json.dumps([{"name": "dev", "members": ["Bob", "Cy"]}, {"name": "qa", "members": ["Di", "Ana"]}]))
    channels = await plan()
    assert [(c.name, c.members) for c in channels] == [("dev", ["Bob", "Cy"]), ("qa", ["Di", "Ana"])]
    spec = run.specs[0]
    assert spec.mcp_tools == [] and spec.claude_tools == [] and spec.employee_id == 1 and spec.oauth_token == "t"


async def test_code_fence_is_accepted(run):
    run.result = answer('```json\n[{"name": "dev", "members": ["Bob", "Cy"]}]\n```')
    assert [c.name for c in await plan()] == ["dev"]


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "{}",
        "[]",
        '[{"name": "dev", "members": ["Bob", "Zed"]}]',  # unknown member
        '[{"name": "dev", "members": ["Bob"]}]',  # fewer than 2
        '[{"name": "dev", "members": ["Bob", "Bob"]}]',  # twice the same member
        '[{"name": "dev", "members": ["Bob", "Cy"]}, {"name": "dev", "members": ["Di", "Cy"]}]',  # same name
        '[{"name": "Dev Team", "members": ["Bob", "Cy"]}]',  # bad name
        '[{"name": "direction", "members": ["Bob", "Cy"]}]',  # reserved
        '[{"name": "dev", "members": ["Bob", "Cy"], "x": 1}]',  # extra field
        '[{"name": "dev", "members": "Bob"}]',  # wrong type
        '[{"name": 3, "members": ["Bob", "Cy"]}]',
        json.dumps([{"name": f"c{i}", "members": ["Bob", "Cy"]} for i in range(7)]),  # too many
    ],
)
async def test_invalid_plan_falls_back(run, text, caplog):
    run.result = answer(text)
    assert await plan() is None
    assert "using the catalog" in caplog.text


async def test_run_error_and_error_result_fall_back(run):
    run.result = ClaudeRunError("boom")
    assert await plan() is None
    run.result = answer('[{"name": "dev", "members": ["Bob", "Cy"]}]', is_error=True)
    assert await plan() is None


async def test_timeout_falls_back(run, monkeypatch, caplog):
    monkeypatch.setattr(planner, "TIMEOUT_S", 0.01)
    run.result = "hang"
    assert await plan() is None
    assert "timed out" in caplog.text


def test_catalog_has_targeted_channels():
    channels = {c["name"]: c["roles"] for c in load_catalog()["channels"]}
    assert channels["dev"] == ["dev", "dev_backend", "dev_frontend"]
    assert set(channels["quality"]) == {"reviewer", "qa", "security"}


class Session:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


def project_of(mode: str = "enterprise") -> Project:
    project = Project(name="P", repo_url="", default_branch="dev", mode=mode, seed=1)
    project.employees = [Employee(name=m.name, roles=m.roles) for m in generate_team(mode, 1).employees]
    return project


def opened(session: Session) -> dict[str, Room]:
    return {o.name: o for o in session.added if isinstance(o, Room)}


async def test_predefined_team_gets_targeted_channels():
    s = Session()
    await projects._open_channels(s, project_of())
    rooms = opened(s)
    assert {"dev", "quality"} <= set(rooms)
    assert all({"dev", "dev_backend", "dev_frontend"} & set(e.roles) for e in rooms["dev"].members)
    assert all({"reviewer", "qa", "security"} & set(e.roles) for e in rooms["quality"].members)


async def test_no_generic_channel_in_the_catalog():
    s = Session()
    await projects._open_channels(s, project_of())
    assert not {"general", "engineering", "product"} & set(opened(s))


async def test_open_rooms_skips_duplicates_and_small_rooms():
    s = Session()
    project = project_of()
    ana, bob, cy = project.employees[:3]
    await projects._open_rooms(s, project, [("a", [ana, bob]), ("b", [bob, ana]), ("c", [cy]), ("a", [bob, cy]), ("d", [bob, cy])])
    assert list(opened(s)) == ["a", "d"]


class Expiring(Session):
    """Like an async session: after a rollback, reading an attribute of a loaded object fails."""

    def __init__(self, project):
        super().__init__()
        self.project = project
        self.rolled_back = False
        self.committed = False

    async def rollback(self):
        self.rolled_back = True

    async def commit(self):
        self.committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def planned(monkeypatch, tmp_path):
    """Runs plan_custom_channels on a fake session; `planned.plan` is what the planner returns."""
    project = project_of()
    for i, e in enumerate(project.employees, 1):
        e.id = i
    sessions = []
    state = SimpleNamespace(plan=None, project=project, sessions=sessions, calls=[])

    def factory():
        s = Expiring(project)
        sessions.append(s)
        return s

    async def fake_load(s, project_id):
        if s.rolled_back:
            raise AssertionError("project reloaded in the session that rolled back")
        return project

    async def fake_plan(members, **kw):
        state.calls.append(kw)
        state.cwd_entries = list(kw["cwd"].iterdir())
        if isinstance(state.plan, BaseException):
            raise state.plan
        return state.plan

    import app.db

    monkeypatch.setattr(app.db, "SessionLocal", factory, raising=False)
    monkeypatch.setattr(projects, "load_project", fake_load)
    monkeypatch.setattr(projects, "assign_accounts", lambda emps: {e.id: object() for e in emps})
    monkeypatch.setattr(projects, "token_for", lambda a: "tok")
    monkeypatch.setattr(projects.worktrees, "project_dir", lambda p: tmp_path / "project")
    monkeypatch.setattr(planner, "plan_channels", fake_plan)
    return state


def rooms_of(state) -> set[str]:
    return {o.name for s in state.sessions for o in s.added if isinstance(o, Room)}


async def test_plan_custom_channels_opens_planned_rooms(planned):
    a, b, *_ = planned.project.employees
    planned.plan = [planner.PlannedChannel(name="duo", members=[a.name, b.name])]
    await projects.plan_custom_channels(1)
    assert rooms_of(planned) == {"duo"}
    assert planned.calls[0]["lead_id"] is not None and planned.calls[0]["lead_name"]
    assert planned.sessions[0].rolled_back and planned.sessions[-1].committed


async def test_plan_custom_channels_falls_back_to_catalog(planned):
    await projects.plan_custom_channels(1)
    assert {"dev", "quality"} <= rooms_of(planned)


async def test_plan_custom_channels_falls_back_on_planner_error(planned):
    planned.plan = RuntimeError("boom")
    await projects.plan_custom_channels(1)
    assert {"dev", "quality"} <= rooms_of(planned)


async def test_plan_runs_in_an_empty_dir_of_its_own(planned, tmp_path):
    await projects.plan_custom_channels(1)
    cwd = planned.calls[0]["cwd"]
    assert cwd.parent == tmp_path / "project"
    assert planned.cwd_entries == []
    assert not cwd.exists()  # Removed afterwards


def test_catalog_has_no_generic_channel():
    names = {c["name"] for c in load_catalog()["channels"]}
    assert not {"general", "engineering", "product"} & names
