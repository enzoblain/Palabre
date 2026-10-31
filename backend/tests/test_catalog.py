"""The role files of the catalog: validation at startup, cross-checks, team constraints and façade shape."""

import hashlib
import json
import shutil
import tomllib
from typing import get_args

import pytest
from pydantic import ValidationError

from app.company import catalog as catalog_module
from app.company.catalog import (
    CATALOG_DIR, GATED_ROLE_KEYS, CatalogError, ExtendedCategory, Permission, Role, held_role_keys, load_catalog,
    load_extended_index, load_personality_pools, load_roles, team_permission_error,
    validate_catalog,
)
from app.company.team import generate_team
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
    roles = load_roles()
    files = {p.stem for p in CATALOG_DIR.glob("*/roles/*.toml")}
    assert set(roles) == files
    assert all(r.kind == "research" for k, r in roles.items() if (CATALOG_DIR / "research/roles" / f"{k}.toml").exists())


def test_permission_literal_matches_permissions_module():
    used = {p for required in MCP_TOOLS.values() for p in required} | set(CLAUDE_TOOLS)
    assert set(get_args(Permission)) == used


def test_event_literal_covers_every_wakes_on_event():
    assert {e for r in load_catalog()["roles"].values() for e in r.wakes_on} <= set(get_args(event_types.EventType))


def test_gated_roles_exist_in_the_company_catalog():
    roles = load_catalog()["roles"]
    assert all(roles[k].kind == "company" for k in GATED_ROLE_KEYS)


def test_invalid_field_names_the_file(catalog_copy):
    path = catalog_copy / "company/roles/qa.toml"
    path.write_text(path.read_text().replace('"report_bug"', '"report_bugs"'))
    with pytest.raises(CatalogError, match=r"(?s)company/roles/qa\.toml.*permissions"):
        load_roles()


def test_unknown_field_is_refused(catalog_copy):
    path = catalog_copy / "company/roles/qa.toml"
    path.write_text(path.read_text() + 'surprise = "x"\n')
    with pytest.raises(CatalogError, match="surprise"):
        load_roles()


def test_broken_toml_names_the_file(catalog_copy):
    (catalog_copy / "company/roles/qa.toml").write_text("title = \n")
    with pytest.raises(CatalogError, match=r"qa\.toml"):
        load_roles()


def test_same_key_in_both_kinds_is_refused(catalog_copy):
    shutil.copy(catalog_copy / "research/roles/skeptic.toml", catalog_copy / "company/roles/skeptic.toml")
    with pytest.raises(CatalogError, match="both company and research"):
        load_roles()


def test_role_combining_merge_and_code_is_refused():
    roles = load_roles()
    bad = Role(**{**roles["dev"].model_dump(), "permissions": ["merge", "code"]})
    with pytest.raises(CatalogError, match="merge and code"):
        validate_catalog({**roles, "dev": bad}, {}, [])


def test_missing_gated_role_is_refused():
    roles = {k: r for k, r in load_roles().items() if k != "security"}
    with pytest.raises(CatalogError, match="security"):
        validate_catalog(roles, {}, [])


def test_seat_with_unknown_role_or_merge_plus_code_is_refused():
    roles = load_roles()
    with pytest.raises(CatalogError, match="unknown"):
        validate_catalog(roles, {"m": {"kind": "company", "seats": [{"roles": ["nobody"]}]}}, [])
    with pytest.raises(CatalogError, match="unknown"):
        validate_catalog(roles, {"m": {"kind": "company", "seats": [{"roles": ["explorer"]}]}}, [])
    with pytest.raises(CatalogError, match="merge and code"):
        validate_catalog(roles, {"m": {"kind": "company", "seats": [{"roles": ["lead", "dev"]}]}}, [])


def test_channel_with_unknown_role_is_refused():
    with pytest.raises(CatalogError, match="unknown"):
        validate_catalog(load_roles(), {}, [{"name": "x", "roles": ["nobody"]}])
    validate_catalog(load_roles(), {}, [{"name": "x", "roles": ["*"]}])


def test_every_predefined_mode_passes_the_checks():
    catalog = load_catalog()
    assert {"startup", "enterprise", "duo", "council"} <= set(catalog["modes"])


def test_team_constraints():
    assert team_permission_error([["lead"], ["dev"], ["reviewer"]], "company") is None
    assert "merge and the code" in team_permission_error([["lead", "dev"]], "company")
    assert "ship_release" in team_permission_error([["lead"], ["lead"]], "company")
    assert team_permission_error([["explorer"], ["skeptic"]], "research") is None


