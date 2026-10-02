import json
import math
from datetime import date

import numpy as np
import pytest

from app.backtest.market import MarketInputs, SecurityStatusDay, StockData, build_market
from app.backtest.stats import deflated_sharpe, expected_max_sharpe
from app.backtest.strategies import STRATEGIES
from app.backtest.walkforward import evaluate, make_folds
from tests.backtest_helpers import weekdays


def synthetic_inputs(n_days=1700, n_stocks=40, seed=3) -> MarketInputs:
    rng = np.random.default_rng(seed)
    days = weekdays(date(2016, 1, 1), n_days)
    stocks = []
    for k in range(n_stocks):
        c = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.02, n_days)))
        o = c * (1 + rng.normal(0, 0.005, n_days))
        h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.01, n_days)))
        lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.01, n_days)))
        v = rng.integers(200_000, 2_000_000, n_days).astype(float)
        stocks.append(
            StockData(
                f"S{k:02d}",
                days,
                o,
                h,
                lo,
                c,
                v,
                np.ones(n_days),
                c * v,
                np.ones(n_days, dtype=bool),
            )
        )
    index = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n_days)))
    closes = dict(zip(days, index, strict=True))
    vix = dict(zip(days, 15 + 5 * rng.random(n_days), strict=True))
    return MarketInputs(days, stocks, closes, closes, vix)


@pytest.fixture(scope="module")
def market():
    return build_market(synthetic_inputs())


def test_folds_hold_out_the_last_year():
    days = weekdays(date(2016, 1, 1), 2600)
    folds = make_folds(days)
    assert folds.first_tradable == 252
    holdout = days[folds.holdout_start]
    assert (days[-1] - holdout).days < 366 and (
        days[-1] - days[folds.holdout_start - 1]
    ).days >= 365
    starts = [days[s] for s in folds.test_starts]
    # Yearly windows (each starts on the first session on or after the boundary).
    assert all(362 <= (b - a).days <= 369 for a, b in zip(starts, starts[1:], strict=False))
    # At least two years of tradable history before the first test window.
    assert (starts[0] - days[folds.first_tradable]).days >= 730


def test_too_little_history_is_refused():
    with pytest.raises(ValueError):
        make_folds(weekdays(date(2020, 1, 1), 600))


def test_evaluation_is_reproducible(market):
    a = evaluate(market, STRATEGIES["breakout-52w"])
    b = evaluate(market, STRATEGIES["breakout-52w"])
    assert json.dumps(a.summary, sort_keys=True) == json.dumps(b.summary, sort_keys=True)
    assert a.fingerprint == b.fingerprint
    assert [t.net_pnl for t in a.sim.trades] == [t.net_pnl for t in b.sim.trades]


def test_every_variant_is_logged_per_window(market):
    strategy = STRATEGIES["pullback-trend"]
    ev = evaluate(market, strategy)
    windows = {v.window for v in ev.variant_logs}
    assert len(windows) == len(ev.folds.test_starts) + 1
    assert len(ev.variant_logs) == len(windows) * len(strategy.grid)
    for w in windows:
        assert sum(v.chosen for v in ev.variant_logs if v.window == w) == 1
    assert {g["key"] for g in ev.summary["gates"]} >= {
        "expectancy",
        "profit_factor",
        "drawdown",
        "trades",
        "regimes",
        "benchmark",
        "holdout",
    }
    assert all(t.signal_day >= ev.folds.test_starts[0] for t in ev.sim.trades)


def test_future_data_does_not_change_earlier_choices():
    inputs = synthetic_inputs()
    base = evaluate(build_market(inputs), STRATEGIES["breakout-52w"])
    first_test = base.folds.test_starts[0]
    # Rewrite every price after the first test window starts.
    for s in inputs.stocks:
        s.close[first_test:] *= 0.5
        s.open[first_test:] *= 0.5
        s.high[first_test:] *= 0.5
        s.low[first_test:] *= 0.5
    changed = evaluate(build_market(inputs), STRATEGIES["breakout-52w"])
    first = [v for v in base.variant_logs if v.window == base.variant_logs[0].window]
    again = [v for v in changed.variant_logs if v.window == base.variant_logs[0].window]
    assert [(v.label, v.trades, v.sharpe, v.chosen) for v in first] == [
        (v.label, v.trades, v.sharpe, v.chosen) for v in again
    ]


def test_universe_rules_apply_point_in_time():
    inputs = synthetic_inputs(n_days=400, n_stocks=3)
    s0, s1, s2 = inputs.stocks
    s1.close[:] = 10.0  # always below ₹20
    s1.open[:], s1.high[:], s1.low[:] = 10.0, 10.5, 9.5
    gsm_day = inputs.days[300]
    inputs.security_list_days = [gsm_day]
    inputs.security_status = {"S02": {gsm_day: SecurityStatusDay(5.0, True)}}
    m = build_market(inputs)
    assert not m.universe[:, :199].any()  # 200 sessions of history needed
    assert m.universe[0, 250]
    assert not m.universe[1].any()
    assert m.universe[2, 299] and not m.universe[2, 300] and not m.universe[2, 304]
    assert m.universe[2, 306]  # the list is only valid for 7 calendar days
    assert m.band_pct[2, 300] == 5.0


def test_deflated_sharpe():
    # Expected maximum Sharpe grows with the number of trials.
    assert expected_max_sharpe([0.1]) == 0.0
    few = expected_max_sharpe([0.0, 0.02, -0.02])
    many = expected_max_sharpe([0.0, 0.02, -0.02] * 10)
    assert 0 < few < many
    rng = np.random.default_rng(0)
    strong = rng.normal(0.002, 0.01, 1500)
    assert deflated_sharpe(strong, [0.0, 0.01, -0.01]) > 0.95
    noise = rng.normal(0.0, 0.01, 1500)
    assert deflated_sharpe(noise, [0.0, 0.05, -0.05, 0.08]) < 0.5
    assert math.isclose(deflated_sharpe(np.zeros(10), [0.1, 0.2]), 0.0)
