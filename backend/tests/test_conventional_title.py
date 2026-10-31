"""workflow.conventional_title and worktrees.branch_name: what goes to GitHub is English and conventional."""

import pytest

from app.errors import WorkflowError
from app.workflow import conventional_title
from app.github import is_task_branch_name
from app.worktrees import branch_name, final_branch_name

from .conftest import make_task


def test_pr_number_is_added_last():
    assert conventional_title("feat(usage): show real Claude usage per model", 60) == (
        "feat(usage): show real Claude usage per model (#60)"
    )


def test_scope_is_optional_and_breaking_mark_accepted():
    assert conventional_title("fix: handle empty diff", 7) == "fix: handle empty diff (#7)"
    assert conventional_title("refactor(api)!: drop v1", 7) == "refactor(api)!: drop v1 (#7)"


def test_existing_reference_is_replaced_not_doubled():
    assert conventional_title("chore: bump deps (#9)", 12) == "chore: bump deps (#12)"
    assert conventional_title("chore: bump deps (#9)") == "chore: bump deps"


@pytest.mark.parametrize(
    "title",
    [
        "[#59] Front : indicateur live",
        "Add a feature",
        "feature: add something",
        "feat(Usage): uppercase scope",
        "feat:no space",
        "feat: ",
        "feat: indicator shown on screen é",
        "feat: " + "x" * 100,
        "",
    ],
)
def test_invalid_titles_are_refused_with_a_clear_message(title):
    with pytest.raises(WorkflowError, match="Conventional Commits"):
        conventional_title(title, 1)


def test_branch_name_ignores_the_title():
    assert branch_name(make_task(id=70, title="Rules: commits in English")) == "task/70"


def test_final_branch_name_from_title():
    assert final_branch_name("feat(usage): Show real Claude usage per model (#60)", 60) == (
        "feat/60-show-real-claude-usage-per-model"
    )
    assert final_branch_name("fix!: handle empty diff (#7)", 7) == "fix/7-handle-empty-diff"
    assert final_branch_name("refactor(api): " + "word " * 20 + "(#7)", 7).count("-") <= 9


@pytest.mark.parametrize(
    "branch, expected",
    [
        ("task/12", True),
        ("task/12-x", True),
        ("feat/60-claude-usage", True),
        ("fix/64-system-lines", True),
        ("dev", False),
        ("main", False),
        ("feature/1-x", False),
        ("dependabot/npm/foo", False),
        ("release/1.0", False),
        ("fix/abc", False),
        (None, False),
    ],
)
def test_task_branch_recognition(branch, expected):
    assert is_task_branch_name(branch) is expected
