"""The room document endpoint returns the room with its last update date."""

from datetime import datetime

from app.api import rooms
from app.models import Room
from tests.test_generic_rooms import db, make_project  # noqa: F401  (db is a fixture)


async def test_document_returns_a_non_null_updated_at(db):  # noqa: F811
    project = await make_project(db)
    room = Room(project=project, name="direction", kind="direction", summary="Short summary", members=[])
    db.add(room)
    await db.flush()
    await db.refresh(room)

    doc = await rooms.get_document(room.id, db)

    assert isinstance(doc["room"].updated_at, datetime)
    assert doc["room"].model_dump(mode="json")["updated_at"]
