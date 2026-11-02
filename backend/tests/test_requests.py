"""Requests to the boss: messages in direction, closed by the boss's next message."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import github, projects, services
from app.errors import WorkflowError
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


async def test_a_decision_already_taken_by_the_boss_is_validated_without_a_request():
    s = FakeSession()
    decision = await services.add_decision(s, 1, 2, "Use Redis", "Faster", LEAD, decided_by_boss=True)
    assert decision.status == DecisionStatus.validated
    assert not [o for o in s.added if isinstance(o, Message)]


async def test_a_decision_proposed_by_default_stays_proposed_with_a_request():
    s = FakeSession()
    decision = await services.add_decision(s, 1, 2, "Use Redis", "Faster", LEAD)
    assert decision.status == DecisionStatus.proposed
    assert len([o for o in s.added if isinstance(o, Message)]) == 1


async def test_only_the_lead_can_record_a_decision_as_decided_by_the_boss():
    dev = make_employee("Maya", "architect")
    with pytest.raises(services.WorkflowError, match="Only the lead"):
        await services.add_decision(FakeSession(), 1, 2, "Use Redis", "Faster", dev, decided_by_boss=True)


async def test_a_decision_from_a_member_is_signed_by_the_lead_and_in_full():
    dev = make_employee("Maya", "architect")
    s = FakeSession()
    long_rationale = "audit " * 500
    await services.add_decision(s, 1, 2, "Use Redis", long_rationale, dev)
    (message,) = [o for o in s.added if isinstance(o, Message)]
    assert message.employee_id == LEAD.id and message.author_name == "Louise"
    assert message.content == f"Use Redis\n\n{long_rationale.strip()}"
    assert "Maya" not in message.content and message.request_author_id == dev.id


async def test_no_lead_means_no_request_from_a_member():
    dev = make_employee("Maya", "architect")
    with pytest.raises(services.WorkflowError, match="no lead"):
        await services.ask_boss(FakeSession(team=()), 1, dev, "x", "question")


async def test_escalating_to_the_boss_is_a_request_in_direction():
    dev = make_employee("Léa", "dev_backend")
    s = FakeSession()
    msg = await services.escalate(s, 1, 4, dev, "boss", "Cloud budget to decide")
    assert msg.conversation_id == 9 and msg.request_kind == "escalation" and msg.request_status == "pending"
    assert msg.employee_id == LEAD.id and msg.content == "Cloud budget to decide" and msg.request_author_id == dev.id
    assert s.events == []


async def test_a_research_group_has_no_direction_to_ask_in():
    s = FakeSession(direction_id=None)
    assert await services.ask_boss(s, 1, LEAD, "why?", "question") is None


async def test_unknown_request_kind_is_refused():
    with pytest.raises(WorkflowError):
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
    answered.request_status = RequestStatus.answered.value
    relayed = await _ask(s, project, dev, "from a member")
    assert relayed.employee_id == lead.id
    # The lead owns every request in direction, the ones relayed for a member included
    assert [m.id for m in await services.list_pending_requests(s, project.id, lead)] == [mine.id, relayed.id]
    assert await services.list_pending_requests(s, project.id, dev) == []


async def test_the_lead_withdraws_and_merges_a_relayed_request(tidy_db):
    s = tidy_db
    project, lead, dev = await _direction(s)
    first, second = await _ask(s, project, dev, "one"), await _ask(s, project, dev, "two")
    done = await services.withdraw_request(s, project.id, lead, first.id, "obsolete")
    assert done.request_status == RequestStatus.withdrawn.value
    new = await services.merge_requests(s, project.id, lead, [second.id], "merged")
    assert new.employee_id == lead.id and second.request_merged_into == new.id


async def test_a_relayed_request_keeps_its_real_author(tidy_db):
    s = tidy_db
    project, lead, dev = await _direction(s)
    relayed, own = await _ask(s, project, dev, "from a member"), await _ask(s, project, lead, "mine")
    assert relayed.employee_id == lead.id and relayed.request_author_id == dev.id
    assert own.request_author_id is None


async def test_the_lead_cannot_withdraw_or_merge_a_relayed_escalation(tidy_db):
    s = tidy_db
    project, lead, dev = await _direction(s)
    escalation = await _ask(s, project, dev, "the lead blocks me", "escalation")
    other = await _ask(s, project, lead, "b")
    with pytest.raises(WorkflowError, match="relayed to the boss"):
        await services.withdraw_request(s, project.id, lead, escalation.id, "obsolete")
    with pytest.raises(WorkflowError, match="relayed to the boss"):
        await services.merge_requests(s, project.id, lead, [escalation.id, other.id], "merged")
    assert escalation.request_status == "pending" and other.request_status == "pending"


async def test_the_lead_can_withdraw_their_own_escalation(tidy_db):
    s = tidy_db
    project, lead, _ = await _direction(s)
    escalation = await _ask(s, project, lead, "blocked", "escalation")
    done = await services.withdraw_request(s, project.id, lead, escalation.id, "unblocked")
    assert done.request_status == RequestStatus.withdrawn.value


async def test_a_deleted_member_escalation_stays_out_of_the_leads_reach(tidy_db):
    s = tidy_db
    project, lead, dev = await _direction(s)
    escalation = await _ask(s, project, dev, "the lead blocks me", "escalation")
    await s.delete(dev)
    await s.flush()
    with pytest.raises(WorkflowError, match="relayed to the boss"):
        await services.withdraw_request(s, project.id, lead, escalation.id, "obsolete")


async def test_the_lead_can_withdraw_an_own_escalation_starting_with_a_name(tidy_db):
    s = tidy_db
    project, lead, dev = await _direction(s)
    escalation = await _ask(s, project, lead, f"{dev.name}: is it blocked?", "escalation")
    assert escalation.request_author_id is None
    done = await services.withdraw_request(s, project.id, lead, escalation.id, "unblocked")
    assert done.request_status == RequestStatus.withdrawn.value


async def test_backfill_marks_prefixed_pending_escalations_and_is_idempotent(tidy_db):
    s = tidy_db
    project, lead, dev = await _direction(s)
    relayed = await _ask(s, project, dev, "blocked", "escalation")
    relayed.content = f"{dev.name}: blocked"
    relayed.request_author_id = None  # as stored before the column existed
    for _ in range(2):
        await projects.backfill_relayed_escalations(s)
        assert relayed.request_author_id == dev.id
    with pytest.raises(WorkflowError, match="relayed to the boss"):
        await services.withdraw_request(s, project.id, lead, relayed.id, "obsolete")


async def test_backfill_runs_once_so_a_later_own_escalation_stays_withdrawable(tidy_db):
    s = tidy_db
    project, lead, dev = await _direction(s)
    await projects.backfill_relayed_escalations(s)
    own = await _ask(s, project, lead, f"{dev.name}: is it blocked?", "escalation")
    await projects.backfill_relayed_escalations(s)  # a restart
    assert own.request_author_id is None
    done = await services.withdraw_request(s, project.id, lead, own.id, "unblocked")
    assert done.request_status == RequestStatus.withdrawn.value


async def test_withdrawing_a_relayed_decision_says_the_boss_did_not_answer(tidy_db):
    s = tidy_db
    project, lead, dev = await _direction(s)
    decision, linked = await _linked_request(s, project, dev)
    twin = await services.ask_boss(s, project.id, lead, "again?", "decision", decision.id)
    await projects.withdraw_request(s, project.id, lead, linked.id, "obsolete")
    assert decision.status == DecisionStatus.rejected
    assert twin.request_comment == "Withdrawn by the lead, not answered by the boss: obsolete"


async def test_withdraw_closes_the_request_and_the_boss_cannot_answer(tidy_db):
    s = tidy_db
    project, lead, _ = await _direction(s)
    request = await _ask(s, project, lead)
    done = await services.withdraw_request(s, project.id, lead, request.id, "done another way")
    assert done.request_status == RequestStatus.withdrawn.value and done.request_comment == "done another way"
    assert await services.list_pending_requests(s, project.id, lead) == []
    reply = await services.post_message(s, project.id, request.conversation_id, "ok", None)
    assert await services.answer_pending_requests(s, project.id, reply) == []


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
    with pytest.raises(WorkflowError, match="at most"):
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
    with pytest.raises(WorkflowError, match="decision or a release"):
        await services.merge_requests(s, project.id, lead, [linked.id, other.id], "merged")
    assert decision.status == DecisionStatus.proposed and linked.request_status == "pending"


async def test_merge_refuses_a_release_request(tidy_db):
    s = tidy_db
    project, lead, _ = await _direction(s)
    _, release_request = await _linked_request(s, project, lead, "release", pr_number=7)
    with pytest.raises(WorkflowError, match="decision or a release"):
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
    with pytest.raises(WorkflowError, match="release"):
        await projects.withdraw_request(s, project.id, lead, request.id, "nope")
    await s.refresh(request)
    await s.refresh(decision)
    assert request.request_status == "pending" and decision.status == DecisionStatus.proposed


async def test_refusals(tidy_db):
    s = tidy_db
    project, lead, dev = await _direction(s)
    other_lead = Employee(project_id=project.id, name="Zoé", title="Lead", model="opus", permissions=[], traits={}, quirks=[], style={}, roles=["lead"], mcp_token="c")
    s.add(other_lead)
    await s.flush()
    answered, theirs, ok = await _ask(s, project, lead), await _ask(s, project, other_lead), await _ask(s, project, lead)
    answered.request_status = RequestStatus.answered.value
    with pytest.raises(WorkflowError, match="no longer pending"):
        await services.withdraw_request(s, project.id, lead, answered.id, "x")
    with pytest.raises(WorkflowError, match="not yours"):
        await services.withdraw_request(s, project.id, lead, theirs.id, "x")
    with pytest.raises(WorkflowError, match="does not exist"):
        await services.withdraw_request(s, project.id, lead, 999, "x")
    with pytest.raises(WorkflowError, match="reason"):
        await services.withdraw_request(s, project.id, lead, ok.id, "  ")
    # One bad request refuses the whole merge: nothing is closed nor created
    with pytest.raises(WorkflowError):
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


def _fake_postgres_connection(stored_definition, ran):
    from types import SimpleNamespace

    class Result:
        def scalar(self):
            return stored_definition

    def execute(statement, params):
        ran.append(("select", str(statement), params))
        return Result()

    return SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        execute=execute,
        exec_driver_sql=lambda sql: ran.append(("raw", sql, None)),
    )


@pytest.mark.parametrize(
    ("stored_definition", "dropped"),
    [("CHECK (request_status IN ('pending'))", True), ("CHECK (request_status IN ('answered'))", False), (None, False)],
)
def test_widen_request_status_check_drops_only_a_stale_constraint(stored_definition, dropped):
    from app import db
    from app.models import REQUEST_STATUS_CHECK

    ran = []
    db._widen_request_status_check(_fake_postgres_connection(stored_definition, ran))
    kind, statement, params = ran[0]
    assert kind == "select" and ":name" in statement and "%s" not in statement
    assert params == {"name": REQUEST_STATUS_CHECK}
    drops = [sql for kind, sql, _ in ran if kind == "raw"]
    assert bool(drops) is dropped
    assert all(REQUEST_STATUS_CHECK in sql and sql.startswith("ALTER TABLE messages DROP") for sql in drops)


# --- The boss answers in the chat ----------------------------------------------------


async def _reply(s, project, conversation_id, text="ok, go"):
    return await services.post_message(s, project.id, conversation_id, text, None)


async def test_the_boss_reply_closes_every_pending_request(tidy_db):
    s = tidy_db
    project, lead, dev = await _direction(s)
    own, relayed = await _ask(s, project, lead, "a"), await _ask(s, project, dev, "b", "escalation")
    withdrawn = await _ask(s, project, lead, "c")
    await services.withdraw_request(s, project.id, lead, withdrawn.id, "obsolete")
    reply = await _reply(s, project, own.conversation_id, "oui, mais doucement")
    closed = await services.answer_pending_requests(s, project.id, reply)
    assert [m.id for m in closed] == [own.id, relayed.id]
    for message in closed:
        assert message.request_status == RequestStatus.answered.value
        assert message.request_comment == "oui, mais doucement" and message.request_answered_at is not None
    assert withdrawn.request_status == RequestStatus.withdrawn.value
    assert await services.list_pending_requests(s, project.id, lead) == []


async def test_a_request_posted_after_the_reply_stays_pending(tidy_db):
    s = tidy_db
    project, lead, _ = await _direction(s)
    first = await _ask(s, project, lead, "a")
    reply = await _reply(s, project, first.conversation_id)
    later = await _ask(s, project, lead, "b")
    assert await services.answer_pending_requests(s, project.id, reply) == [first]
    assert later.request_status == RequestStatus.pending.value


async def test_a_reply_with_nothing_pending_closes_nothing(tidy_db):
    s = tidy_db
    project, lead, _ = await _direction(s)
    note = await services.post_message(s, project.id, await services.direction_conversation_id(s, project.id), "fyi", lead)
    reply = await _reply(s, project, note.conversation_id)
    assert await services.answer_pending_requests(s, project.id, reply) == []


async def test_the_lead_reads_what_the_reply_answers(tidy_db):
    s = tidy_db
    project, lead, _ = await _direction(s)
    decision, linked = await _linked_request(s, project, lead)
    text = services.describe_answered_requests([linked])
    assert text == f"#{linked.id} (decision, about decision #{decision.id}): validate D?"


async def test_the_lead_settles_a_decision_for_the_boss(tidy_db):
    s = tidy_db
    project, lead, _ = await _direction(s)
    decision, _ = await _linked_request(s, project, lead)
    done = await projects.settle_decision_for_boss(s, project.id, lead, decision.id, RequestAnswer.rejected, " too costly ")
    assert done.status == DecisionStatus.rejected and done.decided_at is not None


async def test_a_decision_is_settled_once(tidy_db):
    s = tidy_db
    project, lead, _ = await _direction(s)
    decision, _ = await _linked_request(s, project, lead)
    await projects.settle_decision_for_boss(s, project.id, lead, decision.id, RequestAnswer.validated, "")
    with pytest.raises(WorkflowError, match="already validated"):
        await projects.settle_decision_for_boss(s, project.id, lead, decision.id, RequestAnswer.rejected, "")
    with pytest.raises(WorkflowError, match="does not exist"):
        await projects.settle_decision_for_boss(s, project.id, lead, 999, RequestAnswer.rejected, "")


async def test_a_validated_release_goes_through_merge_release(tidy_db, release):
    s = tidy_db
    project, lead, _ = await _direction(s)
    decision, _ = await _linked_request(s, project, lead, "release", pr_number=42)
    with pytest.raises(WorkflowError, match="merge_release"):
        await projects.settle_decision_for_boss(s, project.id, lead, decision.id, RequestAnswer.validated, "")
    assert release == [] and decision.status == DecisionStatus.proposed


async def test_a_rejected_release_closes_its_pull_request(tidy_db, release):
    s = tidy_db
    project, lead, _ = await _direction(s)
    decision, _ = await _linked_request(s, project, lead, "release", pr_number=42)
    await projects.settle_decision_for_boss(s, project.id, lead, decision.id, RequestAnswer.rejected, "later")
    assert release == [("close", 42)] and decision.status == DecisionStatus.rejected
