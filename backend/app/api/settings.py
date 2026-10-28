from fastapi import APIRouter, HTTPException, status

from app import services
from app.accounts import account_count
from app.api.deps import SessionDep
from app.api.schemas import AppSettingsIn, AppSettingsOut

router = APIRouter(tags=["settings"])


def _settings() -> AppSettingsOut:
    return AppSettingsOut(
        boss_name=services.boss_name(),
        language=services.team_language(),
        languages=services.LANGUAGES,
        claude_accounts=account_count(),
    )


@router.get("/settings", response_model=AppSettingsOut)
async def get_settings():
    return _settings()


@router.put("/settings", response_model=AppSettingsOut)
async def update_settings(body: AppSettingsIn, s: SessionDep):
    """Your name (every employee knows you by it, as the CEO) and the team's language."""
    if body.language is not None and body.language not in services.LANGUAGES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Language must be one of: {', '.join(services.LANGUAGES)}"
        )
    if body.boss_name is not None:
        await services.set_app_setting(s, "boss_name", body.boss_name.strip())
    if body.language is not None:
        await services.set_app_setting(s, "language", body.language)
    return _settings()
