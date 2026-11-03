"""REST endpoints exposing the company catalog and team generation."""

from fastapi import APIRouter, status

from app.api.errors import ApiError, ErrorCode
from app.api.schemas import CatalogLimitsOut, PersonalityPresetOut, RandomPersonalityOut, RoleOut, RoleToolsOut
from app.company.catalog import MANDATORY_ROLE, MAX_TEAM_SIZE, MIN_TEAM_SIZE, MODELS, Role, load_catalog
from app.company.team import generate_team, random_personality
from app.mcp_server.permissions import claude_tools_for, mcp_tools_for

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _role_out(role: Role) -> RoleOut:
    permissions = role.permissions
    tools = RoleToolsOut(
        mcp=sorted(mcp_tools_for(permissions, task_run=True)), claude=claude_tools_for(permissions)
    )
    return RoleOut(**role.model_dump(exclude_none=True), tools=tools)


@router.get("/modes")
async def list_modes() -> dict:
    """Modes: seats (combined roles), rules and merge process."""
    return load_catalog()["modes"]


@router.get("/roles")
async def list_roles() -> dict[str, RoleOut]:
    """Jobs, with the MCP and Claude tools their permissions give."""
    return {k: _role_out(r) for k, r in load_catalog()["roles"].items()}


@router.get("/limits")
async def team_limits() -> CatalogLimitsOut:
    """Models an employee can run on, the team size bounds and the member every company needs."""
    return CatalogLimitsOut(
        models=list(MODELS), max_agents=MAX_TEAM_SIZE, min_team_size=MIN_TEAM_SIZE, mandatory_role=MANDATORY_ROLE
    )


@router.get("/personality")
async def personality_options() -> dict:
    """Axes, levels, quirks and styles an employee's personality is made of."""
    return load_catalog()["personality"]


@router.get("/personalities", response_model=dict[str, PersonalityPresetOut])
async def list_personalities() -> dict:
    """Personality presets, to pick from and tweak."""
    return load_catalog()["personalities"]


@router.get("/roles/{role}/random-personality", response_model=RandomPersonalityOut)
async def draw_personality(role: str) -> dict:
    """A random valid personality for a role, for the "random" button (nothing is saved)."""
    if role not in load_catalog()["roles"]:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.ROLE_NOT_FOUND, f"Unknown role: {role}")
    return random_personality()


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
