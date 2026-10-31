"""fip-momentum-v1 (docs/plans/fip-momentum-v1.md): information discreteness over the
12-1 window, the smooth third of the momentum top fifth, momentum-v1's exit."""

from dataclasses import replace

import numpy as np
import pytest

from app.backtest.market import (
    FIP_WINDOW_RETURNS,
    MOMENTUM_LOOKBACK_SESSIONS,
    build_market,
    fip_ranks,
    momentum_ranks,
)
from app.backtest.strategies import (
    FIP_MOMENTUM,
    MOMENTUM,
    STRATEGIES,
    Tier,
    rebalance_days,
)
from app.backtest.walkforward import evaluate
from tests.backtest_helpers import market_of
from tests.test_backtest_walkforward import synthetic_inputs

N = MOMENTUM_LOOKBACK_SESSIONS


def path(up_share: float, n: int = N + 5, total: float = 0.5) -> np.ndarray:
    """A price that ends `total` higher, rising on `up_share` of the days."""
    ups = int(round(up_share * (n - 1)))
    downs = n - 1 - ups
    # Equal-size moves: ups of +a and downs of -b with ups*log(1+a) + downs*log(1-b) = log(1+total).
    b = 0.002
    a = np.exp((np.log(1 + total) - downs * np.log(1 - b)) / ups) - 1
    steps = np.array([1 + a] * ups + [1 - b] * downs)
    np.random.default_rng(1).shuffle(steps)
    return 100 * np.concatenate([[1.0], np.cumprod(steps)])


def test_discreteness_is_low_for_a_smooth_rise_and_high_for_a_jumpy_one():
    smooth, jumpy = path(0.8), path(0.45)
    close = np.vstack([smooth, jumpy])
    universe = np.ones(close.shape, dtype=bool)
    ret, rank = momentum_ranks(close, universe)
    rank[:] = 0.9  # both in the top fifth
    fid, frank = fip_ranks(close, universe, ret, rank)
    t = close.shape[1] - 1
    assert -1 <= fid[0, t] < fid[1, t] <= 1
    assert fid[0, t] < -0.4  # most days with the trend
    assert frank[0, t] == 0.0 and frank[1, t] == 1.0
    assert np.all(np.isnan(fid[:, : FIP_WINDOW_RETURNS + 20]))


def test_the_sign_follows_the_trend():
    falling = 100 * 100 / path(0.8)  # the mirror image: falls on most days
    close = np.vstack([falling])
    universe = np.ones(close.shape, dtype=bool)
    ret, rank = momentum_ranks(close, universe)
    fid, _ = fip_ranks(close, universe, ret, rank)
    t = close.shape[1] - 1
    assert ret[0, t] < 0 and fid[0, t] < -0.4  # continuous, in its own direction


def test_only_the_momentum_top_fifth_is_ranked():
    close = np.vstack([path(0.8), path(0.6), path(0.45)])
    universe = np.ones(close.shape, dtype=bool)
    ret, _ = momentum_ranks(close, universe)
    rank = np.full(close.shape, 0.9)
    rank[1] = 0.5
    _, frank = fip_ranks(close, universe, ret, rank)
    t = close.shape[1] - 1
    assert np.isnan(frank[1, t]) and frank[0, t] == 0.0 and frank[2, t] == 1.0


def test_no_future_data():
    rng = np.random.default_rng(7)
    close = 100 * np.cumprod(1 + 0.02 * rng.standard_normal((8, N + 60)), axis=1)
    universe = np.ones(close.shape, dtype=bool)
    ret, rank = momentum_ranks(close, universe)
    fid, frank = fip_ranks(close, universe, ret, rank)
    t = N + 30
    shocked = close.copy()
    shocked[:, t + 1 :] *= np.linspace(0.5, 2.0, 8)[:, None]
    ret2, rank2 = momentum_ranks(shocked, universe)
    fid2, frank2 = fip_ranks(shocked, universe, ret2, rank2)
    assert np.allclose(fid[:, t], fid2[:, t])
    assert np.array_equal(np.isnan(frank[:, t]), np.isnan(frank2[:, t]))
    assert np.allclose(np.nan_to_num(frank[:, t]), np.nan_to_num(frank2[:, t]))


def leaders(n: int = 70):
    bars = [(100.0, 101.0, 99.0, 100.0)] * n
    m = market_of({"A": bars, "B": bars, "C": bars})
    m.mom_rank = np.array([[0.95] * n, [0.85] * n, [0.7] * n])
    m.mom_return = np.full((3, n), 0.5)
    m.fip_id = np.array([[-0.5] * n, [0.0] * n, [-0.6] * n])
    m.fip_rank = np.array([[0.0] * n, [1.0] * n, [np.nan] * n])
    return m


def test_entries_are_the_smooth_leaders_on_rebalance_days():
    m = leaders()
    entries = FIP_MOMENTUM.entries(m, FIP_MOMENTUM.default)
    first = rebalance_days(m)[0]
    assert first.sum() >= 2
    assert entries[0].tolist() == first.tolist()
    assert not entries[1].any() and not entries[2].any()


def test_the_exit_is_momentum_v1s():
    m = leaders()
    m.mom_rank[1, :] = 0.6
    a = FIP_MOMENTUM.exits(m, FIP_MOMENTUM.default)
    b = MOMENTUM.exits(m, MOMENTUM.default)
    assert a is not None and b is not None
    assert np.array_equal(a.when, b.when) and a.when[1].any()


def test_a_new_invest_strategy_with_one_grid_point():
    s = STRATEGIES["fip-momentum"]
    assert s is FIP_MOMENTUM and s.version == "fip-momentum-v1"
    assert s.tier is Tier.INVEST and s.grid == [s.default]
    assert s.registered_on is not None and not s.single_regime
    assert "frog-in-the-pan" in " ".join(s.rules(s.default))
    with pytest.raises(ValueError, match="fip_rank"):
        s.entries(replace(leaders(), fip_rank=None), s.default)


def test_it_runs_through_the_walk_forward():
    inputs = synthetic_inputs(n_stocks=30, seed=11)
    market = build_market(inputs)
    assert market.fip_rank is not None
    result = evaluate(market, FIP_MOMENTUM)
    assert result.strategy.key == "fip-momentum"
