"""The role files of the catalog: validation at startup, cross-checks, team constraints and façade shape."""

import hashlib
import json
import shutil
from typing import get_args

import pytest

from app.api.errors import ApiError
from app.api.projects import _check_team
from app.api.schemas import MemberIn
from app.company import catalog as catalog_module
from app.company.catalog import (
    CATALOG_DIR, GATED_ROLE_KEYS, CatalogError, Permission, Role, _load_roles, load_catalog, team_permission_error,
    validate_catalog,
)
from app.company.team import generate_team
from app.errors import ErrorCode
from app.mcp_server.permissions import CLAUDE_TOOLS, MCP_TOOLS
from app.orchestrator import event_types


@pytest.fixture
def catalog_copy(tmp_path, monkeypatch):
    """A writable copy of the catalog files, which the loader reads instead of the real ones."""
    copy = tmp_path / "catalog"
    shutil.copytree(CATALOG_DIR, copy)
    monkeypatch.setattr(catalog_module, "CATALOG_DIR", copy)
    return copy


def test_every_role_file_is_valid_and_the_key_is_the_file_name():
    roles = _load_roles()
    files = {p.stem for p in CATALOG_DIR.glob("*/roles/*.toml")}
    assert set(roles) == files
    assert all(r.kind == "research" for k, r in roles.items() if (CATALOG_DIR / "research/roles" / f"{k}.toml").exists())


def test_permission_literal_matches_permissions_module():
    used = {p for required in MCP_TOOLS.values() for p in required} | set(CLAUDE_TOOLS)
    assert set(get_args(Permission)) == used


def test_event_literal_covers_every_wakes_on_event():
    assert {e for r in load_catalog()["roles"].values() for e in r["wakes_on"]} <= set(get_args(event_types.EventType))


def test_gated_roles_exist_in_the_company_catalog():
    roles = load_catalog()["roles"]
    assert all(roles[k]["kind"] == "company" for k in GATED_ROLE_KEYS)


def test_invalid_field_names_the_file(catalog_copy):
    path = catalog_copy / "company/roles/qa.toml"
    path.write_text(path.read_text().replace('"report_bug"', '"report_bugs"'))
    with pytest.raises(CatalogError, match=r"(?s)company/roles/qa\.toml.*permissions"):
        _load_roles()


def test_unknown_field_is_refused(catalog_copy):
    path = catalog_copy / "company/roles/qa.toml"
    path.write_text(path.read_text() + 'surprise = "x"\n')
    with pytest.raises(CatalogError, match="surprise"):
        _load_roles()


def test_broken_toml_names_the_file(catalog_copy):
    (catalog_copy / "company/roles/qa.toml").write_text("title = \n")
    with pytest.raises(CatalogError, match=r"qa\.toml"):
        _load_roles()


def test_same_key_in_both_kinds_is_refused(catalog_copy):
    shutil.copy(catalog_copy / "research/roles/skeptic.toml", catalog_copy / "company/roles/skeptic.toml")
    with pytest.raises(CatalogError, match="both company and research"):
        _load_roles()


def test_role_combining_merge_and_code_is_refused():
    roles = _load_roles()
    bad = Role(**{**roles["dev"].model_dump(), "permissions": ["merge", "code"]})
    with pytest.raises(CatalogError, match="merge and code"):
        validate_catalog({**roles, "dev": bad}, {}, [])


def test_missing_gated_role_is_refused():
    roles = {k: r for k, r in _load_roles().items() if k != "security"}
    with pytest.raises(CatalogError, match="security"):
        validate_catalog(roles, {}, [])


def test_seat_with_unknown_role_or_merge_plus_code_is_refused():
    roles = _load_roles()
    with pytest.raises(CatalogError, match="unknown"):
        validate_catalog(roles, {"m": {"kind": "company", "seats": [{"roles": ["nobody"]}]}}, [])
    with pytest.raises(CatalogError, match="unknown"):
        validate_catalog(roles, {"m": {"kind": "company", "seats": [{"roles": ["explorer"]}]}}, [])
    with pytest.raises(CatalogError, match="merge and code"):
        validate_catalog(roles, {"m": {"kind": "company", "seats": [{"roles": ["lead", "dev"]}]}}, [])


def test_channel_with_unknown_role_is_refused():
    with pytest.raises(CatalogError, match="unknown"):
        validate_catalog(_load_roles(), {}, [{"name": "x", "roles": ["nobody"]}])
    validate_catalog(_load_roles(), {}, [{"name": "x", "roles": ["*"]}])


def test_every_predefined_mode_passes_the_checks():
    catalog = load_catalog()
    assert {"startup", "enterprise", "duo", "council"} <= set(catalog["modes"])


def test_team_constraints():
    assert team_permission_error([["lead"], ["dev"], ["reviewer"]], "company") is None
    assert "merge and the code" in team_permission_error([["lead", "dev"]], "company")
    assert "ship_release" in team_permission_error([["lead"], ["lead"]], "company")
    assert team_permission_error([["explorer"], ["skeptic"]], "research") is None


def test_facade_keeps_the_dict_shape_and_the_role_order():
    roles = load_catalog()["roles"]
    assert list(roles)[:3] == ["lead", "architect", "product_owner"]
    company_roles = [k for k, r in roles.items() if r["kind"] == "company"]
    assert list(roles)[len(company_roles)] == "explorer"
    assert {"title", "model", "mission", "permissions", "wakes_on", "kind"} <= set(roles["lead"])


# Hash of the team drawn before the catalog was split: a seeded team must not change
PINNED_TEAMS = {
    ("startup", 1): "67b204014e839930",
    ("startup", 42): "84300e1b6cfe0333",
    ("startup", 2024): "710c161ddcf9c04b",
    ("scaleup", 1): "3173d7003ddda7ad",
    ("scaleup", 42): "a21defdd5cee10dc",
    ("scaleup", 2024): "14555597f03d6e6f",
    ("enterprise", 1): "c22a820ed4c0863c",
    ("enterprise", 42): "93b166ea6f2748ac",
    ("enterprise", 2024): "ab850f33ce78d795",
    ("multinational", 1): "2d0fcc8d83c6b7ff",
    ("multinational", 42): "7ef33fd9107f910f",
    ("multinational", 2024): "c5f2b5a5fa9b153f",
    ("duo", 1): "7a72ee10a94f1ddc",
    ("duo", 42): "85fb16635068eacd",
    ("duo", 2024): "086ee643a161e201",
    ("panel", 1): "c95d5b93cfaf44a1",
    ("panel", 42): "59fb82351b116f0c",
    ("panel", 2024): "9ad544ae45c329fc",
    ("council", 1): "757df7768b757b4e",
    ("council", 42): "33ecd2f193675a22",
    ("council", 2024): "a73d99bca2e5d387",
}


@pytest.mark.parametrize(("mode", "seed"), list(PINNED_TEAMS))
def test_seeded_teams_are_unchanged(mode, seed):
    dumped = json.dumps(generate_team(mode, seed).to_dict(), sort_keys=True)
    assert hashlib.sha256(dumped.encode()).hexdigest()[:16] == PINNED_TEAMS[(mode, seed)]


def test_custom_team_with_two_leads_is_a_422():
    members = [MemberIn(name="Ada", roles=["lead"]), MemberIn(name="Bob", roles=["lead"])]
    with pytest.raises(ApiError) as error:
        _check_team(members, "company")
    assert error.value.status_code == 422
    assert error.value.code == ErrorCode.INVALID_TEAM_PERMISSIONS
