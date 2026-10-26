"""Compare's price performance (app/explain/performance.py), worked by hand."""

from datetime import date, timedelta

from app.explain.performance import (
    max_drawdown,
    performance,
    rebase,
    returns,
    volatility,
    window_start,
)


def _closes(values, first=date(2025, 1, 1)):
    return [(first + timedelta(days=i), float(v)) for i, v in enumerate(values)]


def test_returns_need_enough_history():
    c = _closes([100] * 22 + [110])  # 23 closes: 1M is the last vs 21 sessions before
    r = returns(c)
    assert r["1M"] == 10.0 and r["3M"] is None and r["1Y"] is None
    year = _closes([50] + [80] * 251 + [100])  # 253 closes
    assert returns(year)["1Y"] == 100.0


def test_drawdown_and_volatility():
    assert max_drawdown(_closes([100, 120, 90, 130])) == -25.0
    assert max_drawdown(_closes([100, 101, 102])) == 0.0
    assert volatility(_closes([100] * 30)) == 0.0
    assert volatility(_closes([100, 101])) is None  # too few days
    up_down = _closes([100 if i % 2 == 0 else 101 for i in range(60)])
    assert volatility(up_down) > 10


def test_series_start_on_the_same_day_at_100():
    a = _closes(range(100, 400))  # 300 days from 1 Jan
    b = _closes([50] * 100, first=date(2025, 6, 1))  # a newer listing
    start = window_start([a, b])
    assert start == date(2025, 6, 1)
    pa, pb = performance(a, start), performance(b, start)
    assert pa.series[0] == (start, 100.0) and pb.series[0] == (start, 100.0)
    assert pa.series[-1][1] == round(399 / a[[d for d, _ in a].index(start)][1] * 100, 2)
    assert rebase(a, date(2030, 1, 1)) == []
    assert performance(a, None).series == []
