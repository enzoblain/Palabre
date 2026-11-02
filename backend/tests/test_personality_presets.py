"""Personality presets: validation of the files at startup, application in custom_employee and the API."""

import shutil

import pytest
from pydantic import ValidationError

from app.api.catalog import list_personalities
from app.api.errors import ApiError, ErrorCode
from app.api.projects import _check_team
from app.api.schemas import MemberIn
from app.company import catalog as catalog_module
from app.company.catalog import CATALOG_DIR, CatalogError, load_catalog, load_personalities
from app.company.team import custom_employee


@pytest.fixture
def catalog_copy(tmp_path, monkeypatch):
    """A writable copy of the catalog files, which the loader reads instead of the real ones."""
    copy = tmp_path / "catalog"
    shutil.copytree(CATALOG_DIR, copy)
    monkeypatch.setattr(catalog_module, "CATALOG_DIR", copy)
    return copy


def test_every_preset_file_is_valid():
    presets = load_personalities()
    files = {p.stem for p in (CATALOG_DIR / "company" / "personalities").glob("*.toml")}
    assert set(presets) == files
    assert 4 <= len(presets) <= 6
    personality = load_catalog()["personality"]
    assert all(set(p.traits) <= {a["key"] for a in personality["axes"]} for p in presets.values())
    assert all(p.style.verbosity in personality["style"]["verbosity"] for p in presets.values())


def test_catalog_exposes_the_presets_in_file_order():
    presets = load_catalog()["personalities"]
    assert list(presets)[:2] == ["pragmatic", "perfectionist"]
    assert {"label", "description", "traits", "quirks", "style"} <= set(presets["pragmatic"])


def test_unknown_axis_names_the_file(catalog_copy):
    path = catalog_copy / "company/personalities/pragmatic.toml"
    path.write_text(path.read_text().replace("risk = 1", "courage = 1"))
    load_catalog.cache_clear()
    try:
        with pytest.raises(CatalogError, match=r"pragmatic.*courage"):
            load_catalog()
    finally:
        load_catalog.cache_clear()


def test_unknown_style_value_is_refused(catalog_copy):
    path = catalog_copy / "company/personalities/pragmatic.toml"
    path.write_text(path.read_text().replace('"casual"', '"rude"'))
    load_catalog.cache_clear()
    try:
        with pytest.raises(CatalogError, match="rude"):
            load_catalog()
    finally:
        load_catalog.cache_clear()


@pytest.mark.parametrize(
    ("edit", "match"),
    [
        ("risk = 3", "risk"),
        ("surprise = 1\n", "surprise"),
        ('quirks = ["a", "b", "c", "d", "e", "f"]', "quirks"),
    ],
)
def test_invalid_preset_field_names_the_file(catalog_copy, edit, match):
    path = catalog_copy / "company/personalities/pragmatic.toml"
    text = path.read_text()
    if edit.startswith("risk"):
        text = text.replace("risk = 1", edit)
    elif edit.startswith("quirks"):
        text = text.replace(text[text.index("quirks"):text.index("]") + 1], edit)
    else:
        text = edit + text
    path.write_text(text)
    with pytest.raises(CatalogError, match=rf"(?s)pragmatic\.toml.*{match}"):
        load_personalities()


def test_preset_cannot_set_its_key(catalog_copy):
    path = catalog_copy / "company/personalities/pragmatic.toml"
    path.write_text('key = "x"\n' + path.read_text())
    with pytest.raises(CatalogError, match="key"):
        load_personalities()


def test_preset_fills_traits_quirks_and_style_and_neutralizes_missing_axes():
    preset = load_catalog()["personalities"]["pragmatic"]
    member = custom_employee(["dev"], "Ada", preset="pragmatic", seed=7)
    axes = [a["key"] for a in load_catalog()["personality"]["axes"]]
    assert member.traits == {k: preset["traits"].get(k, 0) for k in axes}
    assert member.quirks == preset["quirks"]
    assert member.style == preset["style"]


def test_explicit_parts_override_the_preset():
    member = custom_employee(
        ["dev"], "Ada", preset="pragmatic", traits={"risk": -2}, quirks=["Mine."], style={"tone": "formal"}, seed=7
    )
    assert member.traits["risk"] == -2
    assert member.traits["complexity"] == -2  # still the preset's
    assert member.quirks == ["Mine."]
    assert member.style == {"verbosity": "concise", "tone": "formal"}


def test_without_a_preset_the_draw_is_unchanged():
    assert custom_employee(["dev"], "Ada", seed=7) == custom_employee(["dev"], "Ada", seed=7, preset=None)


def test_unknown_preset_is_refused():
    with pytest.raises(ValueError, match="Unknown personality"):
        custom_employee(["dev"], "Ada", preset="nobody")


def test_check_team_refuses_an_unknown_preset():
    team = [
        MemberIn(name="Ada", roles=["lead", "reviewer"], personality="nobody"),
    ]
    with pytest.raises(ApiError) as error:
        _check_team(team)
    assert error.value.status_code == 422
    assert error.value.code == ErrorCode.UNKNOWN_PERSONALITY


async def test_endpoint_lists_the_presets():
    presets = await list_personalities()
    assert set(presets) == set(load_catalog()["personalities"])


@pytest.mark.parametrize("key", ["../etc", "Guardian", "x" * 41, ""])
def test_member_personality_key_is_bounded(key):
    with pytest.raises(ValidationError):
        MemberIn(name="Ada", roles=["lead"], personality=key)
