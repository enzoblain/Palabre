"""Requests to the boss: messages in direction answered with validate / reject / nuance."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import github, projects, services
from app.api.schemas import RequestAnswerIn
from app.mcp_server.permissions import mcp_tools_for
from app.models import (
    Base,
    Conversation,
    Decision,
    DecisionStatus,
    Employee,
    Event,
    Message,
    Project,
    RequestAnswer,
    RequestStatus,
    Room,
)

from .conftest import make_employee

LEAD = make_employee("Louise", "lead")


class FakeSession:
    """Serves objects by (model, id), the team for `scalars`, and records what is added."""

    def __init__(self, *objects, team=(LEAD,), direction_id=9):
        self.objects = {(type(o), o.id): o for o in objects}
        self.team, self.direction_id = list(team), direction_id
        self.added, self.executed = [], []

    async def get(self, model, id_, **_kwargs):
        return self.objects.get((model, id_))

    async def scalars(self, _query):
        return self.team

    async def scalar(self, _query):
        return self.direction_id

    async def execute(self, statement):
        self.executed.append(statement)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for i, obj in enumerate(self.added, start=100):
            if getattr(obj, "id", 0) is None:
                obj.id = i

    async def commit(self):
        pass

    async def refresh(self, _obj):
        pass

    @property
    def events(self) -> list[Event]:
        return [o for o in self.added if isinstance(o, Event)]


def _request(kind="question", decision_id=None, status="pending") -> Message:
    return Message(
        id=5, conversation_id=9, employee_id=LEAD.id, author_name="Louise", content="Ship it?",
        request_kind=kind, request_status=status, request_decision_id=decision_id,
    )  # fmt: skip


def _objects(message, *more):
    conversation = Conversation(id=9, room_id=2, title="General")
    room = Room(id=2, project_id=1, name="direction", kind="direction")
    return FakeSession(message, conversation, room, *more)


def _decision(**fields) -> Decision:
    return Decision(
        id=3, room_id=2, title="Use Redis", proposed_by="Louise", status=DecisionStatus.proposed, **fields
    )  # fmt: skip


@pytest.mark.parametrize("answer", list(RequestAnswer))
async def test_answer_is_stored_and_wakes_the_lead_with_it(answer):
    s = _objects(_request())
    message = await projects.answer_request(s, 5, answer, " on y va, mais doucement ")
    assert message.request_status == answer.value
    assert message.request_comment == "on y va, mais doucement"
    assert message.request_answered_at is not None
    (event,) = s.events
    assert event.type == "ceo_answer" and event.target_employee_id == LEAD.id
    assert event.payload["answer"] == answer.value and event.payload["comment"] == "on y va, mais doucement"


async def test_a_request_is_answered_only_once():
    s = _objects(_request(status="validated"))
    with pytest.raises(services.WorkflowError, match="already answered"):
        await projects.answer_request(s, 5, RequestAnswer.rejected)
    assert s.events == []


async def test_a_plain_message_cannot_be_answered():
    s = _objects(Message(id=5, conversation_id=9, author_name="Louise", content="hi"))
    with pytest.raises(services.WorkflowError):
        await projects.answer_request(s, 5, RequestAnswer.validated)


def test_nuance_needs_a_comment():
    with pytest.raises(ValueError):
        RequestAnswerIn(answer="nuanced", comment="  ")
    assert RequestAnswerIn(answer="validated").comment == ""


async def test_validating_a_decision_validates_it():
    decision = _decision()
    s = _objects(_request("decision", decision.id), decision)
    await projects.answer_request(s, 5, RequestAnswer.validated)
    assert decision.status == DecisionStatus.validated and decision.decided_at is not None
    # The lead proposed it: only the answer wakes them up, not decision_changed
    assert [e.type for e in s.events if e.target_employee_id == LEAD.id] == ["ceo_answer"]


async def test_nuancing_a_decision_leaves_it_proposed():
    decision = _decision()
    s = _objects(_request("decision", decision.id), decision)
    await projects.answer_request(s, 5, RequestAnswer.nuanced, "Rather Valkey")
    assert decision.status == DecisionStatus.proposed and decision.decided_at is None


@pytest.fixture
def release(monkeypatch):
    calls = []

    async def merge(repo, number, title, method, sha=None):
        calls.append(("merge", number, method))

    async def close(repo, number):
        calls.append(("close", number))

    async def load_project(_s, _id):
        return SimpleNamespace(id=1, repo_url="https://github.com/acme/app")

    monkeypatch.setattr(github, "merge_pull_request", merge)
    monkeypatch.setattr(github, "close_pull_request", close)
    monkeypatch.setattr(projects, "load_project", load_project)
    return calls


async def test_validating_a_release_merges_its_pull_request(release):
    decision = _decision(pr_number=42, pr_url="https://github.com/acme/app/pull/42")
    s = _objects(_request("release", decision.id), decision)
    await projects.answer_request(s, 5, RequestAnswer.validated)
    assert release == [("merge", 42, "merge")]
    assert decision.status == DecisionStatus.validated


async def test_rejecting_a_release_closes_its_pull_request(release):
    decision = _decision(pr_number=42)
    s = _objects(_request("release", decision.id), decision)
    await projects.answer_request(s, 5, RequestAnswer.rejected)
    assert release == [("close", 42)]
    assert decision.status == DecisionStatus.rejected


async def test_nuancing_a_release_keeps_the_pull_request_open(release):
    decision = _decision(pr_number=42)
    s = _objects(_request("release", decision.id), decision)
    message = await projects.answer_request(s, 5, RequestAnswer.nuanced, "Wait for the login fix")
    assert release == []
    assert decision.status == DecisionStatus.rejected  # dropped, so the lead can propose it again
    assert message.request_status == "nuanced"


async def test_a_refused_merge_leaves_the_request_pending(release, monkeypatch):
    async def refuse(*_args, **_kwargs):
        raise github.GitHubError("not mergeable")

    monkeypatch.setattr(github, "merge_pull_request", refuse)
    decision = _decision(pr_number=42)
    message = _request("release", decision.id)
    s = _objects(message, decision)
    with pytest.raises(github.GitHubError):
        await projects.answer_request(s, 5, RequestAnswer.validated)
    assert message.request_status == "pending" and decision.status == DecisionStatus.proposed


async def test_add_decision_asks_the_boss_in_direction():
    s = FakeSession()
    decision = await services.add_decision(s, 1, 2, "Use Redis", "Faster", LEAD)
    messages = [o for o in s.added if isinstance(o, Message)]
    assert len(messages) == 1
    assert messages[0].conversation_id == 9
    assert (messages[0].request_kind, messages[0].request_status) == ("decision", "pending")
    assert "Use Redis" in messages[0].content
    assert not any(e.target_role == "boss" for e in s.events)
    assert decision.proposed_by == "Louise"


async def test_escalating_to_the_boss_is_a_request_in_direction():
    dev = make_employee("Léa", "dev_backend")
    s = FakeSession()
    msg = await services.escalate(s, 1, 4, dev, "boss", "Cloud budget to decide")
    assert msg.conversation_id == 9 and msg.request_kind == "escalation" and msg.request_status == "pending"
    assert s.events == []


async def test_a_research_group_has_no_direction_to_ask_in():
    s = FakeSession(direction_id=None)
    assert await services.ask_boss(s, 1, LEAD, "why?", "question") is None


async def test_unknown_request_kind_is_refused():
    with pytest.raises(services.WorkflowError):
        await services.ask_boss(FakeSession(), 1, LEAD, "x", "chitchat")


async def test_migration_turns_what_waited_in_the_inbox_into_requests():
    decision = _decision()
    room = Room(id=2, project_id=1, name="direction", kind="direction")
    escalated = Message(id=6, conversation_id=4, author_name="Léa", content="Budget ?")
    event = Event(type="escalation", target_role="boss", payload={"message_id": 6})

    class Migrating(FakeSession):
        results = iter([[event], [decision], [LEAD]])

        # not asked yet, then the direction conversation, then the room kind of the posted message
        scalar_results = iter([None, 9, "direction"])

        async def scalars(self, _query):
            return next(self.results)

        async def scalar(self, _query):
            return next(self.scalar_results)

    s = Migrating(escalated, room, direction_id=9)
    await projects.migrate_inbox(s)
    assert (escalated.request_kind, escalated.request_status) == ("escalation", "pending")
    (asked,) = [o for o in s.added if isinstance(o, Message)]
    assert (asked.request_kind, asked.request_decision_id) == ("decision", decision.id)


# --- The lead tidies up their pending requests ---------------------------------------


@pytest.fixture
async def tidy_db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def _direction(s):
    project = Project(name="P", repo_url="https://github.com/o/r", mode="enterprise", seed=1, kind="company")
    s.add(project)
    await s.flush()
    lead = Employee(project_id=project.id, name="Louise", title="Lead", model="opus", permissions=[], traits={}, quirks=[], style={}, roles=["lead"], mcp_token="a")
    dev = Employee(project_id=project.id, name="Mehdi", title="Dev", model="sonnet", permissions=[], traits={}, quirks=[], style={}, roles=["backend"], mcp_token="b")
    room = Room(project_id=project.id, name="direction", kind="direction")
    s.add_all([lead, dev, room])
    await s.flush()
    s.add(Conversation(room_id=room.id, title="General"))
    await s.flush()
    return project, lead, dev


async def _ask(s, project, lead, text="Question?", kind="question"):
    return await services.ask_boss(s, project.id, lead, text, kind)


async def test_list_returns_only_pending_requests_of_the_lead(tidy_db):
    s = tidy_db
    project, lead, dev = await _direction(s)
    mine, answered = await _ask(s, project, lead, "a"), await _ask(s, project, lead, "b")
    await projects.answer_request(s, answered.id, RequestAnswer.validated)
    await _ask(s, project, dev, "not the lead's")
    assert [m.id for m in await services.list_pending_requests(s, project.id, lead)] == [mine.id]


async def test_withdraw_closes_the_request_and_the_boss_cannot_answer(tidy_db):
    s = tidy_db
    project, lead, _ = await _direction(s)
    request = await _ask(s, project, lead)
    done = await services.withdraw_request(s, project.id, lead, request.id, "done another way")
    assert done.request_status == RequestStatus.withdrawn.value and done.request_comment == "done another way"
    assert await services.list_pending_requests(s, project.id, lead) == []
    with pytest.raises(services.WorkflowError, match="already answered"):
        await projects.answer_request(s, request.id, RequestAnswer.validated)


async def test_merge_replaces_requests_by_a_new_one(tidy_db):
    s = tidy_db
    project, lead, _ = await _direction(s)
    first, second = await _ask(s, project, lead, "a"), await _ask(s, project, lead, "b")
    new = await services.merge_requests(s, project.id, lead, [first.id, second.id], "a and b together")
    for old in (first, second):
        assert old.request_status == RequestStatus.merged.value and old.request_merged_into == new.id
    assert new.request_status == RequestStatus.pending.value and new.content == "a and b together"
    assert [m.id for m in await services.list_pending_requests(s, project.id, lead)] == [new.id]


async def test_merge_failure_after_creation_leaves_no_new_request(tidy_db, monkeypatch):
    s = tidy_db
    project, lead, _ = await _direction(s)
    first, second = await _ask(s, project, lead, "a"), await _ask(s, project, lead, "b")
    ids, project_id, lead_ref = {first.id, second.id}, project.id, SimpleNamespace(id=lead.id)
    calls = []

    def boom(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("closing failed")

    monkeypatch.setattr(services, "_close_request", boom)
    with pytest.raises(RuntimeError):
        await services.merge_requests(s, project.id, lead, [first.id, second.id], "together")
    await s.rollback()
    assert calls
    assert {m.id for m in await services.list_pending_requests(s, project_id, lead_ref)} == ids


async def test_merge_caps_the_number_of_requests(tidy_db):
    s = tidy_db
    project, lead, _ = await _direction(s)
    with pytest.raises(services.WorkflowError, match="at most"):
        await services.merge_requests(s, project.id, lead, list(range(1, 60)), "x")


async def _linked_request(s, project, lead, kind="decision", **fields):
    room_id = await s.scalar(select(Room.id).where(Room.kind == "direction"))
    decision = Decision(room_id=room_id, title="D", proposed_by="Louise", **fields)
    s.add(decision)
    await s.flush()
    return decision, await services.ask_boss(s, project.id, lead, "validate D?", kind, decision.id)


async def test_merge_refuses_a_decision_request(tidy_db):
    s = tidy_db
    project, lead, _ = await _direction(s)
    decision, linked = await _linked_request(s, project, lead)
    other = await _ask(s, project, lead, "b")
    with pytest.raises(services.WorkflowError, match="decision or a release"):
        await services.merge_requests(s, project.id, lead, [linked.id, other.id], "merged")
    assert decision.status == DecisionStatus.proposed and linked.request_status == "pending"


async def test_merge_refuses_a_release_request(tidy_db):
    s = tidy_db
    project, lead, _ = await _direction(s)
    _, release_request = await _linked_request(s, project, lead, "release", pr_number=7)
    with pytest.raises(services.WorkflowError, match="decision or a release"):
        await services.merge_requests(s, project.id, lead, [release_request.id], "merged")


async def test_withdrawing_a_decision_request_rejects_the_decision(tidy_db):
    s = tidy_db
    project, lead, _ = await _direction(s)
    decision, linked = await _linked_request(s, project, lead)
    twin = await services.ask_boss(s, project.id, lead, "again?", "decision", decision.id)
    done = await projects.withdraw_request(s, project.id, lead, linked.id, "obsolete")
    assert done.request_status == RequestStatus.withdrawn.value
    assert decision.status == DecisionStatus.rejected and decision.decided_at is not None
    # The other request on the same decision is settled with it
    assert twin.request_status == RequestAnswer.rejected.value and twin.request_comment == "obsolete"


async def test_withdrawing_a_release_request_is_refused(tidy_db):
    s = tidy_db
    project, lead, _ = await _direction(s)
    decision, request = await _linked_request(s, project, lead, "release", pr_number=7)
    with pytest.raises(services.WorkflowError, match="release"):
        await projects.withdraw_request(s, project.id, lead, request.id, "nope")
    await s.refresh(request)
    await s.refresh(decision)
    assert request.request_status == "pending" and decision.status == DecisionStatus.proposed


async def test_refusals(tidy_db):
    s = tidy_db
    project, lead, dev = await _direction(s)
    answered, theirs, ok = await _ask(s, project, lead), await _ask(s, project, dev), await _ask(s, project, lead)
    await projects.answer_request(s, answered.id, RequestAnswer.rejected)
    with pytest.raises(services.WorkflowError, match="no longer pending"):
        await services.withdraw_request(s, project.id, lead, answered.id, "x")
    with pytest.raises(services.WorkflowError, match="not yours"):
        await services.withdraw_request(s, project.id, lead, theirs.id, "x")
    with pytest.raises(services.WorkflowError, match="does not exist"):
        await services.withdraw_request(s, project.id, lead, 999, "x")
    with pytest.raises(services.WorkflowError, match="reason"):
        await services.withdraw_request(s, project.id, lead, ok.id, "  ")
    # One bad request refuses the whole merge: nothing is closed nor created
    with pytest.raises(services.WorkflowError):
        await services.merge_requests(s, project.id, lead, [ok.id, answered.id], "merged")
    assert [m.id for m in await services.list_pending_requests(s, project.id, lead)] == [ok.id]


def test_only_the_lead_holds_the_tools():
    tools = {"list_pending_requests", "withdraw_request", "merge_requests"}
    assert tools <= mcp_tools_for(["manage_channels"], task_run=False)
    assert not tools & mcp_tools_for(["conversation", "request_review"], task_run=True)


def test_request_status_check_rejects_unknown_value():
    from sqlalchemy import create_engine, insert
    from sqlalchemy.exc import IntegrityError

    from app.models import Base, Message

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    row = dict(conversation_id=1, author_name="x", content="c", request_kind="decision")
    with engine.begin() as conn:
        conn.execute(insert(Message).values(**row, request_status="merged"))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(Message).values(**row, request_status="bogus"))


def test_upgrade_adds_missing_check_on_existing_postgres_table():
    from types import SimpleNamespace

    from app import db
    from app.models import REQUEST_STATUS_CHECK

    ran = []

    def run(sql):
        ran.append(sql)
        return []  # no existing constraint

    conn = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), exec_driver_sql=run)
    db._add_missing_checks(conn)
    alters = [sql for sql in ran if sql.startswith("ALTER")]
    assert len(alters) == 1 and REQUEST_STATUS_CHECK in alters[0] and "'withdrawn'" in alters[0]
    assert alters[0].endswith("NOT VALID")
