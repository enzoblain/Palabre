"""Apple/Swift project creation: refusal without a Mac builder, and the starter Swift package."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import apple, apple_template, worktrees
from app.api import projects as api_projects
from app.api.errors import ApiError
from app.api.schemas import ProjectIn
from app.config import settings
from app.models import AppleHost, Base, ProjectPlatform

NOW = datetime(2030, 1, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'apple.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


def add_host(db, last_seen_at, revoked_at=None) -> None:
    db.add(AppleHost(
        name="mac", token_hash=str(id(last_seen_at)) + str(revoked_at), expires_at=NOW + timedelta(days=1),
        last_seen_at=last_seen_at, revoked_at=revoked_at,
    ))  # fmt: skip


def test_platform_defaults_to_generic():
    assert ProjectIn(name="P").platform == ProjectPlatform.generic


def test_unknown_platform_is_invalid():
    with pytest.raises(ValueError):
        ProjectIn(name="P", platform="android")


async def test_generic_project_needs_no_mac(db):
    await api_projects._check_apple_platform(ProjectIn(name="P"), db)


async def test_apple_project_is_refused_when_the_mode_is_off(db, monkeypatch):
    monkeypatch.setattr(settings, "apple_mode_enabled", False)
    with pytest.raises(ApiError) as refused:
        await api_projects._check_apple_platform(ProjectIn(name="P", platform="apple"), db)
    assert refused.value.status_code == 422
    assert refused.value.code == "apple_host_required"


async def test_apple_project_is_refused_without_a_connected_mac(db, monkeypatch):
    monkeypatch.setattr(settings, "apple_mode_enabled", True)
    add_host(db, last_seen_at=None)
    add_host(db, last_seen_at=datetime.now(UTC) - timedelta(days=1))
    add_host(db, last_seen_at=datetime.now(UTC), revoked_at=NOW)
    await db.commit()
    with pytest.raises(ApiError) as refused:
        await api_projects._check_apple_platform(ProjectIn(name="P", platform="apple"), db)
    assert refused.value.status_code == 422
    assert "aucun Mac builder n'est connecté" in refused.value.detail


async def test_apple_project_is_accepted_with_a_connected_mac(db, monkeypatch):
    monkeypatch.setattr(settings, "apple_mode_enabled", True)
    add_host(db, last_seen_at=datetime.now(UTC))
    await db.commit()
    await api_projects._check_apple_platform(ProjectIn(name="P", platform="apple"), db)


@pytest.mark.parametrize(
    ("name", "expected"),
    [("My Cool App", "MyCoolApp"), ("todo-list", "TodoList"), ("42 things", "App"), ("🚀", "App")],
)
def test_module_name_is_a_valid_swift_identifier(name, expected):
    assert apple_template.module_name(name) == expected


def test_starter_package_has_manifest_source_and_test():
    files = apple_template.starter_files("My App")
    assert set(files) == {
        "Package.swift", "Sources/MyApp/MyApp.swift", "Tests/MyAppTests/MyAppTests.swift",
    }
    assert 'name: "MyApp"' in files["Package.swift"]
    assert "XCTAssertEqual" in files["Tests/MyAppTests/MyAppTests.swift"]


def test_starter_package_holds_no_apple_key_or_token():
    content = "\n".join(apple_template.starter_files("App").values()).lower()
    for forbidden in ("token", "secret", "api_key", "private key", "p8", "team_id", "developmentteam"):
        assert forbidden not in content


def test_initial_files_of_an_apple_project_add_the_package():
    project = SimpleNamespace(name="My App", platform=ProjectPlatform.apple)
    files = worktrees._initial_files(project)
    assert "Package.swift" in files and "README.md" in files
    assert ".build/" in files[".gitignore"] and ".env" in files[".gitignore"]


def test_initial_files_of_a_generic_project_are_unchanged():
    project = SimpleNamespace(name="App", platform=ProjectPlatform.generic)
    assert set(worktrees._initial_files(project)) == {"README.md", ".gitignore"}
