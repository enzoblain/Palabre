"""workflow.conventional_title and worktrees.branch_name: what goes to GitHub is English and conventional."""

import pytest

from app.workflow import WorkflowError, conventional_title
from app.worktrees import branch_name

from .conftest import make_task


def test_reference_is_added_last():
    assert conventional_title("feat(usage): show real Claude usage per model", 60) == (
        "feat(usage): show real Claude usage per model (#60)"
    )


def test_scope_is_optional_and_breaking_mark_accepted():
    assert conventional_title("fix: handle empty diff", 7) == "fix: handle empty diff (#7)"
    assert conventional_title("refactor(api)!: drop v1", 7) == "refactor(api)!: drop v1 (#7)"


def test_existing_reference_is_not_doubled():
    assert conventional_title("chore: bump deps (#9)", 9) == "chore: bump deps (#9)"


@pytest.mark.parametrize(
    "title",
    [
        "[#59] Front : indicateur live",
        "Add a feature",
        "feature: add something",
        "feat(Usage): uppercase scope",
        "feat:no space",
        "feat: ",
        "feat: indicateur affiché à l'écran é",
        "feat: " + "x" * 100,
        "",
    ],
)
def test_invalid_titles_are_refused_with_a_clear_message(title):
    with pytest.raises(WorkflowError, match="Conventional Commits"):
        conventional_title(title, 1)


def test_branch_name_ignores_the_title():
    assert branch_name(make_task(id=70, title="Règles : commits en anglais")) == "task/70"
