"""Tests for CLAUDE.md injected in the agents' prompt, since the runs only load the user settings."""

from app.company.team import generate_team
from app.models import Project
from app.orchestrator import dispatcher
from app.orchestrator.dispatcher import MAX_PROJECT_INSTRUCTIONS_BYTES, build_system_prompt, read_project_instructions


def _project() -> Project:
    return Project(id=1, name="P", repo_url="https://github.com/o/r", mode="enterprise", seed=1, kind="company")


def _reference(tmp_path, monkeypatch):
    monkeypatch.setattr(dispatcher, "repo_dir", lambda project: tmp_path)
    return tmp_path


def test_prompt_contains_claude_md():
    team = generate_team("enterprise", 1)
    prompt = build_system_prompt(team, team.employees[0], _project(), "Boss", False, "Module map: foo.py")
    assert "Module map: foo.py" in prompt


def test_prompt_without_claude_md_has_no_section():
    team = generate_team("enterprise", 1)
    assert "CLAUDE.md" not in build_system_prompt(team, team.employees[0], _project(), "Boss", False)


def test_reads_claude_md_from_reference_clone(tmp_path, monkeypatch):
    (_reference(tmp_path, monkeypatch) / "CLAUDE.md").write_text("  conventions \n")
    assert read_project_instructions(_project()) == "conventions"


def test_missing_empty_symlinked_or_huge_file_is_skipped(tmp_path, monkeypatch):
    repo = _reference(tmp_path, monkeypatch)
    assert read_project_instructions(_project()) is None
    target = tmp_path / "secret"
    target.write_text("secret")
    (repo / "CLAUDE.md").symlink_to(target)
    assert read_project_instructions(_project()) is None
    (repo / "CLAUDE.md").unlink()
    (repo / "CLAUDE.md").write_text("x" * (MAX_PROJECT_INSTRUCTIONS_BYTES + 1))
    assert read_project_instructions(_project()) is None
    (repo / "CLAUDE.md").write_text("  \n")
    assert read_project_instructions(_project()) is None
