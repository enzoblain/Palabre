"""REST endpoints exposing the company catalog and team generation."""

from typing import Literal

from fastapi import APIRouter, HTTPException, status

from app.company.team import generate_team, load_catalog, personality_for

Kind = Literal["company", "research"]

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/modes")
async def list_modes(kind: Kind = "company") -> dict:
    """Modes of a kind of project: seats (combined roles), rules and merge process."""
    return {k: m for k, m in load_catalog()["modes"].items() if m["kind"] == kind}


@router.get("/roles")
async def list_roles(kind: Kind = "company") -> dict:
    return {k: r for k, r in load_catalog()["roles"].items() if r["kind"] == kind}


@router.get("/personality")
async def personality_options(kind: Kind = "company") -> dict:
    """Axes, levels, quirks and styles an employee's personality is made of."""
    return personality_for(kind)


@router.get("/modes/{mode}/team")
async def preview_team(mode: str, seed: int | None = None) -> dict:
    """Draw a team without saving it. Create the project with the same seed to keep it."""
    if mode not in load_catalog()["modes"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown mode: {mode}")
    return generate_team(mode, seed).to_dict()


@router.get("/names")
async def list_names() -> list[str]:
    """First names given to employees drawn at random."""
    return load_catalog()["people"]["names"]
