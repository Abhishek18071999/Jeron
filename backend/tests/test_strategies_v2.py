"""The v2 research strategies (docs/plans/strategies-v2.md): relative-strength rank,
trend breakout and RS-leader pullback."""

from dataclasses import replace

import numpy as np
import pytest

from app.backtest.market import Regime, build_market
from app.backtest.strategies import STRATEGIES, TREND_BREAKOUT_MIN_RS
from app.backtest.walkforward import evaluate
from tests.backtest_helpers import market_of
from tests.test_backtest_walkforward import synthetic_inputs


@pytest.fixture(scope="module")
def market():
    return build_market(synthetic_inputs(n_stocks=30, seed=5))


def test_rs6_rank_is_the_universe_percentile_behind_the_score(market):
    rank = market.rs6_rank
    assert rank is not None
    assert np.all(np.isnan(rank[~market.universe]))
    t = len(market.days) - 1
    members = np.flatnonzero(market.universe[:, t])
    defined = members[~np.isnan(rank[members, t])]
    assert len(defined) > 10
    assert np.nanmin(rank[defined, t]) == 0.0 and np.nanmax(rank[defined, t]) == 1.0


def leaders_market(n: int = 6):
    """Three stocks in an uptrend (close 110 > EMA50 100 > EMA200 90), breaking out on
    volume, with RS ranks 0.95, 0.85 and 0.5."""
    bars = [(109.0, 111.0, 104.0, 110.0)] * n
    m = market_of({"A": bars, "B": bars, "C": bars})
    k = len(m.symbols)
    m.ema20 = np.full((k, n), 105.0)
    m.ema50 = np.full((k, n), 100.0)
    m.ema200 = np.full((k, n), 90.0)
    m.prior_high_52w = np.full((k, n), 108.0)
    m.volume_ratio = np.full((k, n), 2.0)
    m.rs6_rank = np.array([[0.95] * n, [0.85] * n, [0.5] * n])
    return m


BREAKOUT = {"volume_x": 1.5, "stop_atr": 3.0}


def test_trend_breakout_needs_a_leader_an_uptrend_and_a_bull_market():
    m = leaders_market()
    s = STRATEGIES["trend-breakout"]
    entries = s.entries(m, BREAKOUT)
    assert entries[:, 0].tolist() == [True, True, False]
    assert TREND_BREAKOUT_MIN_RS == 0.8

    m.regime = [Regime.SIDEWAYS] * len(m.days)
    assert not s.entries(m, BREAKOUT).any()

    m = leaders_market()
    m.ema50[0] = 80.0  # 50-day EMA below the 200-day
    assert s.entries(m, BREAKOUT)[:, 0].tolist() == [False, True, False]

    m = leaders_market()
    m.close[1] = 107.0  # no breakout
    assert s.entries(m, BREAKOUT)[:, 0].tolist() == [True, False, False]

    m = leaders_market()
    assert not s.entries(m, {"volume_x": 2.5, "stop_atr": 3.0}).any()


def test_rs_pullback_buys_a_dip_to_the_20_day_ema_that_holds():
    m = leaders_market()
    s = STRATEGIES["rs-pullback"]
    m.low[:] = 104.0  # touched the 20-day EMA (105), closed above it at 110
    assert s.entries(m, {"min_rs": 0.9, "stop_atr": 2.0})[:, 0].tolist() == [True, False, False]
    assert s.entries(m, {"min_rs": 0.8, "stop_atr": 2.0})[:, 0].tolist() == [True, True, False]

    m.regime = [Regime.SIDEWAYS] * len(m.days)
    assert s.entries(m, {"min_rs": 0.8, "stop_atr": 2.0})[:, 0].tolist() == [True, True, False]
    m.regime = [Regime.BEAR] * len(m.days)
    assert not s.entries(m, {"min_rs": 0.8, "stop_atr": 2.0}).any()

    m = leaders_market()
    m.low[:] = 106.0  # never reached the 20-day EMA
    assert not s.entries(m, {"min_rs": 0.8, "stop_atr": 2.0}).any()
    m.low[:] = 100.0
    m.close[:] = 104.0  # closed below it
    assert not s.entries(m, {"min_rs": 0.8, "stop_atr": 2.0}).any()


def test_rs_strategies_refuse_a_market_without_rs_ranks():
    m = replace(leaders_market(), rs6_rank=None)
    with pytest.raises(ValueError, match="rs6_rank"):
        STRATEGIES["trend-breakout"].entries(m, BREAKOUT)


def test_v2_strategies_are_new_versions_with_small_grids():
    for key in ("trend-breakout", "rs-pullback"):
        s = STRATEGIES[key]
        assert s.version == f"{key}-v1"
        assert len(s.grid) == 4
        assert s.default in s.grid
        assert s.tier.value == "positional"
        assert not s.results_blackout and s.min_news_score is None
        assert "relative strength" in s.rules(s.default)[0]


def test_v2_strategies_run_through_the_walk_forward(market):
    for key in ("trend-breakout", "rs-pullback"):
        result = evaluate(market, STRATEGIES[key])
        assert result.strategy.key == key
