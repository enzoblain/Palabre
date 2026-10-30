"""expand_events: which event wakes whom, and in which context (conversation or task run)."""

from types import SimpleNamespace

import pytest

from app import runner
from app.models import Event, Wakeup
from app.orchestrator import events
from app.orchestrator.events import expand_events, wakes_on

from .conftest import make_employee, make_task

ROOM_ID = 100
CONVERSATION_ID = 200


class FakeEventSession:
    """In-memory stand-in for the queries of `expand_events`, served by what they select."""

    def __init__(self, pending, employees, tasks=(), members=(), room_id=ROOM_ID, conversation_id=CONVERSATION_ID, room_kind="team"):
        self.pending = list(pending)
        self.employees = list(employees)
        self.tasks = {t.id: t for t in tasks}
        self.members = set(members)
        self.room_id = room_id
        self.room_kind = room_kind
        self.conversation_id = conversation_id
        self.added: list = []
        self.joined: list[int] = []
        self.committed = False

    async def scalars(self, query):
        name = query.column_descriptions[0]["name"]
        if name == "Event":
            return self.pending
        if name == "Employee":
            return self.employees
        if name == "employee_id":
            return list(self.members)
        raise AssertionError(f"unexpected query on {name}")

    async def scalar(self, query):
        name = query.column_descriptions[0]["name"]
        if name == "kind":
            return self.room_kind
        if name == "room_id":
            return self.room_id
        if name == "id":  # last conversation of the room(s)
            return self.conversation_id
        raise AssertionError(f"unexpected query on {name}")

    async def get(self, model, pk):
        if model.__name__ == "Task":
            return self.tasks.get(pk)
        return next((e for e in self.employees if e.id == pk), None)

    async def execute(self, statement):  # insert into room_members
        self.joined.append(statement.compile().params["employee_id"])
        self.members.add(self.joined[-1])

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    @property
    def wakeups(self) -> list[Wakeup]:
        return [o for o in self.added if isinstance(o, Wakeup)]


def employee(name: str, role: str):
    e = make_employee(name, role)
    e.project_id = 1
    return e


def event(type: str, payload=None, employee_id=None, role=None) -> Event:
    return Event(project_id=1, type=type, payload=payload or {}, target_employee_id=employee_id, target_role=role)


@pytest.fixture
def team():
    return SimpleNamespace(
        lead=employee("Louise", "lead"),
        dev=employee("Léa", "dev_backend"),
        other_dev=employee("Nina", "dev_backend"),
        reviewer=employee("Karim", "reviewer"),
        qa=employee("Samuel", "qa"),
        security=employee("Noa", "security"),
    )


def everyone(team):
    return list(vars(team).values())


def woken(session) -> set[str]:
    names = {e.id: e.name for e in session.employees}
    return {names[w.employee_id] for w in session.wakeups}


# --- Catalog: wakes_on ----------------------------------------------------------------


@pytest.mark.parametrize(
    "role, event_type, expected",
    [
        ("lead", "pr_approved", True), ("lead", "escalation", True), ("lead", "review_requested", False),
        ("dev_backend", "task_assigned", True), ("dev_backend", "changes_requested", True),
        ("dev_backend", "pr_ready", False),
        ("reviewer", "review_requested", True), ("reviewer", "sensitive_pr", False),
        ("qa", "pr_ready", True), ("qa", "review_requested", False),
        ("security", "sensitive_pr", True), ("security", "pr_ready", False),
        ("scribe", "conversation_idle", True), ("scribe", "task_assigned", False),
    ],
)  # fmt: skip
def test_wakes_on_follows_the_catalog(role, event_type, expected):
    assert wakes_on(employee("X", role), event_type) is expected


@pytest.mark.parametrize("role", ["lead", "dev_backend", "reviewer", "qa", "security", "scribe", "architect"])
def test_everyone_wakes_on_mention(role):
    assert wakes_on(employee("X", role), "mention")


def test_employee_with_several_roles_wakes_on_any_of_them():
    both = make_employee("Duo", "reviewer", "qa")
    assert wakes_on(both, "review_requested") and wakes_on(both, "pr_ready")


# --- Mention --------------------------------------------------------------------------


async def test_mention_wakes_only_the_mentioned_employee(team):
    s = FakeEventSession(
        [event("mention", {"conversation_id": CONVERSATION_ID, "message_id": 5}, employee_id=team.qa.id)],
        everyone(team), members=[e.id for e in everyone(team)],
    )  # fmt: skip
    await expand_events(s)
    [wakeup] = s.wakeups
    assert wakeup.employee_id == team.qa.id
    assert (wakeup.kind, wakeup.conversation_id, wakeup.task_id) == ("conversation", CONVERSATION_ID, None)
    assert wakeup.event_type == "mention" and "#5" in wakeup.reason


async def test_mention_of_someone_outside_the_room_makes_them_join(team):
    s = FakeEventSession(
        [event("mention", {"conversation_id": CONVERSATION_ID, "message_id": 5}, employee_id=team.qa.id)],
        everyone(team), members=[team.lead.id],
    )  # fmt: skip
    await expand_events(s)
    assert s.joined == [team.qa.id]
    assert len(s.wakeups) == 1


async def test_no_conversation_means_no_wakeup(team):
    s = FakeEventSession([event("mention", {"message_id": 5}, employee_id=team.qa.id)], everyone(team), room_id=None, conversation_id=None)
    await expand_events(s)
    assert s.wakeups == []


# --- Boss message ---------------------------------------------------------------------


