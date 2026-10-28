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
    assert await projects.working_branch(URL, "main") == "dev"
    assert repo.created == [("dev", "main")]


async def test_an_existing_dev_is_reused(repo):
    repo.branches.add("dev")
    assert await projects.working_branch(URL, "main") == "dev"
    assert repo.created == []


async def test_an_explicit_non_default_branch_is_kept(repo):
    repo.branches.add("staging")
    assert await projects.working_branch(URL, "staging") == "staging"
    assert repo.created == []


async def test_an_empty_repository_gets_dev_from_its_first_commit(repo):
    repo.branches.clear()
    assert await projects.working_branch(URL, "main") == "dev"
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
    project = SimpleNamespace(repo_url=URL, default_branch="dev")
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
    project = await projects.create_project(Session(), name="App", repo_url=URL, mode="enterprise", default_branch="main")
    assert project.default_branch == "dev"


async def test_research_project_is_untouched(repo, monkeypatch):
    async def no_channels(*_args):
        pass

    async def no_kickoff(*_args):
        pass

    class Session:
        def add(self, _obj):
            pass

        async def commit(self):
            pass

    monkeypatch.setattr(projects, "_open_channels", no_channels)
    monkeypatch.setattr(projects, "_kick_off_research", no_kickoff)
    mode = next(m for m in projects.load_catalog()["modes"] if projects.kind_of_mode(m) == "research")
    project = await projects.create_project(Session(), name="R", repo_url="", mode=mode, default_branch="main", topic="x")
    assert project.default_branch == "main"
    assert repo.created == []
