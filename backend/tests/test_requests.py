"""Requests to the boss: messages in direction answered with validate / reject / nuance."""

from types import SimpleNamespace

import pytest

from app import github, projects, services
from app.api.schemas import RequestAnswerIn
from app.models import Conversation, Decision, DecisionStatus, Event, Message, RequestAnswer, Room

from .conftest import make_employee

LEAD = make_employee("Louise", "lead")


class FakeSession:
    """Serves objects by (model, id), the team for `scalars`, and records what is added."""

    def __init__(self, *objects, team=(LEAD,), direction_id=9):
        self.objects = {(type(o), o.id): o for o in objects}
        self.team, self.direction_id = list(team), direction_id
        self.added, self.executed = [], []

    async def get(self, model, id_):
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
    await projects.answer_request(s, 5, RequestAnswer.nuanced, "Plutôt Valkey")
    assert decision.status == DecisionStatus.proposed and decision.decided_at is None


@pytest.fixture
def release(monkeypatch):
    calls = []

    async def merge(repo, number, title, method):
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
    message = await projects.answer_request(s, 5, RequestAnswer.nuanced, "Attends le fix du login")
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
    msg = await services.escalate(s, 1, 4, dev, "boss", "Budget cloud à arbitrer")
    assert msg.conversation_id == 9 and msg.request_kind == "escalation" and msg.request_status == "pending"
    assert s.events == []


async def test_a_research_group_has_no_direction_to_ask_in():
    s = FakeSession(direction_id=None)
    assert await services.ask_boss(s, 1, LEAD, "why?", "question") is None


async def test_unknown_request_kind_is_refused():
    with pytest.raises(services.WorkflowError):
        await services.ask_boss(FakeSession(), 1, LEAD, "x", "chitchat")
