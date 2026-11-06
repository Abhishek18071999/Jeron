"""high52-v1 (docs/plans/high52-v1.md): close over the 252-session highest high, the
top tenth with a positive 12-1 return on rebalance days, out below rank 0.7."""

from dataclasses import replace

import numpy as np
import pytest

from app.backtest.market import HIGH52_SESSIONS, build_market, high52_ranks
from app.backtest.strategies import HIGH52, STRATEGIES, Tier, rebalance_days
from app.backtest.walkforward import evaluate
from tests.backtest_helpers import market_of
from tests.test_backtest_walkforward import synthetic_inputs

N = HIGH52_SESSIONS


def test_ratio_is_close_over_the_years_high_and_ranks_nearest_first():
    d = N + 10
    rising = np.linspace(50, 150, d)
    falling = np.linspace(150, 50, d)
    close = np.vstack([rising, falling, rising * 0.0 + 100])
    high = close * 1.01
    high[2] = 110.0
    universe = np.ones_like(close, dtype=bool)
    ratio, rank = high52_ranks(close, high, universe)
    assert np.isnan(ratio[:, : N - 1]).all() and np.isnan(rank[:, : N - 1]).all()
    t = d - 1
    assert ratio[0, t] == pytest.approx(1 / 1.01)
    assert 0 < ratio[1, t] < ratio[2, t] < ratio[0, t] <= 1
    assert rank[0, t] == 1.0 and rank[1, t] == 0.0


def test_no_future_data_and_too_few_traded_sessions():
    d = N + 20
    close = np.vstack([np.linspace(50, 150, d), np.linspace(80, 120, d)])
    high = close.copy()
    universe = np.ones_like(close, dtype=bool)
    ratio, rank = high52_ranks(close, high, universe)
    shocked_c, shocked_h = close.copy(), high.copy()
    shocked_c[:, -5:] *= 3
    shocked_h[:, -5:] *= 3
    ratio2, rank2 = high52_ranks(shocked_c, shocked_h, universe)
    assert np.array_equal(np.nan_to_num(ratio[:, :-5]), np.nan_to_num(ratio2[:, :-5]))
    assert np.array_equal(np.nan_to_num(rank[:, :-5]), np.nan_to_num(rank2[:, :-5]))
    sparse = high.copy()
    sparse[1, : N - 100] = np.nan
    r3, k3 = high52_ranks(close, sparse, universe)
    assert np.isnan(r3[1, N - 1]) and np.isnan(k3[1, N - 1])
    out = universe.copy()
    out[0, :] = False
    _, k4 = high52_ranks(close, high, out)
    assert np.isnan(k4[0]).all()


def leaders(n: int = 70):
    bars = [(100.0, 101.0, 99.0, 100.0)] * n
    m = market_of({"A": bars, "B": bars, "C": bars})
    m.high52_rank = np.array([[0.95] * n, [0.95] * n, [0.8] * n])
    m.high52_ratio = np.full((3, n), 0.97)
    m.mom_return = np.array([[0.3] * n, [-0.1] * n, [0.3] * n])
    return m


def test_entries_are_rising_leaders_on_rebalance_days():
    m = leaders()
    entries = HIGH52.entries(m, HIGH52.default)
    first = rebalance_days(m)[0]
    assert first.sum() >= 2
    assert entries[0].tolist() == first.tolist()
    assert not entries[1].any() and not entries[2].any()


def test_exit_below_the_top_thirty_percent_only_on_rebalance_days():
    m = leaders()
    m.high52_rank[2, :] = 0.6
    m.high52_rank[1, :] = np.nan
    ex = HIGH52.exits(m, HIGH52.default)
    assert ex is not None
    first = rebalance_days(m)[0]
    assert ex.when[2].tolist() == first.tolist()
    assert not ex.when[0].any() and not ex.when[1].any()


def test_a_new_invest_strategy_with_one_grid_point():
    s = STRATEGIES["high52"]
    assert s is HIGH52 and s.version == "high52-v1"
    assert s.tier is Tier.INVEST and s.grid == [s.default]
    assert s.registered_on is not None and not s.single_regime
    assert "George and Hwang" in " ".join(s.rules(s.default))
    with pytest.raises(ValueError, match="high52_rank"):
        s.entries(replace(leaders(), high52_rank=None), s.default)


def test_it_runs_through_the_walk_forward():
    inputs = synthetic_inputs(n_stocks=30, seed=11)
    market = build_market(inputs)
    assert market.high52_rank is not None
    result = evaluate(market, HIGH52)
    assert result.strategy.key == "high52"
