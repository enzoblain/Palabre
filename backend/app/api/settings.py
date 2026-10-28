from fastapi import APIRouter

from app import services
from app.accounts import account_count
from app.api.deps import SessionDep
from app.api.schemas import AppSettings, AppSettingsOut

router = APIRouter(tags=["settings"])


def _settings() -> AppSettingsOut:
    return AppSettingsOut(boss_name=services.boss_name(), claude_accounts=account_count())


@router.get("/settings", response_model=AppSettingsOut)
async def get_settings():
    return _settings()


@router.put("/settings", response_model=AppSettingsOut)
async def update_settings(body: AppSettings, s: SessionDep):
    """Your name: every employee knows you by it, as the CEO."""
    await services.set_boss_name(s, body.boss_name.strip())
    return _settings()
