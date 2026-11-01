"""REST endpoints for application settings."""

from fastapi import APIRouter, status

from app import claude_usage, services
from app.accounts import account_count
from app.api.deps import SessionDep
from app.api.errors import ApiError, ErrorCode
from app.api.schemas import (
    AccountQuotaOut,
    AppSettingsIn,
    AppSettingsOut,
    ModelUsageOut,
    QuotaOut,
    UsageWindowOut,
)

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
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.INVALID_LANGUAGE,
            f"Language must be one of: {', '.join(services.LANGUAGES)}",
        )
    if body.boss_name is not None:
        await services.set_app_setting(s, "boss_name", body.boss_name.strip())
    if body.language is not None:
        await services.set_app_setting(s, "language", body.language)
    return _settings()


def _window(w: claude_usage.Window | None) -> UsageWindowOut | None:
    return UsageWindowOut(used_percent=w.used_percent, resets_at=w.resets_at) if w else None


@router.get("/settings/quota", response_model=QuotaOut)
async def get_quota():
    """Real quota of each Claude account, as /usage shows it: 5h session, week, week by model.
    Read from Claude's usage API (cached ~1 min); an account that fails gets an `error`, the others are unaffected."""
    return QuotaOut(
        accounts=[
            AccountQuotaOut(
                account=a.account,
                error=a.error,
                session=_window(a.session),
                week=_window(a.week),
                models=[ModelUsageOut(model=m, used_percent=w.used_percent, resets_at=w.resets_at) for m, w in sorted(a.models.items())],
            )
            for a in await claude_usage.fetch_all()
        ]
    )
