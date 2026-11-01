"""REST endpoints exposing the company catalog and team generation."""

from typing import Literal

from fastapi import APIRouter, status

from app.api.errors import ApiError, ErrorCode
from app.api.schemas import CatalogLimitsOut, PersonalityPresetOut, RandomPersonalityOut, RoleOut, RoleToolsOut
from app.company.catalog import MANDATORY_ROLE, MAX_TEAM_SIZE, MIN_AUTO_TEAM_SIZE, MODELS, Role, load_catalog
from app.company.team import generate_team, personality_for, random_personality
from app.mcp_server.permissions import claude_tools_for, mcp_tools_for

Kind = Literal["company", "research"]

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _role_out(role: Role) -> RoleOut:
    permissions = role.permissions
    tools = RoleToolsOut(
        mcp=sorted(mcp_tools_for(permissions, task_run=True)), claude=claude_tools_for(permissions)
    )
    return RoleOut(**role.model_dump(exclude_none=True), tools=tools)


@router.get("/modes")
async def list_modes(kind: Kind = "company") -> dict:
    """Modes of a kind of project: seats (combined roles), rules and merge process."""
    return {k: m for k, m in load_catalog()["modes"].items() if m["kind"] == kind}


@router.get("/roles")
async def list_roles(kind: Kind = "company") -> dict[str, RoleOut]:
    """Jobs of a kind, with the MCP and Claude tools their permissions give."""
    return {k: _role_out(r) for k, r in load_catalog()["roles"].items() if r.kind == kind}


@router.get("/limits")
async def team_limits() -> CatalogLimitsOut:
    """Models an employee can run on, the team size bounds and the member every company needs."""
    return CatalogLimitsOut(
        models=list(MODELS), max_agents=MAX_TEAM_SIZE, min_team_size=MIN_AUTO_TEAM_SIZE, mandatory_role=MANDATORY_ROLE
    )


@router.get("/personality")
async def personality_options(kind: Kind = "company") -> dict:
    """Axes, levels, quirks and styles an employee's personality is made of."""
    return personality_for(kind)


@router.get("/personalities", response_model=dict[str, PersonalityPresetOut])
async def list_personalities(kind: Kind = "company") -> dict:
    """Personality presets of a kind of project, to pick from and tweak."""
    return load_catalog()["personalities"][kind]


@router.get("/roles/{role}/random-personality", response_model=RandomPersonalityOut)
async def draw_personality(role: str) -> dict:
    """A random valid personality for a role, for the "random" button (nothing is saved)."""
    found = load_catalog()["roles"].get(role)
    if found is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.ROLE_NOT_FOUND, f"Unknown role: {role}")
    return random_personality(found.kind)


@router.get("/modes/{mode}/team")
async def preview_team(mode: str, seed: int | None = None) -> dict:
    """Draw a team without saving it. Create the project with the same seed to keep it."""
    if mode not in load_catalog()["modes"]:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.MODE_NOT_FOUND, f"Unknown mode: {mode}")
    return generate_team(mode, seed).to_dict()


@router.get("/names")
async def list_names() -> list[str]:
    """First names given to employees drawn at random."""
    return load_catalog()["people"]["names"]
