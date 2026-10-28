"""Claude usage (runs, tokens, estimated cost) aggregated per account, employee and project."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

PERIODS = ("day", "week", "total")


@dataclass
class Totals:
    runs: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    # Runs that reported no usage / no cost: the sums above leave them out
    runs_without_tokens: int = 0
    runs_without_cost: int = 0

    def add(self, run: Any) -> None:
        self.runs += 1
        if run.input_tokens is None and run.output_tokens is None:
            self.runs_without_tokens += 1
        self.input_tokens += run.input_tokens or 0
        self.output_tokens += run.output_tokens or 0
        self.cache_creation_tokens += run.cache_creation_tokens or 0
        self.cache_read_tokens += run.cache_read_tokens or 0
        if run.cost_usd is None:
            self.runs_without_cost += 1
        else:
            self.cost_usd += run.cost_usd


def period_starts(now: datetime) -> dict[str, datetime | None]:
    """Day: since midnight (UTC, like `now`); week: the last 7 days including today; total: no bound."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {"day": midnight, "week": midnight - timedelta(days=6), "total": None}


def aggregate(runs: Iterable[Any], now: datetime) -> dict[str, dict[str, dict[Any, Totals]]]:
    """period → dimension ("account", "employee", "project") → key → totals.

    Runs need started_at, account, employee_id, project_id and the token/cost fields.
    A run with no recorded account is grouped under the key None."""
    starts = period_starts(now)
    out: dict[str, dict[str, dict[Any, Totals]]] = {
        p: {"account": {}, "employee": {}, "project": {}} for p in PERIODS
    }
    for run in runs:
        keys = {"account": run.account, "employee": run.employee_id, "project": run.project_id}
        for period, start in starts.items():
            if start is not None and run.started_at < start:
                continue
            for dim, key in keys.items():
                out[period][dim].setdefault(key, Totals()).add(run)
    return out


def sum_totals(parts: Iterable[Totals]) -> Totals:
    total = Totals()
    for p in parts:
        for name in total.__dataclass_fields__:
            setattr(total, name, getattr(total, name) + getattr(p, name))
    return total
