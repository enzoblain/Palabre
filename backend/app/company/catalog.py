"""Typed catalog: every role, personality preset and personality pool is a TOML file under catalog/company/, validated when the backend starts."""

import tomllib
from functools import cache
from pathlib import Path
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.orchestrator.event_types import EventType

CATALOG_DIR = Path(__file__).with_name("catalog")
SHARED_PATH = Path(__file__).with_name("catalog.toml")

Model = Literal["haiku", "sonnet", "opus"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]
Category = Literal["management", "engineering", "quality", "product", "support"]
# Categories of the extended jobs (extended_roles.toml)
ExtendedCategory = Literal[
    "direction_strategy", "architecture", "software_development", "artificial_intelligence", "data_databases",
    "cybersecurity", "cloud_devops_infrastructure", "networks_telecom", "blockchain_web3", "quality_testing",
    "performance_reliability", "product_project_management", "ux_ui_design", "iot_robotics_embedded",
    "games_3d_multimedia", "advanced_research", "ecommerce_fintech_business", "support_operations",
    "technical_documentation", "specialized_roles",
]
# Keep in sync with mcp_server/permissions.py (MCP_TOOLS values and CLAUDE_TOOLS keys): a test checks it
Permission = Literal[
    "conversation", "propose_decision", "manage_tasks", "request_review", "review", "read_code", "report_bug",
    "edit_room_document", "merge", "ship_release", "manage_channels", "manage_toolchains", "code",
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
MIN_TEAM_SIZE = 4  # Creation (manual and automatic): members wanted, the mandatory member included
MANDATORY_ROLE = "lead"  # The member every company team starts with and cannot do without
MODELS = get_args(Model)

PERSONALITY_POOL_FILE = "personality_pool.toml"
EXTENDED_INDEX_FILE = "extended_roles.toml"
# Fields an extended job takes from its archetype when its file leaves them out
INHERITED_FIELDS = ("permissions", "wakes_on", "model", "effort")
# Inherited fields a file may never set: an extended job's rights come only from its archetype
ARCHETYPE_ONLY_FIELDS = ("permissions", "wakes_on")
KEY_PATTERN = r"^[a-z][a-z0-9_]*$"
MAX_QUIRKS = 5
MAX_QUIRK_LENGTH = 200

Level = Literal[-2, -1, 0, 1, 2]


class CatalogError(Exception):
    """The catalog files are invalid; the message names the file and the field."""


class Role(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=KEY_PATTERN)
    title: str
    description: str
    category: Category | ExtendedCategory
    # Extended job only: the role whose permissions, events and workflow place it inherits
    archetype: str | None = Field(default=None, pattern=KEY_PATTERN)
    order: int  # position in the inventory (the files have no natural order)
    model: Model
    effort: Effort | None = None
    mission: str
    responsibilities: list[str] = Field(min_length=1)
    forbidden: list[str]
    deliverables: list[str]
    escalation: str
    success: str
    # How the role works; optional until every job has its working notes
    method: list[str] = Field(default_factory=list)
    watch_points: list[str] = Field(default_factory=list)
    deliverable_format: str | None = None
    permissions: tuple[Permission, ...]
    wakes_on: tuple[EventType, ...]

    @field_validator("archetype")
    @classmethod
    def _archetype_is_not_lead(cls, archetype: str | None) -> str | None:
        if archetype == LEAD_KEY:
            raise ValueError("the lead cannot be an archetype (it holds unique permissions)")
        return archetype


class ExtendedRoleEntry(BaseModel):
    """One line of the extended jobs index: an English name, its category and the role it behaves like."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=KEY_PATTERN)
    name: str
    category: Category | ExtendedCategory
    archetype: str = Field(pattern=KEY_PATTERN)
    existing: bool = False  # the job is an already existing role, which keeps its own file

    @model_validator(mode="after")
    def _only_the_existing_lead_points_to_the_lead(self) -> "ExtendedRoleEntry":
        if self.archetype == LEAD_KEY and not self.existing:
            raise ValueError("the lead cannot be an archetype (only the existing lead entry points to it)")
        return self


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
    label: str
    description: str
    order: int  # position in the list (the files have no natural order)
    traits: dict[str, Level]
    quirks: list[Annotated[str, Field(min_length=1, max_length=MAX_QUIRK_LENGTH)]] = Field(max_length=MAX_QUIRKS)
    style: PresetStyle


def merge_and_code_conflict(permissions: set[str] | list[str]) -> bool:
    """Whether a set of permissions combines merge and code (one employee must not review their own work)."""
    return {MERGE, CODE} <= set(permissions)


# Set by the loader from the file name
RESERVED_ROLE_FIELDS = frozenset({"key"})


def _read_entry(path: Path) -> dict:
    """The fields of one catalog file; its key comes from the file name."""
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise CatalogError(f"Invalid catalog file {path.relative_to(CATALOG_DIR)}: {exc}") from exc
    if reserved := sorted(RESERVED_ROLE_FIELDS & data.keys()):
        raise CatalogError(
            f"Invalid catalog file {path.relative_to(CATALOG_DIR)}: {', '.join(reserved)} "
            "comes from the file name, not from the file"
        )
    return data


def _build_entry[T: BaseModel](model: type[T], path: Path, data: dict) -> T:
    try:
        return model(key=path.stem, **data)
    except ValidationError as exc:
        raise CatalogError(f"Invalid catalog file {path.relative_to(CATALOG_DIR)}: {exc}") from exc


def _load_entry[T: BaseModel](model: type[T], path: Path) -> T:
    """One catalog file as a `model`."""
    return _build_entry(model, path, _read_entry(path))


def _inherit(data: dict, archetypes: dict[str, Role], path: Path) -> dict:
    """The fields of an extended job's file, completed from its archetype (model and effort set by the file win)."""
    archetype = archetypes.get(data["archetype"])
    if archetype is None:
        raise CatalogError(
            f"Invalid catalog file {path.relative_to(CATALOG_DIR)}: archetype '{data['archetype']}' is not a base role"
        )
    if forbidden := [f for f in ARCHETYPE_ONLY_FIELDS if f in data]:
        raise CatalogError(
            f"Invalid catalog file {path.relative_to(CATALOG_DIR)}: an extended job cannot set "
            f"{', '.join(forbidden)}, it inherits them from its archetype '{data['archetype']}'"
        )
    inherited = {f: getattr(archetype, f) for f in INHERITED_FIELDS if getattr(archetype, f) is not None}
    return {**inherited, **data}


def load_roles() -> dict[str, Role]:
    """Every role, ordered by its `order` field. Extended jobs (with an `archetype`) are built
    after the base roles they inherit from."""
    entries = {p: _read_entry(p) for p in sorted((CATALOG_DIR / "company" / "roles").glob("*.toml"))}
    base = {p.stem: _build_entry(Role, p, d) for p, d in entries.items() if "archetype" not in d}
    extended = (_build_entry(Role, p, _inherit(d, base, p)) for p, d in entries.items() if "archetype" in d)
    return {role.key: role for role in sorted([*base.values(), *extended], key=lambda r: (r.order, r.key))}


def load_extended_index() -> dict[str, ExtendedRoleEntry]:
    """The extended jobs index, company/extended_roles.toml, by key."""
    path = CATALOG_DIR / "company" / EXTENDED_INDEX_FILE
    try:
        with path.open("rb") as f:
            raw = tomllib.load(f)
        return {key: ExtendedRoleEntry(key=key, **fields) for key, fields in raw.items()}
    except (tomllib.TOMLDecodeError, ValidationError) as exc:
        raise CatalogError(f"Invalid catalog file company/{EXTENDED_INDEX_FILE}: {exc}") from exc


def load_personalities() -> dict[str, PersonalityPreset]:
    """Every personality preset, ordered by its `order` field."""
    loaded = sorted(
        (_load_entry(PersonalityPreset, p) for p in (CATALOG_DIR / "company" / "personalities").glob("*.toml")),
        key=lambda x: (x.order, x.key),
    )
    return {preset.key: preset for preset in loaded}


def load_personality_pool() -> PersonalityPool:
    """The personality pool, from catalog/company/personality_pool.toml."""
    return _load_entry(PersonalityPool, CATALOG_DIR / "company" / PERSONALITY_POOL_FILE)


def _personality_pool_dict(pool: PersonalityPool) -> dict:
    """The dict shape callers read; `diverse` is only present on the axes that set it."""
    data = pool.model_dump(exclude={"key"})
    data["axes"] = [{k: v for k, v in a.items() if k != "diverse" or v} for a in data["axes"]]
    return data


def _check_presets(presets: dict[str, PersonalityPreset], personality: dict) -> None:
    """A preset only uses the axes and the styles of the pool."""
    axes = {a["key"] for a in personality["axes"]}
    for preset in presets.values():
        where = f"Personality '{preset.key}'"
        if unknown := sorted(set(preset.traits) - axes):
            raise CatalogError(f"{where} uses unknown axes: {', '.join(unknown)}")
        for name, value in preset.style.model_dump().items():
            if value not in personality["style"][name]:
                raise CatalogError(f"{where} has an unknown {name}: {value}")


def _check_roles(roles: dict[str, Role]) -> None:
    if missing := sorted(GATED_ROLE_KEYS - roles.keys()):
        raise CatalogError(f"Missing roles read by the workflow: {', '.join(missing)}")
    for role in roles.values():
        if merge_and_code_conflict(role.permissions):
            raise CatalogError(f"Role '{role.key}' combines the merge and code permissions")


def _check_extended(roles: dict[str, Role], index: dict[str, ExtendedRoleEntry]) -> None:
    """Archetypes are base roles, names are unique, and a role file agrees with its index line."""
    base = {k for k, r in roles.items() if r.archetype is None}
    names = [entry.name.casefold() for entry in index.values()]
    if duplicated := sorted({n for n in names if names.count(n) > 1}):
        raise CatalogError(f"Extended jobs listed twice: {', '.join(duplicated)}")
    for entry in index.values():
        if entry.archetype not in base:
            raise CatalogError(f"Extended job '{entry.key}' has archetype '{entry.archetype}', which is not a base role")
        role = roles.get(entry.key)
        if entry.existing and role is None:
            raise CatalogError(f"Extended job '{entry.key}' is marked existing but has no role")
        if role is not None and not entry.existing and (role.archetype, role.category) != (entry.archetype, entry.category):
            raise CatalogError(f"Role file '{entry.key}' disagrees with its category or archetype in {EXTENDED_INDEX_FILE}")
    for role in roles.values():
        if role.archetype is not None and role.archetype not in base:
            raise CatalogError(f"Role '{role.key}' has archetype '{role.archetype}', which is not a base role")


def _check_seats(roles: dict[str, Role], modes: dict[str, dict]) -> None:
    for name, mode in modes.items():
        for seat in mode["seats"]:
            unknown = [k for k in seat["roles"] if k not in roles]
            if unknown:
                raise CatalogError(f"Mode '{name}' uses unknown roles: {', '.join(unknown)}")
            if extended := [k for k in seat["roles"] if roles[k].archetype is not None]:
                raise CatalogError(f"Mode '{name}' draws extended jobs at random: {', '.join(extended)}")
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


@cache
def load_catalog() -> dict:
    """The whole catalog as a dict, validated: `roles` holds the role files (as `Role` models),
    `personality` the pool file, `personalities` the presets. Raises CatalogError at the first
    invalid file or cross-check."""
    roles = load_roles()
    with SHARED_PATH.open("rb") as f:
        catalog = tomllib.load(f)
    catalog["extended_index"] = load_extended_index()
    validate_catalog(roles, catalog["modes"], catalog["channels"])
    _check_extended(roles, catalog["extended_index"])
    catalog["personality"] = _personality_pool_dict(load_personality_pool())
    presets = load_personalities()
    _check_presets(presets, catalog["personality"])
    catalog["personalities"] = {k: p.model_dump() for k, p in presets.items()}
    catalog["roles"] = roles
    return catalog


def held_role_keys(role_keys: list[str], roles: dict[str, Role]) -> set[str]:
    """The roles an employee acts as: their own and the archetypes of their extended jobs, so an
    extended job takes the workflow place (gates, events) of its archetype. A key missing from the
    catalog (a removed job) grants nothing."""
    return {*role_keys, *(roles[k].archetype for k in role_keys if k in roles and roles[k].archetype)}


def team_permission_error(roles_by_employee: list[list[str]]) -> str | None:
    """Why a hand-made team breaks the permission rules, else None: nobody combines merge and
    code, and the team has exactly one carrier of each unique permission."""
    roles = load_catalog()["roles"]
    held = [{p for k in keys for p in roles[k].permissions} for keys in roles_by_employee]
    if any(merge_and_code_conflict(h) for h in held):
        return "No employee can hold both the merge and the code permissions"
    for permission in UNIQUE_PERMISSIONS:
        if sum(permission in h for h in held) != 1:
            return f"The team needs exactly one employee with the {permission} permission"
    return None
