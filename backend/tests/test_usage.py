"""Usage aggregation: periods, grouping and missing data."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app import usage
from app.runner import _usage

NOW = datetime(2026, 10, 28, 15, 0, tzinfo=UTC)


def run(age: timedelta, *, account=1, employee_id=1, project_id=1, tokens=(10, 5, 2, 3), cost=0.5):
    i, o, cc, cr = tokens if tokens else (None,) * 4
    return SimpleNamespace(
        started_at=NOW - age, account=account, employee_id=employee_id, project_id=project_id,
        input_tokens=i, output_tokens=o, cache_creation_tokens=cc, cache_read_tokens=cr, cost_usd=cost,
    )  # fmt: skip


def test_periods():
    runs = [run(timedelta(hours=1)), run(timedelta(days=1)), run(timedelta(days=10))]
    agg = usage.aggregate(runs, NOW)
    totals = {p: agg[p]["account"][1] for p in usage.PERIODS}
    assert [totals[p].runs for p in usage.PERIODS] == [1, 2, 3]
    assert totals["total"].input_tokens == 30
    assert totals["total"].cost_usd == 1.5


def test_grouping():
    runs = [
        run(timedelta(hours=1), account=1, employee_id=1, project_id=1),
        run(timedelta(hours=1), account=2, employee_id=2, project_id=1),
        run(timedelta(hours=1), account=None, employee_id=2, project_id=2),
    ]
    agg = usage.aggregate(runs, NOW)["total"]
    assert set(agg["account"]) == {1, 2, None}
    assert agg["employee"][2].runs == 2
    assert agg["project"][1].runs == 2


def test_missing_data_is_counted_not_invented():
    runs = [run(timedelta(hours=1)), run(timedelta(hours=2), tokens=None, cost=None)]
    t = usage.aggregate(runs, NOW)["total"]["account"][1]
    assert (t.runs, t.runs_without_tokens, t.runs_without_cost) == (2, 1, 1)
    assert (t.input_tokens, t.cost_usd) == (10, 0.5)


def test_sum_totals():
    agg = usage.aggregate([run(timedelta(hours=1), account=1), run(timedelta(hours=1), account=2)], NOW)
    assert usage.sum_totals(agg["day"]["account"].values()).runs == 2


def test_parse_claude_usage():
    parsed = _usage({"input_tokens": 3, "output_tokens": 4, "cache_read_input_tokens": 5})
    assert parsed == {"input_tokens": 3, "output_tokens": 4, "cache_creation_tokens": None, "cache_read_tokens": 5}
    assert _usage(None)["input_tokens"] is None
