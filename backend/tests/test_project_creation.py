"""projects.working_branch: new development projects work on dev, not on production."""

from types import SimpleNamespace

import pytest

from app import github, projects, worktrees


@pytest.fixture
def repo(monkeypatch):
    state = SimpleNamespace(default="main", branches={"main"}, created=[])

    async def resolve_branch(_repo, _branch):
        return state.default

    async def has_commits(_repo):
        return bool(state.branches)

    async def branch_exists(_repo, branch):
        return branch in state.branches

    async def create_branch(_repo, branch, from_branch):
        assert from_branch in state.branches
        state.branches.add(branch)
        state.created.append((branch, from_branch))

    monkeypatch.setattr(github, "resolve_branch", resolve_branch)
    monkeypatch.setattr(github, "has_commits", has_commits)
    monkeypatch.setattr(github, "branch_exists", branch_exists)
    monkeypatch.setattr(github, "create_branch", create_branch)
    return state


URL = "https://github.com/acme/app"


async def test_dev_is_created_from_the_default_branch(repo):
    assert await projects.working_branch(URL) == "dev"
    assert repo.created == [("dev", "main")]


async def test_an_existing_dev_is_reused(repo):
    repo.branches.add("dev")
    assert await projects.working_branch(URL) == "dev"
    assert repo.created == []


async def test_an_empty_repository_gets_dev_from_its_first_commit(repo):
    repo.branches.clear()
    assert await projects.working_branch(URL) == "dev"
    assert repo.created == []  # nothing to branch from yet


async def test_initial_commit_pushes_production_before_dev(repo, monkeypatch, tmp_path):
    calls = []

    async def git(_cwd, *args, **_kwargs):
        calls.append(args)
        if args[0] == "rev-parse":
            raise github.GitHubError("no ref")
        return ""

    monkeypatch.setattr(worktrees, "git", git)
    monkeypatch.setattr(worktrees, "resolve_branch", github.resolve_branch)  # the fake of `repo`
    project = SimpleNamespace(name="App", repo_url=URL, default_branch="dev")
    await worktrees._initial_commit(project, tmp_path)
    pushes = [a[-1] for a in calls if a[0] == "push"]
    assert pushes == ["main:refs/heads/main", "main:refs/heads/dev"]


async def test_create_project_stores_dev_for_a_company(repo, monkeypatch):
    added = []

    class Session:
        def add(self, obj):
            added.append(obj)

        async def flush(self):  # `ensure_direction` flushes the direction room
            pass

        async def commit(self):
            pass

    async def no_channels(*_args):
        pass

    monkeypatch.setattr(projects, "_open_channels", no_channels)
    project = await projects.create_project(Session(), name="App", repo_url=URL, mode="enterprise")
    assert project.default_branch == "dev"


async def test_research_project_is_untouched(repo, monkeypatch):
    async def no_channels(*_args):
        pass

    async def no_kickoff(*_args):
        pass

    class Session:
        def add(self, _obj):
            pass

        async def flush(self):
            pass

        async def commit(self):
            pass

    monkeypatch.setattr(projects, "_open_channels", no_channels)
    monkeypatch.setattr(projects, "_kick_off_research", no_kickoff)
    mode = next(m for m in projects.load_catalog()["modes"] if projects.kind_of_mode(m) == "research")
    project = await projects.create_project(Session(), name="R", repo_url="", mode=mode, topic="x")
    assert project.default_branch == "main"
    assert repo.created == []


@pytest.fixture
def api(monkeypatch):
    state = SimpleNamespace(repo={"default_branch": "main"}, branches=set())

    async def _api(_method, path, **_kwargs):
        if path.endswith("/branches"):
            return [{"name": b} for b in state.branches][:1]
        if "/branches/" in path:
            name = path.rsplit("/", 1)[1]
            if name not in state.branches:
                raise github.GitHubError("GET failed: 404 not found", status=404)
            return {"name": name}
        return state.repo

    monkeypatch.setattr(github, "_api", _api)
    return state


async def test_production_branch_is_the_github_default_main(api):
    api.branches = {"main", "dev"}
    assert await github.production_branch("acme/app") == "main"


async def test_production_branch_is_the_github_default_master(api):
    api.repo = {"default_branch": "master"}
    api.branches = {"master"}
    assert await github.resolve_branch("acme/app", "") == "master"


async def test_production_branch_falls_back_to_master_then_main(api):
    api.repo = {}
    api.branches = {"master"}
    assert await github.production_branch("acme/app") == "master"
    api.branches = {"main", "master"}
    assert await github.production_branch("acme/app") == "main"
    api.branches = set()
    assert await github.production_branch("acme/app") == "main"


async def test_initial_commit_has_a_readme_and_gitignore(repo, monkeypatch, tmp_path):
    calls = []

    async def git(_cwd, *args, **_kwargs):
        calls.append(args)
        if args[0] == "rev-parse":
            raise github.GitHubError("no ref")
        return ""

    monkeypatch.setattr(worktrees, "git", git)
    monkeypatch.setattr(worktrees, "resolve_branch", github.resolve_branch)
    project = SimpleNamespace(name="App", repo_url=URL, default_branch="main")
    await worktrees._initial_commit(project, tmp_path)
    assert (tmp_path / "README.md").read_text().startswith("# App")
    assert (tmp_path / ".gitignore").exists()
    assert ("add", "README.md", ".gitignore") in calls
    assert [a[-1] for a in calls if a[0] == "push"] == ["main:refs/heads/main"]


def test_orientation_only_on_the_first_run():
    from app.orchestrator.prompts import orientation_rule

    first = orientation_rule("master")
    assert "`master`" in first and "README" in first
    later = orientation_rule("master", first_run=False)
    assert "`master`" in later and "README" not in later


def test_project_in_ignores_a_default_branch_sent_by_an_old_client():
    from app.api.schemas import ProjectIn

    assert not hasattr(ProjectIn(name="p", repo_url=URL, default_branch="x"), "default_branch")


async def test_create_branch_encodes_the_source_branch(monkeypatch):
    calls = []

    async def api(method, path, **kwargs):
        calls.append((method, path))
        return {"object": {"sha": "abc"}}

    monkeypatch.setattr(github, "_api", api)
    await github.create_branch("acme/app", "dev", "a?b#c")
    assert calls[0] == ("GET", "/repos/acme/app/git/ref/heads/a%3Fb%23c")


def test_branch_change_rejects_trailing_newline():
    import pytest
    from pydantic import ValidationError

    from app.api.schemas import BranchChange

    assert BranchChange(branch="main").branch == "main"
    with pytest.raises(ValidationError):
        BranchChange(branch="main\n")


async def test_lead_cannot_move_the_team_to_production(repo):
    from app.errors import ErrorCode, WorkflowError

    project = SimpleNamespace(repo_url=URL, default_branch="dev")
    with pytest.raises(WorkflowError) as e:
        await projects.change_branch(None, project, "main", by=SimpleNamespace())
    assert e.value.code == ErrorCode.PRODUCTION_BRANCH_BOSS_ONLY
