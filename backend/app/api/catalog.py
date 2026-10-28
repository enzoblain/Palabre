from fastapi import APIRouter, HTTPException, status

from app.company.team import generate_team, load_catalog

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/modes")
async def list_modes() -> dict:
    """Company modes: seats (combined roles), rules and merge process."""
    return load_catalog()["modes"]


@router.get("/roles")
async def list_roles() -> dict:
    return load_catalog()["roles"]


@router.get("/personality")
async def personality_options() -> dict:
    """Axes, levels, quirks and styles an employee's personality is made of."""
    return load_catalog()["personality"]


@router.get("/modes/{mode}/team")
async def preview_team(mode: str, seed: int | None = None) -> dict:
    """Draw a team without saving it. Create the project with the same seed to keep it."""
    if mode not in load_catalog()["modes"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown mode: {mode}")
    return generate_team(mode, seed).to_dict()
