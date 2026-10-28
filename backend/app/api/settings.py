from fastapi import APIRouter

from app import services
from app.api.deps import SessionDep
from app.api.schemas import AppSettings

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=AppSettings)
async def get_settings():
    return AppSettings(boss_name=services.boss_name())


@router.put("/settings", response_model=AppSettings)
async def update_settings(body: AppSettings, s: SessionDep):
    """Your name: every employee knows you by it, as the CEO."""
    await services.set_boss_name(s, body.boss_name.strip())
    return AppSettings(boss_name=services.boss_name())
