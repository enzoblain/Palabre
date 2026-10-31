"""Typed catalog: every role, personality preset and personality pool is a TOML file under catalog/<kind>/, validated when the backend starts."""

import tomllib
from functools import cache
from pathlib import Path
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.orchestrator.event_types import EventType

CATALOG_DIR = Path(__file__).with_name("catalog")
SHARED_PATH = Path(__file__).with_name("catalog.toml")
KINDS = ("company", "research")

Kind = Literal["company", "research"]
Model = Literal["haiku", "sonnet", "opus"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]
Category = Literal["management", "engineering", "quality", "product", "support", "research"]
# Keep in sync with mcp_server/permissions.py (MCP_TOOLS values and CLAUDE_TOOLS keys): a test checks it
Permission = Literal[
    "conversation", "propose_decision", "manage_tasks", "request_review", "review", "read_code", "report_bug",
    "edit_room_document", "merge", "ship_release", "manage_channels", "manage_toolchains", "research", "code",
    "run_tests", "edit_docs",
]

# Roles the backend reads by key (merge gates, direction): the loader refuses to start without them
LEAD_KEY = "lead"
REVIEWER_KEY = "reviewer"
QA_KEY = "qa"
SECURITY_KEY = "security"
GATED_ROLE_KEYS = frozenset({LEAD_KEY, REVIEWER_KEY, QA_KEY, SECURITY_KEY})

# Permissions that must never be held together by one employee
MERGE = "merge"
CODE = "code"
# Permissions carried by exactly one employee of a custom team
UNIQUE_PERMISSIONS = ("ship_release", "manage_channels")

# Biggest team a custom project can have (the API refuses more, the front reads it from /catalog/limits)
MAX_TEAM_SIZE = 30
MODELS = get_args(Model)

PERSONALITY_POOL_FILE = "personality_pool.toml"
KEY_PATTERN = r"^[a-z][a-z0-9_]*$"
MAX_QUIRKS = 5
MAX_QUIRK_LENGTH = 200

Level = Literal[-2, -1, 0, 1, 2]


class CatalogError(Exception):
    """The catalog files are invalid; the message names the file and the field."""


class Role(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=KEY_PATTERN)
    kind: Kind
    title: str
    description: str
    category: Category
    order: int  # position in the inventory (the files have no natural order)
    model: Model
    effort: Effort | None = None
    mission: str
    responsibilities: list[str] = Field(min_length=1)
    forbidden: list[str]
    deliverables: list[str]
    escalation: str
    success: str
    permissions: tuple[Permission, ...]
    wakes_on: tuple[EventType, ...]


class PersonalityAxis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=KEY_PATTERN)
    label: str
    low: str
    high: str
    diverse: bool = False  # the team always has one employee on each side of the axis


class PersonalityPool(BaseModel):
    """What the employees' personalities are drawn from: a level per axis, quirks and styles."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=KEY_PATTERN)
    kind: Kind
    levels: list[int] = Field(min_length=1)
    quirks: list[str]
    axes: list[PersonalityAxis] = Field(min_length=1)
    style: dict[str, list[str]]


class PresetStyle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    verbosity: str
    tone: str


class PersonalityPreset(BaseModel):
    """A named personality the boss can pick; an axis left out of `traits` is neutral (0)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=KEY_PATTERN)
    kind: Kind
    label: str
    description: str
    order: int  # position in the list (the files have no natural order)
    traits: dict[str, Level]
    quirks: list[Annotated[str, Field(min_length=1, max_length=MAX_QUIRK_LENGTH)]] = Field(max_length=MAX_QUIRKS)
    style: PresetStyle


def merge_and_code_conflict(permissions: set[str] | list[str]) -> bool:
    """Whether a set of permissions combines merge and code (one employee must not review their own work)."""
    return {MERGE, CODE} <= set(permissions)


# Set by the loader from the file name and the folder
RESERVED_ROLE_FIELDS = frozenset({"key", "kind"})


def _load_entry[T: BaseModel](model: type[T], path: Path, kind: str) -> T:
    """One catalog file as a `model`; its key and kind come from the file name and folder."""
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
        if reserved := sorted(RESERVED_ROLE_FIELDS & data.keys()):
            raise CatalogError(
                f"Invalid catalog file {path.relative_to(CATALOG_DIR)}: {', '.join(reserved)} "
                "come from the file name and folder, not from the file"
            )
        return model(key=path.stem, kind=kind, **data)
    except (tomllib.TOMLDecodeError, ValidationError) as exc:
        raise CatalogError(f"Invalid catalog file {path.relative_to(CATALOG_DIR)}: {exc}") from exc


def load_roles() -> dict[str, Role]:
    """Every role, company then research, each kind ordered by its `order` field."""
    roles: dict[str, Role] = {}
    for kind in KINDS:
        folder = sorted((CATALOG_DIR / kind / "roles").glob("*.toml"))
        for role in sorted((_load_entry(Role, p, kind) for p in folder), key=lambda r: (r.order, r.key)):
            if role.key in roles:
                raise CatalogError(
                    f"Role key '{role.key}' exists in both company and research: gates are read by key, "
                    "a shadowing key would change who can approve"
                )
            roles[role.key] = role
    return roles


