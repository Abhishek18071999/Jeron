"""low-vol-v1 (docs/plans/low-vol-v1.md): the volatility rank, entries in the calmest
tenth on rebalance days, the exit above 0.30."""

from dataclasses import replace

import numpy as np
import pytest

from app.backtest.market import MOMENTUM_LOOKBACK_SESSIONS, build_market, volatility_ranks
from app.backtest.strategies import (
    LOW_VOL,
    LOW_VOL_EXIT_ABOVE,
    LOW_VOL_MAX_RANK,
    STRATEGIES,
    Tier,
    rebalance_days,
)
from app.backtest.walkforward import evaluate
from tests.backtest_helpers import market_of
from tests.test_backtest_walkforward import synthetic_inputs

N = MOMENTUM_LOOKBACK_SESSIONS


def test_the_calmest_stock_ranks_first():
    rng = np.random.default_rng(3)
    moves = rng.standard_normal((3, N + 10))
    close = 100 * np.cumprod(1 + np.array([[0.005], [0.02], [0.04]]) * moves, axis=1)
    universe = np.ones(close.shape, dtype=bool)
    vol, rank = volatility_ranks(close, universe)
    t = close.shape[1] - 1
    assert vol[0, t] < vol[1, t] < vol[2, t]
    assert (rank[0, t], rank[1, t], rank[2, t]) == (0.0, 0.5, 1.0)
    assert vol[0, t] == pytest.approx(
        np.std(np.diff(close[0, -N:]) / close[0, -N:-1], ddof=1), rel=0.02
    )
    assert np.all(np.isnan(rank[:, : N - 1]))


def test_no_future_data_and_outside_the_universe_is_unknown():
    rng = np.random.default_rng(9)
    close = 100 * np.cumprod(1 + 0.02 * rng.standard_normal((5, N + 40)), axis=1)
    universe = np.ones(close.shape, dtype=bool)
    universe[4, -1] = False
    vol, rank = volatility_ranks(close, universe)
    t = N + 20
    shocked = close.copy()
    shocked[:, t + 1 :] *= np.linspace(0.5, 2.0, 5)[:, None]
    vol2, rank2 = volatility_ranks(shocked, universe)
    assert np.allclose(vol[:, t], vol2[:, t]) and np.allclose(rank[:, t], rank2[:, t])
    assert np.isnan(rank[4, -1]) and not np.isnan(vol[4, -1])


def calm(n: int = 70):
    bars = [(100.0, 101.0, 99.0, 100.0)] * n
    m = market_of({"A": bars, "B": bars, "C": bars})
    m.vol_rank = np.array([[0.05] * n, [0.2] * n, [0.6] * n])
    m.volatility = np.full((3, n), 0.01)
    return m


def test_entries_are_the_calmest_tenth_on_rebalance_days():
    m = calm()
    entries = LOW_VOL.entries(m, LOW_VOL.default)
    first = rebalance_days(m)[0]
    assert first.sum() >= 2
    assert entries[0].tolist() == first.tolist()
    assert not entries[1].any() and not entries[2].any()
    assert LOW_VOL_MAX_RANK == 0.10


def test_the_exit_is_leaving_the_calmest_three_tenths():
    m = calm()
    m.vol_rank[0, :] = np.nan  # unknown is not an exit
    exits = LOW_VOL.exits(m, LOW_VOL.default)
    assert exits is not None
    first = rebalance_days(m)[0]
    assert not exits.when[0].any() and not exits.when[1].any()
    assert exits.when[2].tolist() == first.tolist()
    assert LOW_VOL_EXIT_ABOVE == 0.30


def test_a_new_invest_strategy_with_one_grid_point():
    s = STRATEGIES["low-vol"]
    assert s is LOW_VOL and s.version == "low-vol-v1"
    assert s.tier is Tier.INVEST and s.grid == [s.default]
    assert s.registered_on is not None and not s.single_regime
    with pytest.raises(ValueError, match="vol_rank"):
        s.entries(replace(calm(), vol_rank=None), s.default)


def test_it_runs_through_the_walk_forward():
    market = build_market(synthetic_inputs(n_stocks=30, seed=11))
    assert market.vol_rank is not None
    result = evaluate(market, LOW_VOL)
    assert result.strategy.key == "low-vol"
