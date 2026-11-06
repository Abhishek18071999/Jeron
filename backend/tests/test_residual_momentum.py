"""residual-momentum-v1 (docs/plans/residual-momentum-v1.md): market-model residuals over
the 12-1 window, their sum over their standard deviation, the top tenth on rebalance
days, out below rank 0.75."""

from dataclasses import replace

import numpy as np
import pytest

from app.backtest.market import (
    FIP_WINDOW_RETURNS,
    MOMENTUM_SKIP_SESSIONS,
    build_market,
    residual_momentum_ranks,
)
from app.backtest.strategies import RESIDUAL_MOMENTUM, STRATEGIES, Tier, rebalance_days
from app.backtest.walkforward import evaluate
from tests.backtest_helpers import market_of
from tests.test_backtest_walkforward import synthetic_inputs

N, SKIP = FIP_WINDOW_RETURNS, MOMENTUM_SKIP_SESSIONS


def _prices(returns: np.ndarray, start: float = 100.0) -> np.ndarray:
    return start * np.concatenate([[1.0], np.cumprod(1 + returns)])


def test_score_matches_a_direct_least_squares_fit():
    rng = np.random.default_rng(3)
    d = N + SKIP + 40
    mkt = rng.normal(0.0005, 0.01, d - 1)
    stock = 0.0008 + 1.3 * mkt + rng.normal(0, 0.012, d - 1)
    close = np.vstack([_prices(stock)])
    index = _prices(mkt, 1000.0)
    universe = np.ones_like(close, dtype=bool)
    score, rank = residual_momentum_ranks(close, universe, index)
    assert np.isnan(score[:, : N + SKIP - 1]).all()
    t = d - 1
    # The returns at sessions t - SKIP - N + 1 .. t - SKIP; return k sits at session k + 1.
    r = stock[t - SKIP - N : t - SKIP]
    m = mkt[t - SKIP - N : t - SKIP]
    beta = np.polyfit(m, r, 1)[0]
    resid = r - beta * m
    assert score[0, t] == pytest.approx(resid.sum() / resid.std(ddof=1), rel=1e-6)
    assert rank[0, t] == 0.5  # alone in the universe


def test_a_stock_that_only_rode_the_market_ranks_below_one_that_rose_on_its_own():
    rng = np.random.default_rng(7)
    d = N + SKIP + 5
    mkt = rng.normal(0.004, 0.01, d - 1)  # a fast-rising market
    noise = rng.normal(0, 0.008, (2, d - 1))
    rider = 2.0 * mkt + noise[0]  # high beta, nothing of its own
    own = 0.0005 + 0.5 * mkt + noise[1]  # low beta, a steady excess return
    close = np.vstack([_prices(rider), _prices(own)])
    universe = np.ones_like(close, dtype=bool)
    score, rank = residual_momentum_ranks(close, universe, _prices(mkt, 1000.0))
    t = d - 1
    total = close[:, t - SKIP] / close[:, t - SKIP - N] - 1
    assert total[0] > total[1]  # plain momentum would prefer the rider
    assert score[1, t] > score[0, t] and rank[1, t] == 1.0 and rank[0, t] == 0.0


def test_no_future_data_too_few_returns_and_outside_the_universe():
    rng = np.random.default_rng(11)
    d = N + SKIP + 30
    mkt = rng.normal(0.0005, 0.01, d - 1)
    close = np.vstack([_prices(rng.normal(0.001, 0.02, d - 1)) for _ in range(3)])
    index = _prices(mkt, 1000.0)
    universe = np.ones_like(close, dtype=bool)
    score, rank = residual_momentum_ranks(close, universe, index)
    shocked = close.copy()
    shocked[:, -5:] *= 3
    shocked_index = index.copy()
    shocked_index[-5:] *= 0.5
    score2, rank2 = residual_momentum_ranks(shocked, universe, shocked_index)
    assert np.array_equal(np.nan_to_num(score[:, :-5]), np.nan_to_num(score2[:, :-5]))
    assert np.array_equal(np.nan_to_num(rank[:, :-5]), np.nan_to_num(rank2[:, :-5]))
    sparse = close.copy()
    sparse[1, : N - 100] = np.nan
    s3, k3 = residual_momentum_ranks(sparse, universe, index)
    assert np.isnan(s3[1, N + SKIP - 1]) and np.isnan(k3[1, N + SKIP - 1])
    out = universe.copy()
    out[0, :] = False
    _, k4 = residual_momentum_ranks(close, out, index)
    assert np.isnan(k4[0]).all()


def leaders(n: int = 70):
    bars = [(100.0, 101.0, 99.0, 100.0)] * n
    m = market_of({"A": bars, "B": bars, "C": bars})
    m.resmom_rank = np.array([[0.95] * n, [0.85] * n, [0.9] * n])
    m.resmom_score = np.full((3, n), 3.0)
    return m


def test_entries_are_the_top_tenth_on_rebalance_days():
    m = leaders()
    entries = RESIDUAL_MOMENTUM.entries(m, RESIDUAL_MOMENTUM.default)
    first = rebalance_days(m)[0]
    assert first.sum() >= 2
    assert entries[0].tolist() == first.tolist()
    assert entries[2].tolist() == first.tolist()
    assert not entries[1].any()


def test_exit_below_the_top_quarter_only_on_rebalance_days():
    m = leaders()
    m.resmom_rank[2, :] = 0.7
    m.resmom_rank[1, :] = np.nan
    ex = RESIDUAL_MOMENTUM.exits(m, RESIDUAL_MOMENTUM.default)
    assert ex is not None
    first = rebalance_days(m)[0]
    assert ex.when[2].tolist() == first.tolist()
    assert not ex.when[0].any() and not ex.when[1].any()


def test_a_new_invest_strategy_with_one_grid_point():
    s = STRATEGIES["residual-momentum"]
    assert s is RESIDUAL_MOMENTUM and s.version == "residual-momentum-v1"
    assert s.tier is Tier.INVEST and s.grid == [s.default]
    assert s.registered_on is not None and not s.single_regime
    assert "Blitz, Huij and Martens" in " ".join(s.rules(s.default))
    with pytest.raises(ValueError, match="resmom_rank"):
        s.entries(replace(leaders(), resmom_rank=None), s.default)


def test_it_runs_through_the_walk_forward():
    inputs = synthetic_inputs(n_stocks=30, seed=11)
    market = build_market(inputs)
    assert market.resmom_rank is not None
    result = evaluate(market, RESIDUAL_MOMENTUM)
    assert result.strategy.key == "residual-momentum"
