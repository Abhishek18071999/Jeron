"""reversal-v1 (docs/plans/reversal-v1.md): the 5-session reversal rank, no entry after
results, and the exit once the fall is made up."""

from dataclasses import replace
from datetime import timedelta

import numpy as np
import pytest

from app.backtest.market import REVERSAL_SESSIONS, build_market, reversal_ranks
from app.backtest.strategies import (
    REVERSAL,
    REVERSAL_EXIT_AT,
    STRATEGIES,
    Tier,
    recent_results,
)
from app.backtest.walkforward import evaluate
from app.data.events import ResultsDate
from tests.backtest_helpers import market_of
from tests.test_backtest_walkforward import synthetic_inputs

N = REVERSAL_SESSIONS


def test_the_rank_is_the_five_session_return_among_the_universe():
    n = 30
    close = np.vstack([np.full(n, 100.0) for _ in range(4)])
    close[0, -1] = 90.0  # fell 10% on the last day
    close[1, -1] = 95.0
    close[2, -1] = 105.0
    universe = np.ones(close.shape, dtype=bool)
    universe[3, -1] = False
    ret, rank = reversal_ranks(close, universe)
    assert ret[0, -1] == pytest.approx(-0.10)
    assert rank[0, -1] == 0.0 and rank[1, -1] == 0.5 and rank[2, -1] == 1.0
    assert np.isnan(rank[3, -1])
    assert np.all(np.isnan(rank[:, :N]))


def test_the_rank_uses_no_future_data():
    rng = np.random.default_rng(5)
    close = 100 * np.cumprod(1 + 0.02 * rng.standard_normal((6, 60)), axis=1)
    universe = np.ones(close.shape, dtype=bool)
    ret, rank = reversal_ranks(close, universe)
    t = 40
    shocked = close.copy()
    shocked[:, t + 1 :] *= np.linspace(0.5, 2.0, 6)[:, None]
    ret2, rank2 = reversal_ranks(shocked, universe)
    assert np.allclose(ret[:, t], ret2[:, t]) and np.allclose(rank[:, t], rank2[:, t])


def losers(n: int = 30):
    bars = [(100.0, 101.0, 99.0, 100.0)] * n
    m = market_of({"A": bars, "B": bars, "C": bars})
    m.rev_rank = np.array([[0.05] * n, [0.3] * n, [0.6] * n])
    m.rev_return = np.full((3, n), -0.08)
    m.results_session = np.zeros((3, n), dtype=bool)
    return m


def test_entries_are_the_bottom_tenth_without_recent_results():
    m = losers()
    entries = REVERSAL.entries(m, REVERSAL.default)
    assert entries[0].all() and not entries[1].any() and not entries[2].any()
    m.results_session[0, 10] = True
    entries = REVERSAL.entries(m, REVERSAL.default)
    # Out on the results session and the four after it, back on the fifth.
    assert entries[0, :10].all()
    assert not entries[0, 10:15].any()
    assert entries[0, 15:].all()


def test_recent_results_window():
    m = losers()
    m.results_session[1, 3] = True
    recent = recent_results(m)
    assert recent[1].tolist() == [3 <= t <= 7 for t in range(m.close.shape[1])]
    assert not recent[0].any()


def test_the_exit_is_a_rank_back_at_the_middle():
    m = losers()
    m.rev_rank[0, :] = np.nan  # unknown is not an exit
    exits = REVERSAL.exits(m, REVERSAL.default)
    assert exits is not None
    assert not exits.when[0].any() and not exits.when[1].any() and exits.when[2].all()
    assert REVERSAL_EXIT_AT == 0.5
    assert "made up" in " ".join(REVERSAL.rules(REVERSAL.default))


def test_reversal_is_a_new_swing_strategy_with_one_grid_point():
    s = STRATEGIES["reversal"]
    assert s is REVERSAL and s.version == "reversal-v1"
    assert s.tier is Tier.SWING
    assert s.grid == [s.default]
    assert s.results_blackout and s.min_news_score is not None
    assert s.registered_on is not None and not s.single_regime
    with pytest.raises(ValueError, match="rev_rank"):
        s.entries(replace(losers(), rev_rank=None), s.default)
    with pytest.raises(ValueError, match="results calendar"):
        s.entries(replace(losers(), results_session=None), s.default)


def test_reversal_runs_through_the_walk_forward():
    inputs = synthetic_inputs(n_stocks=30, seed=11)
    # A results calendar: every stock reports once a quarter.
    results = {
        s.symbol: [ResultsDate(d, d - timedelta(days=14)) for d in inputs.days[60::63]]
        for s in inputs.stocks
    }
    market = build_market(replace(inputs, results=results))
    assert market.rev_rank is not None
    t = len(market.days) - 1
    defined = market.rev_rank[market.universe[:, t], t]
    assert len(defined[~np.isnan(defined)]) > 10
    result = evaluate(market, REVERSAL)
    assert result.strategy.key == "reversal"