def load_personalities() -> dict[str, dict[str, PersonalityPreset]]:
    """Every personality preset by kind, each kind ordered by its `order` field."""
    presets: dict[str, dict[str, PersonalityPreset]] = {}
    for kind in KINDS:
        folder = sorted((CATALOG_DIR / kind / "personalities").glob("*.toml"))
        loaded = sorted((_load_entry(PersonalityPreset, p, kind) for p in folder), key=lambda x: (x.order, x.key))
        presets[kind] = {preset.key: preset for preset in loaded}
    return presets


def load_personality_pools() -> dict[str, PersonalityPool]:
    """The personality pool of each kind, from catalog/<kind>/personality_pool.toml."""
    return {kind: _load_entry(PersonalityPool, CATALOG_DIR / kind / PERSONALITY_POOL_FILE, kind) for kind in KINDS}


def _personality_pool_dict(pool: PersonalityPool) -> dict:
    """The dict shape callers read; `diverse` is only present on the axes that set it."""
    data = pool.model_dump(exclude={"key", "kind"})
    data["axes"] = [{k: v for k, v in a.items() if k != "diverse" or v} for a in data["axes"]]
    return data


def _check_presets(presets: dict[str, dict[str, PersonalityPreset]], personalities: dict[str, dict]) -> None:
    """A preset only uses the axes and the styles of its kind."""
    for kind, by_key in presets.items():
        axes = {a["key"] for a in personalities[kind]["axes"]}
        styles = personalities[kind]["style"]
        for preset in by_key.values():
            where = f"Personality '{preset.key}' ({kind})"
            if unknown := sorted(set(preset.traits) - axes):
                raise CatalogError(f"{where} uses unknown axes: {', '.join(unknown)}")
            for name, value in preset.style.model_dump().items():
                if value not in styles[name]:
                    raise CatalogError(f"{where} has an unknown {name}: {value}")


def _check_roles(roles: dict[str, Role]) -> None:
    if missing := sorted(GATED_ROLE_KEYS - {k for k, r in roles.items() if r.kind == "company"}):
        raise CatalogError(f"Missing company roles read by the workflow: {', '.join(missing)}")
    for role in roles.values():
        if merge_and_code_conflict(role.permissions):
            raise CatalogError(f"Role '{role.key}' combines the merge and code permissions")


def _check_seats(roles: dict[str, Role], modes: dict[str, dict]) -> None:
    for name, mode in modes.items():
        for seat in mode["seats"]:
            unknown = [k for k in seat["roles"] if roles.get(k) is None or roles[k].kind != mode["kind"]]
            if unknown:
                raise CatalogError(f"Mode '{name}' uses unknown {mode['kind']} roles: {', '.join(unknown)}")
            permissions = {p for k in seat["roles"] for p in roles[k].permissions}
            if merge_and_code_conflict(permissions):
                raise CatalogError(f"A seat of mode '{name}' combines the merge and code permissions")


def _check_channels(roles: dict[str, Role], channels: list[dict]) -> None:
    for channel in channels:
        unknown = [k for k in channel["roles"] if k != "*" and k not in roles]
        if unknown:
            raise CatalogError(f"Channel '{channel['name']}' uses unknown roles: {', '.join(unknown)}")


def validate_catalog(roles: dict[str, Role], modes: dict[str, dict], channels: list[dict]) -> None:
    """Every cross-check of the catalog; raises CatalogError at the first broken rule."""
    _check_roles(roles)
    _check_seats(roles, modes)
    _check_channels(roles, channels)


def _shared_catalog() -> dict:
    """catalog.toml, with the research modes merged into `modes` (each carries its `kind`)."""
    with SHARED_PATH.open("rb") as f:
        catalog = tomllib.load(f)
    catalog["modes"] = {k: {**v, "kind": "company"} for k, v in catalog["modes"].items()} | {
        k: {**v, "kind": "research"} for k, v in catalog["research"]["modes"].items()
    }
    return catalog


@cache
def load_catalog() -> dict:
    """The whole catalog as a dict, validated: `roles` holds the role files (as `Role` models), `modes`
    both kinds of modes, `personality` and `research.personality` the pool files. Raises CatalogError at the first invalid file or cross-check."""
    roles = load_roles()
    pools = load_personality_pools()
    catalog = _shared_catalog()
    validate_catalog(roles, catalog["modes"], catalog["channels"])
    catalog["personality"] = _personality_pool_dict(pools["company"])
    catalog["research"]["personality"] = _personality_pool_dict(pools["research"])
    presets = load_personalities()
    _check_presets(presets, {"company": catalog["personality"], "research": catalog["research"]["personality"]})
    catalog["personalities"] = {
        kind: {k: p.model_dump() for k, p in by_key.items()} for kind, by_key in presets.items()
    }
    catalog["roles"] = roles
    return catalog


def team_permission_error(roles_by_employee: list[list[str]], kind: str) -> str | None:
    """Why a hand-made team breaks the permission rules, else None: nobody combines merge and
    code, and a company has exactly one carrier of each unique permission."""
    roles = load_catalog()["roles"]
    held = [{p for k in keys for p in roles[k].permissions} for keys in roles_by_employee]
    if any(merge_and_code_conflict(h) for h in held):
        return "No employee can hold both the merge and the code permissions"
    if kind == "company":
        for permission in UNIQUE_PERMISSIONS:
            if sum(permission in h for h in held) != 1:
                return f"The team needs exactly one employee with the {permission} permission"
    return None
