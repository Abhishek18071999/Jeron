"""momentum-v1 (docs/plans/momentum-v1.md): the 12-1 momentum rank, monthly entries and
the exit when a stock leaves the top quarter."""

from dataclasses import replace

import numpy as np
import pytest

from app.backtest.market import (
    MOMENTUM_LOOKBACK_SESSIONS,
    MOMENTUM_SKIP_SESSIONS,
    build_market,
    momentum_ranks,
)
from app.backtest.strategies import (
    MOMENTUM,
    MOMENTUM_EXIT_BELOW,
    STRATEGIES,
    Tier,
    rebalance_days,
)
from app.backtest.walkforward import evaluate
from tests.backtest_helpers import market_of
from tests.test_backtest_walkforward import synthetic_inputs

N = MOMENTUM_LOOKBACK_SESSIONS


@pytest.fixture(scope="module")
def market():
    return build_market(synthetic_inputs(n_stocks=30, seed=11))


def _steady(daily: float, n: int, wiggle: float = 0.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    r = daily + wiggle * rng.standard_normal(n)
    return 100 * np.cumprod(1 + r)


def test_the_rank_prefers_a_steady_riser_over_a_wild_one_with_the_same_return():
    n = N + 30
    steady = _steady(0.002, n, 0.005, seed=1)
    wild = steady * (1 + 0.08 * np.sin(np.arange(n)))  # same trend, far more volatile
    flat = _steady(0.0, n, 0.01, seed=2)
    close = np.vstack([steady, wild, flat])
    universe = np.ones(close.shape, dtype=bool)
    ret, rank = momentum_ranks(close, universe)
    t = n - 1
    expected = close[:, t - MOMENTUM_SKIP_SESSIONS] / close[:, t - N] - 1
    assert np.allclose(ret[:, t], expected)
    assert rank[0, t] > rank[1, t]
    assert rank[2, t] == 0.0
    # Not enough history before session 252.
    assert np.all(np.isnan(rank[:, : N - 1]))


def test_the_rank_uses_no_future_data_and_only_the_universe():
    n = N + 40
    close = np.vstack([_steady(0.001 * k, n, 0.01, seed=k) for k in range(5)])
    universe = np.ones(close.shape, dtype=bool)
    universe[4, -1] = False
    ret, rank = momentum_ranks(close, universe)
    t = n - 10
    shocked = close.copy()
    shocked[:, t + 1 :] *= 3.0  # anything after t must not change day t
    ret2, rank2 = momentum_ranks(shocked, universe)
    assert np.allclose(ret[:, t], ret2[:, t]) and np.allclose(rank[:, t], rank2[:, t])
    assert np.isnan(rank[4, -1])
    members = rank[:4, -1]
    assert members.min() == 0.0 and members.max() == 1.0


def test_the_market_carries_the_rank(market):
    assert market.mom_rank is not None and market.mom_return is not None
    assert np.all(np.isnan(market.mom_rank[~market.universe]))
    t = len(market.days) - 1
    defined = market.mom_rank[market.universe[:, t], t]
    defined = defined[~np.isnan(defined)]
    assert len(defined) > 10 and defined.max() == 1.0


def leaders(n: int = 30):
    bars = [(100.0, 101.0, 99.0, 100.0)] * n
    m = market_of({"A": bars, "B": bars, "C": bars})
    m.mom_rank = np.array([[0.97] * n, [0.92] * n, [0.5] * n])
    m.mom_return = np.full((3, n), 0.6)
    return m


def test_entries_only_on_the_first_session_of_a_month():
    m = leaders()
    first = rebalance_days(m)[0]
    assert first[0] and first.sum() >= 2
    for t in np.flatnonzero(first)[1:]:
        assert m.days[t].month != m.days[t - 1].month
    entries = MOMENTUM.entries(m, {"min_rank": 0.9, "stop_atr": 4.0})
    assert entries[0].tolist() == first.tolist()
    assert entries[1].tolist() == first.tolist()
    assert not entries[2].any()
    entries = MOMENTUM.entries(m, {"min_rank": 0.95, "stop_atr": 4.0})
    assert entries[0].any() and not entries[1].any()


def test_the_exit_is_a_rebalance_day_below_the_top_quarter():
    m = leaders()
    first = rebalance_days(m)[0]
    m.mom_rank[1] = 0.74
    m.mom_rank[0, :] = np.nan  # unknown is not an exit
    exits = MOMENTUM.exits(m, MOMENTUM.default)
    assert exits is not None
    assert not exits.when[0].any()
    assert exits.when[1].tolist() == first.tolist()
    assert exits.when[2].tolist() == first.tolist()
    assert MOMENTUM_EXIT_BELOW == 0.75
    assert "top quarter" in " ".join(MOMENTUM.rules(MOMENTUM.default))


def test_momentum_is_a_new_invest_strategy_with_a_small_grid():
    s = STRATEGIES["momentum"]
    assert s is MOMENTUM and s.version == "momentum-v1"
    assert s.tier is Tier.INVEST
    assert len(s.grid) == 4 and s.default in s.grid
    assert s.registered_on is not None and not s.single_regime
    m = replace(leaders(), mom_rank=None)
    with pytest.raises(ValueError, match="mom_rank"):
        s.entries(m, s.default)


def test_momentum_runs_through_the_walk_forward(market):
    result = evaluate(market, MOMENTUM)
    assert result.strategy.key == "momentum"