def test_roles_are_typed_and_keep_the_file_order():
    roles = load_catalog()["roles"]
    assert list(roles)[:3] == ["lead", "architect", "product_owner"]
    company_roles = [k for k, r in roles.items() if r.kind == "company"]
    assert list(roles)[len(company_roles)] == "explorer"
    assert all(isinstance(role, Role) for role in roles.values())


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


@pytest.mark.parametrize("field", ["key", "kind"])
def test_role_file_cannot_set_key_or_kind(catalog_copy, field):
    path = catalog_copy / "company/roles/qa.toml"
    path.write_text(f'{field} = "x"\n' + path.read_text())
    with pytest.raises(CatalogError, match=r"qa\.toml.*" + field):
        load_roles()


@pytest.fixture
async def api_client():
    from httpx import ASGITransport, AsyncClient

    from app.config import settings
    from app.main import app

    headers = {"Authorization": f"Bearer {settings.admin_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=headers) as client:
        yield client


async def test_roles_endpoint_adds_tools_to_the_role_fields(api_client):
    from app.company.catalog import load_catalog
    from app.mcp_server.permissions import claude_tools_for, mcp_tools_for

    response = await api_client.get("/api/catalog/roles", params={"kind": "company"})

    assert response.status_code == 200
    roles = response.json()
    expected = {k: r for k, r in load_catalog()["roles"].items() if r.kind == "company"}
    assert list(roles) == list(expected)
    for key, role in roles.items():
        permissions = expected[key].permissions
        assert role["tools"] == {
            "mcp": sorted(mcp_tools_for(permissions, task_run=True)),
            "claude": claude_tools_for(permissions),
        }
        assert {k: v for k, v in role.items() if k != "tools"} == {"effort": None, "archetype": None, **expected[key].model_dump(mode="json", exclude_none=True)}


async def test_roles_endpoint_filters_by_kind(api_client):
    roles = (await api_client.get("/api/catalog/roles", params={"kind": "research"})).json()

    assert roles
    assert {r["kind"] for r in roles.values()} == {"research"}


async def test_limits_endpoint_exposes_models_and_team_size(api_client):
    response = await api_client.get("/api/catalog/limits")

    assert response.status_code == 200
    assert response.json() == {"models": ["haiku", "sonnet", "opus"], "max_agents": 30}


def test_personality_pool_files_feed_the_catalog():
    pools = load_personality_pools()
    catalog = load_catalog()
    assert set(pools) == {"company", "research"}
    assert catalog["personality"]["axes"][0] == {
        "key": "risk", "label": "Risk-taking", "diverse": True,
        "low": "cautious — you limit risk and always want a plan B",
        "high": "bold — you are willing to bet on an ambitious solution if the payoff is worth it",
    }
    assert "diverse" not in catalog["personality"]["axes"][3]
    assert catalog["research"]["personality"]["axes"][0]["key"] == "skepticism"


def test_personality_pool_unknown_field_names_the_file(catalog_copy):
    path = catalog_copy / "research/personality_pool.toml"
    path.write_text("colour = 1\n" + path.read_text())
    with pytest.raises(CatalogError, match=r"(?s)personality_pool\.toml.*colour"):
        load_personality_pools()


def test_personality_pool_axis_typo_names_the_file_and_field(catalog_copy):
    path = catalog_copy / "company/personality_pool.toml"
    path.write_text(path.read_text().replace('label = "Risk-taking"', 'lable = "Risk-taking"', 1))
    with pytest.raises(CatalogError, match=r"(?s)company/personality_pool\.toml.*axes\.0\.lable"):
        load_personality_pools()


def test_loaded_role_permissions_and_wakes_on_are_immutable():
    role = load_catalog()["roles"]["lead"]

    assert isinstance(role.permissions, tuple)
    assert isinstance(role.wakes_on, tuple)
    with pytest.raises(AttributeError):
        role.permissions.append("merge")
    with pytest.raises(ValidationError):
        role.permissions = ()


EXTENDED_JOB = """title = "Kernel Developer"
description = "Works on kernels."
category = "software_development"
archetype = "dev_backend"
order = 500
mission = "Deliver kernel code."
responsibilities = ["Code"]
forbidden = []
deliverables = ["Commits"]
escalation = "The lead decides."
success = "Reliable."
"""


def test_extended_index_gives_a_known_category_and_archetype_to_every_job():
    index = load_extended_index()
    roles = load_roles()
    base = {k for k, r in roles.items() if r.kind == "company" and r.archetype is None}
    assert len(index) > 400
    assert {e.category for e in index.values()} >= set(get_args(ExtendedCategory))
    for entry in index.values():
        assert entry.archetype in base, entry.key
        assert entry.category in get_args(ExtendedCategory) or roles[entry.key].category == entry.category
        assert entry.existing == (entry.key in roles)


def test_no_extended_job_uses_the_lead_or_its_own_permissions():
    roles = load_roles()
    for entry in load_extended_index().values():
        assert entry.archetype != "lead" or entry.existing, entry.key
    extended = [r for r in roles.values() if r.archetype is not None]
    for role in extended:
        assert role.archetype != "lead", role.key
        assert roles[role.archetype].kind == "company" and roles[role.archetype].archetype is None, role.key
        assert (role.permissions, role.wakes_on) == (roles[role.archetype].permissions, roles[role.archetype].wakes_on)
    for path in CATALOG_DIR.glob("*/roles/*.toml"):
        raw = tomllib.loads(path.read_text())
        if "archetype" in raw:
            assert not {"permissions", "wakes_on"} & raw.keys(), path.name


def test_extended_job_cannot_have_the_lead_as_archetype(catalog_copy):
    (catalog_copy / "company/roles/kernel_developer.toml").write_text(EXTENDED_JOB.replace("dev_backend", "lead"))
    with pytest.raises(CatalogError, match="lead cannot be an archetype"):
        load_roles()


def test_index_entry_pointing_to_the_lead_is_refused_unless_existing(catalog_copy):
    index = catalog_copy / "company/extended_roles.toml"
    index.write_text(index.read_text().replace('archetype = "architect"', 'archetype = "lead"', 1))
    with pytest.raises(CatalogError, match="lead cannot be an archetype"):
        load_extended_index()


def test_extended_index_has_unique_names():
    names = [e.name.casefold() for e in load_extended_index().values()]
    assert len(names) == len(set(names))


def test_extended_job_inherits_the_archetype_permissions(catalog_copy):
    (catalog_copy / "company/roles/kernel_developer.toml").write_text(EXTENDED_JOB)
    roles = load_roles()
    assert roles["kernel_developer"].permissions == roles["dev_backend"].permissions
    assert roles["kernel_developer"].wakes_on == roles["dev_backend"].wakes_on
    assert roles["kernel_developer"].model == roles["dev_backend"].model


@pytest.mark.parametrize("field", ["permissions", "wakes_on"])
def test_extended_job_cannot_set_archetype_only_fields(catalog_copy, field):
    value = '["merge"]' if field == "permissions" else '["task_created"]'
    (catalog_copy / "company/roles/kernel_developer.toml").write_text(f"{EXTENDED_JOB}\n{field} = {value}\n")
    with pytest.raises(CatalogError, match=rf"kernel_developer.toml.*cannot set {field}"):
        load_roles()


def test_extended_job_acts_as_its_archetype(catalog_copy):
    (catalog_copy / "company/roles/unlisted_job.toml").write_text(EXTENDED_JOB.replace("dev_backend", "reviewer"))
    catalog_module.load_catalog.cache_clear()
    try:
        roles = load_catalog()["roles"]
        assert held_role_keys(["unlisted_job"], roles) == {"unlisted_job", "reviewer"}
        assert held_role_keys(["qa"], roles) == {"qa"}
        assert held_role_keys(["removed_job"], roles) == {"removed_job"}
    finally:
        catalog_module.load_catalog.cache_clear()


def test_extended_job_with_unknown_archetype_is_refused(catalog_copy):
    (catalog_copy / "company/roles/kernel_developer.toml").write_text(EXTENDED_JOB.replace("dev_backend", "nobody"))
    with pytest.raises(CatalogError, match="kernel_developer.toml.*not a base role"):
        load_roles()


def test_extended_job_cannot_be_an_archetype(catalog_copy):
    (catalog_copy / "company/roles/kernel_developer.toml").write_text(EXTENDED_JOB)
    (catalog_copy / "company/roles/driver_developer.toml").write_text(
        EXTENDED_JOB.replace("dev_backend", "kernel_developer")
    )
    with pytest.raises(CatalogError, match="not a base role"):
        load_roles()


def test_role_file_disagreeing_with_the_index_is_refused(catalog_copy):
    (catalog_copy / "company/roles/kernel_developer.toml").write_text(EXTENDED_JOB.replace("dev_backend", "qa"))
    catalog_module.load_catalog.cache_clear()
    try:
        with pytest.raises(CatalogError, match="disagrees"):
            load_catalog()
    finally:
        catalog_module.load_catalog.cache_clear()


def test_mode_seat_with_an_extended_job_is_refused(catalog_copy):
    (catalog_copy / "company/roles/kernel_developer.toml").write_text(EXTENDED_JOB)
    roles = load_roles()
    mode = {"kind": "company", "seats": [{"roles": ["kernel_developer"]}]}
    with pytest.raises(CatalogError, match="at random"):
        validate_catalog(roles, {"m": mode}, [])