async def test_boss_message_wakes_the_lead_only(team):
    s = FakeEventSession(
        [event("boss_message", {"conversation_id": CONVERSATION_ID, "message_id": 9}, role="lead")],
        everyone(team), members=[e.id for e in everyone(team)],
    )  # fmt: skip
    await expand_events(s)
    assert woken(s) == {"Louise"}
    assert "boss posted" in s.wakeups[0].reason


async def test_boss_message_goes_to_the_role_even_if_the_catalog_does_not_list_it(team):
    assert not wakes_on(team.lead, "boss_message")  # targeted by role, not by broadcast
    s = FakeEventSession(
        [event("boss_message", {"conversation_id": CONVERSATION_ID}, role="lead")], everyone(team), members=[team.lead.id]
    )  # fmt: skip
    await expand_events(s)
    assert len(s.wakeups) == 1


async def test_only_the_lead_is_woken_in_the_direction_channel(team):
    s = FakeEventSession(
        [event("mention", {"conversation_id": CONVERSATION_ID, "message_id": 9}, employee_id=team.dev.id),
         event("mention", {"conversation_id": CONVERSATION_ID, "message_id": 9}, employee_id=team.lead.id)],
        everyone(team), members=[team.lead.id], room_kind="direction",
    )  # fmt: skip
    await expand_events(s)
    assert woken(s) == {"Louise"}
    assert s.joined == []  # nobody is called into direction


async def test_nobody_is_called_into_a_dm(team):
    s = FakeEventSession(
        [event("escalation", {"conversation_id": CONVERSATION_ID}, employee_id=team.lead.id),
         event("mention", {"conversation_id": CONVERSATION_ID, "message_id": 9}, employee_id=team.dev.id)],
        everyone(team), members=[team.dev.id, team.qa.id], room_kind="dm",
    )  # fmt: skip
    await expand_events(s)
    assert woken(s) == {"Léa"}  # the member only; the lead is not added to the DM
    assert s.joined == []


async def test_event_without_target_and_unlisted_type_wakes_nobody(team):
    s = FakeEventSession([event("boss_message", {"conversation_id": CONVERSATION_ID})], everyone(team))
    await expand_events(s)
    assert s.wakeups == []


# --- Task unblocked and other task events ---------------------------------------------


async def test_unblocked_task_wakes_its_assignee_in_a_task_run(team):
    task = make_task(assignee_id=team.dev.id, conversation_id=CONVERSATION_ID)
    s = FakeEventSession([event("task_unblocked", {"task_id": task.id}, employee_id=team.dev.id)], everyone(team), tasks=[task])
    await expand_events(s)
    [wakeup] = s.wakeups
    assert wakeup.employee_id == team.dev.id
    assert (wakeup.kind, wakeup.task_id, wakeup.conversation_id) == ("task", task.id, None)
    assert f"#{task.id}" in wakeup.reason and "no longer waiting" in wakeup.reason
    assert s.joined == []  # a task run does not need the room


@pytest.mark.parametrize("type", ["task_assigned", "changes_requested", "task_retry", "task_resume"])
async def test_task_events_start_a_task_run_for_the_assignee(team, type):
    task = make_task(assignee_id=team.dev.id, conversation_id=CONVERSATION_ID)
    s = FakeEventSession([event(type, {"task_id": task.id}, employee_id=team.dev.id)], everyone(team), tasks=[task])
    await expand_events(s)
    assert [w.kind for w in s.wakeups] == ["task"]


async def test_task_event_for_someone_else_than_the_assignee_is_a_conversation_wakeup(team):
    task = make_task(assignee_id=team.dev.id, conversation_id=CONVERSATION_ID)
    s = FakeEventSession(
        [event("task_assigned", {"task_id": task.id}, employee_id=team.other_dev.id)],
        everyone(team), tasks=[task], members=[team.other_dev.id],
    )  # fmt: skip
    await expand_events(s)
    [wakeup] = s.wakeups
    assert (wakeup.kind, wakeup.conversation_id, wakeup.task_id) == ("conversation", CONVERSATION_ID, None)


# --- Broadcasts: who reacts ------------------------------------------------------------


@pytest.mark.parametrize(
    "type, expected",
    [
        ("review_requested", {"Karim"}),
        ("pr_ready", {"Samuel"}),
        ("sensitive_pr", {"Noa"}),
        ("pr_approved", {"Louise"}),
        ("task_assigned", {"Léa", "Nina"}),
    ],
)  # fmt: skip
async def test_broadcast_wakes_the_roles_that_listen(team, type, expected):
    s = FakeEventSession([event(type, {"conversation_id": CONVERSATION_ID})], everyone(team), members=[e.id for e in everyone(team)])
    await expand_events(s)
    assert woken(s) == expected


async def test_event_targeted_at_a_role_ignores_others(team):
    s = FakeEventSession([event("review_requested", {"conversation_id": CONVERSATION_ID}, role="qa")], everyone(team), members=[team.qa.id])
    await expand_events(s)
    assert woken(s) == {"Samuel"}


async def test_events_are_marked_processed_and_committed(team):
    ev = event("mention", {"conversation_id": CONVERSATION_ID}, employee_id=team.qa.id)
    s = FakeEventSession([ev], everyone(team), members=[team.qa.id])
    assert await expand_events(s) == 1
    assert ev.processed_at is not None and s.committed


# --- Nothing real runs -----------------------------------------------------------------


async def test_no_real_claude_run_in_tests():
    with pytest.raises(AssertionError, match="mock it"):
        await runner.asyncio.create_subprocess_exec("claude", "-p")


def test_events_module_uses_the_catalog_not_the_network():
    assert events.load_catalog()["roles"]["lead"]["permissions"]
