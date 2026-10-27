from fastapi import APIRouter

from app.company.team import load_catalog

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
