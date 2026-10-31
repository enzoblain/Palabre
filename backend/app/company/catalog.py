"""Typed catalog: every role is a TOML file under catalog/<kind>/roles/, validated when the backend starts."""

import tomllib
from functools import cache
from pathlib import Path
from typing import Literal

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

KEY_PATTERN = r"^[a-z][a-z0-9_]*$"


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
    permissions: list[Permission]
    wakes_on: list[EventType]


def merge_and_code_conflict(permissions: set[str] | list[str]) -> bool:
    """Whether a set of permissions combines merge and code (one employee must not review their own work)."""
    return {MERGE, CODE} <= set(permissions)


def _load_role(path: Path, kind: str) -> Role:
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
        return Role(key=path.stem, kind=kind, **data)
    except (tomllib.TOMLDecodeError, ValidationError) as exc:
        raise CatalogError(f"Invalid catalog file {path.relative_to(CATALOG_DIR)}: {exc}") from exc


def _load_roles() -> dict[str, Role]:
    """Every role, company then research, each kind ordered by its `order` field."""
    roles: dict[str, Role] = {}
    for kind in KINDS:
        folder = sorted((CATALOG_DIR / kind / "roles").glob("*.toml"))
        for role in sorted((_load_role(p, kind) for p in folder), key=lambda r: (r.order, r.key)):
            if role.key in roles:
                raise CatalogError(
                    f"Role key '{role.key}' exists in both company and research: gates are read by key, "
                    "a shadowing key would change who can approve"
                )
            roles[role.key] = role
    return roles


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
    """The whole catalog as a dict, validated: `roles` holds the role files (as dicts), `modes`
    both kinds of modes. Raises CatalogError at the first invalid file or cross-check."""
    roles = _load_roles()
    _check_roles(roles)
    catalog = _shared_catalog()
    _check_seats(roles, catalog["modes"])
    _check_channels(roles, catalog["channels"])
    catalog["roles"] = {k: r.model_dump(exclude_none=True) for k, r in roles.items()}
    return catalog


def team_permission_error(roles_by_employee: list[list[str]], kind: str) -> str | None:
    """Why a hand-made team breaks the permission rules, else None: nobody combines merge and
    code, and a company has exactly one carrier of each unique permission."""
    roles = load_catalog()["roles"]
    held = [{p for k in keys for p in roles[k]["permissions"]} for keys in roles_by_employee]
    if any(merge_and_code_conflict(h) for h in held):
        return "No employee can hold both the merge and the code permissions"
    if kind == "company":
        for permission in UNIQUE_PERMISSIONS:
            if sum(permission in h for h in held) != 1:
                return f"The team needs exactly one employee with the {permission} permission"
    return None
