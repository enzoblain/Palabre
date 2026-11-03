"""The lead's sensitive flag: who may set it, and how it combines with the path detection at merge."""

import pytest

from app import workflow
from app.errors import ErrorCode, WorkflowError
from app.models import Verdict

from .conftest import FakeSession, make_employee, make_project, make_review, make_task

BLOCKER = "security has not approved this sensitive PR"


class Session(FakeSession):
    def __init__(self, project=None):
        super().__init__([])
        self.project = project or make_project()
        self.added = []

    async def get(self, *_, **__):
        return self.project

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass


@pytest.fixture
def stored_task(monkeypatch):
    task = make_task()

    async def get_task(*_):
        return task

    monkeypatch.setattr(workflow, "get_task", get_task)
    return task


async def update(task, author, **fields):
    args = dict(title=None, description=None, acceptance_criteria=None, depends_on=None, status=None) | fields
    return await workflow.update_task(Session(), 1, task.id, author=author, **args)


async def blockers(project, task, *reviews):
    return await workflow.merge_blockers(FakeSession(list(reviews)), project, task)


async def test_lead_can_set_and_clear_the_flag(stored_task):
    lead = make_employee("Élise", "lead")
    await update(stored_task, lead, sensitive=True)
    assert stored_task.marked_sensitive is True
    await update(stored_task, lead, sensitive=False)
    assert stored_task.marked_sensitive is False


async def test_omitted_flag_is_left_untouched(stored_task):
    stored_task.marked_sensitive = True
    await update(stored_task, make_employee("Chloé", "product_owner"), title="new")
    assert stored_task.marked_sensitive is True


async def test_flag_set_during_review_wakes_security(stored_task, process):
    process(security_gate=True)
    s = Session()
    await workflow.update_task(
        s, 1, stored_task.id, author=make_employee("Élise", "lead"), sensitive=True,
        title=None, description=None, acceptance_criteria=None, depends_on=None, status=None,
    )  # fmt: skip
    [event] = [e for e in s.added if e.type == "sensitive_pr"]
    assert event.payload["task_id"] == stored_task.id


@pytest.mark.parametrize("role", ["product_owner", "backend_dev", "security"])
async def test_other_roles_cannot_set_the_flag(stored_task, role):
    with pytest.raises(WorkflowError) as error:
        await update(stored_task, make_employee("Nina", role), sensitive=True)
    assert error.value.code == ErrorCode.SENSITIVE_FLAG_LEAD_ONLY
    assert stored_task.marked_sensitive is False


async def test_other_roles_cannot_clear_the_flag(stored_task):
    stored_task.marked_sensitive = True
    with pytest.raises(WorkflowError):
        await update(stored_task, make_employee("Nina", "product_owner"), sensitive=False)
    assert stored_task.marked_sensitive is True


async def test_create_task_with_flag_is_lead_only(monkeypatch):
    async def no_dependency_check(*_):
        return None

    async def find_task(_s, _project_id, _task_id):
        return make_task()

    monkeypatch.setattr(workflow, "get_task", find_task)
    kwargs = dict(
        project_id=1, room_id=1, conversation_id=1, title="t", description="", acceptance_criteria=[],
        assignee=None, depends_on=[], sensitive=True,
    )  # fmt: skip
    with pytest.raises(WorkflowError):
        await workflow.create_task(Session(), author=make_employee("Chloé", "product_owner"), **kwargs)
    s = Session()
    await workflow.create_task(s, author=make_employee("Élise", "lead"), **kwargs)
    assert s.added[0].marked_sensitive is True


async def test_marked_task_needs_security_even_on_safe_paths(project, reviewer, process, fake_github):
    process(security_gate=True)
    fake_github.changed_files = ["docs/readme.md"]
    task = make_task(marked_sensitive=True, sensitive=False)
    assert await blockers(project, task, make_review(reviewer, Verdict.approve)) == [BLOCKER]


async def test_marked_task_merges_with_security_approval(project, reviewer, security, process, fake_github):
    process(security_gate=True)
    task = make_task(marked_sensitive=True)
    reviews = [make_review(reviewer, Verdict.approve), make_review(security, Verdict.approve)]
    assert await blockers(project, task, *reviews) == []


async def test_unmarked_flag_never_lifts_path_detection(project, reviewer, process, fake_github):
    process(security_gate=True)
    task = make_task(marked_sensitive=False, sensitive=True)
    assert await blockers(project, task, make_review(reviewer, Verdict.approve)) == [BLOCKER]
