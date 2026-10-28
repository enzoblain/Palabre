"""Channels: the boss writes in direction only, and only the lead is woken by them."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import conversations
from app.api.schemas import MessageIn
from app.models import Conversation, Event, Project, Room


class FakeApiSession:
    def __init__(self, room_kind: str, project_kind: str = "company"):
        self.objects = {
            Conversation: SimpleNamespace(id=1, room_id=2),
            Room: SimpleNamespace(id=2, project_id=3, kind=room_kind),
            Project: SimpleNamespace(id=3, kind=project_kind),
        }
        self.events: list[Event] = []

    async def get(self, model, _id):
        return self.objects[model]

    async def scalar(self, _query):
        return None  # no @mention

    async def execute(self, _statement):
        pass

    async def commit(self):
        pass


@pytest.fixture
def posted(monkeypatch):
    """Records what the boss posted, and the events that follow."""
    log = SimpleNamespace(messages=[], events=[])

    async def post_message(_s, _project_id, conversation_id, content, author):
        log.messages.append((conversation_id, content, author))
        return SimpleNamespace(id=7)

    def emit_event(_s, _project_id, type, payload=None, *, employee_id=None, role=None):
        log.events.append((type, role))

    monkeypatch.setattr(conversations.services, "post_message", post_message)
    monkeypatch.setattr(conversations.services, "emit_event", emit_event)
    monkeypatch.setattr(conversations, "start_question", lambda *_: log.events.append(("research", None)))
    return log


async def test_boss_cannot_write_in_a_team_channel(posted):
    with pytest.raises(HTTPException) as exc:
        await conversations.post_message(1, MessageIn(content="hello"), FakeApiSession("team"))
    assert exc.value.status_code == 403
    assert posted.messages == [] and posted.events == []


async def test_boss_writes_in_direction_and_only_the_lead_is_woken(posted):
    await conversations.post_message(1, MessageIn(content="hello"), FakeApiSession("direction"))
    assert posted.messages == [(1, "hello", None)]
    assert posted.events == [("boss_message", "lead")]


async def test_research_group_has_no_direction(posted):
    await conversations.post_message(1, MessageIn(content="why?"), FakeApiSession("team", "research"))
    assert len(posted.messages) == 1
