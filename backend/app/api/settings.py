from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status

from sqlalchemy import select

from app import services, usage
from app.accounts import account_count
from app.api.deps import SessionDep
from app.api.schemas import AppSettingsIn, AppSettingsOut, UsageEntry, UsageOut, UsageTotals
from app.models import AgentRun, Employee, Project

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


def _entries(by_period: dict[str, dict], names: dict[int | None, str]) -> list[UsageEntry]:
    keys = {k for period in usage.PERIODS for k in by_period[period]}
    empty = usage.Totals()
    return [
        UsageEntry(
            id=k,
            name=names.get(k),
            **{p: UsageTotals(**asdict(by_period[p].get(k, empty))) for p in usage.PERIODS},
        )
        for k in sorted(keys, key=lambda k: (k is None, k))
    ]


@router.get("/settings/usage", response_model=UsageOut)
async def get_usage(s: SessionDep):
    """Claude usage of the agents' runs by account, employee and project, for today (UTC),
    the last 7 days and since the beginning. Tokens and cost are what claude reported."""
    rows = (
        await s.execute(
            select(
                AgentRun.started_at, AgentRun.account, AgentRun.employee_id, Employee.project_id,
                AgentRun.input_tokens, AgentRun.output_tokens, AgentRun.cache_creation_tokens,
                AgentRun.cache_read_tokens, AgentRun.cost_usd,
            ).join(Employee, Employee.id == AgentRun.employee_id)
        )
    ).all()  # fmt: skip
    agg = usage.aggregate(rows, datetime.now(UTC))
    employees = {e.id: e.name for e in await s.scalars(select(Employee))}
    projects = {p.id: p.name for p in await s.scalars(select(Project))}
    total = {p: UsageTotals(**asdict(usage.sum_totals(agg[p]["account"].values()))) for p in usage.PERIODS}
    return UsageOut(
        accounts=_entries({p: agg[p]["account"] for p in usage.PERIODS}, {}),
        employees=_entries({p: agg[p]["employee"] for p in usage.PERIODS}, employees),
        projects=_entries({p: agg[p]["project"] for p in usage.PERIODS}, projects),
        **total,
    )
