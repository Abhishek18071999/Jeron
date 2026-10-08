"""Strategies v3 in the backtester: the results reaction behind post-results drift, the
measured sector and its strength behind sector rotation, and the two strategies."""

from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from app.backtest.features import stock_features
from app.backtest.market import (
    SECTOR_ASSIGN_EVERY,
    SECTOR_LOOKBACK_SESSIONS,
    SECTOR_STRENGTH_SESSIONS,
    Regime,
    _assign_sectors,
    results_reactions,
    sector_ranks,
)
from app.backtest.strategies import STRATEGIES, Tier
from app.data.events import ResultsDate
from tests.backtest_helpers import one_stock_market, weekdays

NAN = float("nan")


def test_results_reaction_is_measured_from_before_the_meeting_to_the_day_after():
    days = weekdays(date(2024, 1, 1), 30)  # 2024-01-01 is a Monday
    close = np.array([[100.0] * 10 + [104.0, 112.0] + [113.0] * 18])
    nifty = np.array([1000.0] * 10 + [1010.0, 1020.0] + [1020.0] * 18)
    volume_ratio = np.full((1, 30), 1.0)
    volume_ratio[0, 10] = 3.0
    meetings = {
        # Meeting on session 10; reaction session 11.
        "AAA": [ResultsDate(days[10], None)],
    }
    reactions = results_reactions(days, ["AAA"], meetings, close, volume_ratio, nifty)
    assert reactions is not None
    reaction, volume = reactions
    assert reaction[0, 11] == pytest.approx(0.12 - 0.02)
    assert volume[0, 11] == 3.0
    assert np.isnan(reaction[0, :11]).all() and np.isnan(reaction[0, 12:]).all()
    assert results_reactions(days, ["AAA"], None, close, volume_ratio, nifty) is None


def test_results_on_a_weekend_count_from_the_next_session():
    days = weekdays(date(2024, 1, 1), 30)
    saturday = date(2024, 1, 13)  # sessions 9 (Fri 12th) and 10 (Mon 15th)
    close = np.array([[100.0] * 10 + [110.0] * 20])
    nifty = np.full(30, 1000.0)
    ratio = np.ones((1, 30))
    reactions = results_reactions(
        days, ["AAA"], {"AAA": [ResultsDate(saturday, None)]}, close, ratio, nifty
    )
    assert reactions is not None
    # m = Monday (10), r = 11: from Friday's close 100 to 110.
    assert reactions[0][0, 11] == pytest.approx(0.10)
    assert np.isnan(reactions[0][0, 10])


def test_missing_closes_and_edges_give_no_reaction():
    days = weekdays(date(2024, 1, 1), 10)
    close = np.array([[100.0, NAN, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0]])
    nifty, ratio = np.full(10, 1000.0), np.ones((1, 10))
    meetings = {
        "AAA": [
            ResultsDate(days[0], None),  # no session before
            ResultsDate(days[2], None),  # no close before (session 1 missing)
            ResultsDate(days[9], None),  # no session after
            ResultsDate(date(2030, 1, 1), None),  # beyond the data
        ]
    }
    reactions = results_reactions(days, ["AAA"], meetings, close, ratio, nifty)
    assert reactions is not None and np.isnan(reactions[0]).all()


def _walk(rng: np.random.Generator, returns: np.ndarray) -> np.ndarray:
    return 100.0 * np.cumprod(1 + returns)


def test_a_stock_is_assigned_the_sector_it_follows():
    rng = np.random.default_rng(7)
    n = SECTOR_LOOKBACK_SESSIONS + 3 * SECTOR_ASSIGN_EVERY
    market = rng.normal(0, 0.01, n)
    own = rng.normal(0, 0.01, (3, n))  # each sector's excess returns
    sectors = [_walk(rng, market + own[k]) for k in range(3)]
    stocks = np.vstack(
        [
            _walk(rng, market + own[1] + rng.normal(0, 0.005, n)),  # follows sector 1
            _walk(rng, market + rng.normal(0, 0.01, n)),  # follows none
        ]
    )
    nifty = _walk(rng, market)
    ranks = sector_ranks(stocks, nifty, sectors)
    first = SECTOR_LOOKBACK_SESSIONS
    assert np.isnan(ranks[:, :first]).all()
    strength = sectors[1][first:] / sectors[1][first - SECTOR_STRENGTH_SESSIONS : -63] - (
        nifty[first:] / nifty[first - SECTOR_STRENGTH_SESSIONS : -63]
    )
    others = [
        sectors[k][first:] / sectors[k][first - SECTOR_STRENGTH_SESSIONS : -63]
        - (nifty[first:] / nifty[first - SECTOR_STRENGTH_SESSIONS : -63])
        for k in (0, 2)
    ]
    expected = 1 + sum((o > strength).astype(int) for o in others)
    assert ranks[0, first:] == pytest.approx(expected)
    assert np.isnan(ranks[1]).all()


def test_sector_assignment_needs_enough_returns():
    rng = np.random.default_rng(1)
    sectors = rng.normal(0, 0.01, (2, SECTOR_LOOKBACK_SESSIONS))
    stock = sectors[0] + rng.normal(0, 0.001, SECTOR_LOOKBACK_SESSIONS)
    sparse = stock.copy()
    sparse[:100] = NAN
    assert list(_assign_sectors(np.vstack([stock, sparse]), sectors)) == [0, -1]


def test_prior_50_session_high_excludes_today():
    n = 120
    highs = [100.0 + (i % 60) for i in range(n)]
    closes = [h - 1 for h in highs]
    f = stock_features(
        weekdays(date(2024, 1, 1), n), highs, closes, closes, [1e6] * n, index_closes={}
    )
    for t in (1, 30, 59, 60, 61, 119):
        assert f.prior_high_50[t] == max(highs[max(0, t - 50) : t])
    assert np.isnan(f.prior_high_50[0])


def _market(n: int = 40):
    m = one_stock_market([(100.0, 101.0, 99.0, 100.0)] * n)
    return replace(
        m,
        ema50=np.full((1, n), 95.0),
        ema200=np.full((1, n), 90.0),
        prior_high_50=np.full((1, n), 99.0),
        sector_rank=np.full((1, n), 2.0),
        results_reaction=np.full((1, n), NAN),
        results_volume_ratio=np.full((1, n), NAN),
    )


def test_results_drift_entries():
    s = STRATEGIES["results-drift"]
    m = _market()
    m.results_reaction[0, [5, 10, 15]] = [0.06, 0.09, 0.09]
    m.results_volume_ratio[0, [5, 10, 15]] = [2.5, 2.0, 1.9]
    assert np.flatnonzero(s.entries(m, {"min_jump": 0.05, "stop_atr": 3.0})[0]).tolist() == [5, 10]
    assert np.flatnonzero(s.entries(m, {"min_jump": 0.08, "stop_atr": 3.0})[0]).tolist() == [10]
    with pytest.raises(ValueError, match="results calendar"):
        s.entries(replace(m, results_reaction=None), s.default)


def test_sector_rotation_entries():
    s = STRATEGIES["sector-rotation"]
    m = _market()
    assert s.entries(m, {"top_n": 2.0, "stop_atr": 3.0}).all()
    m.sector_rank[0, 3] = 3.0
    m.sector_rank[0, 4] = NAN
    m.prior_high_50[0, 5] = 100.0  # the close only equals it
    m.ema50[0, 6] = 101.0  # close below the 50-day EMA
    m.regime[7] = Regime.BEAR
    entries = s.entries(m, {"top_n": 2.0, "stop_atr": 3.0})[0]
    assert np.flatnonzero(~entries).tolist() == [3, 4, 5, 6, 7]
    assert s.entries(m, {"top_n": 3.0, "stop_atr": 3.0})[0, 3]


def test_v3_strategies_are_registered():
    for key in ("results-drift", "sector-rotation"):
        s = STRATEGIES[key]
        assert s.version == f"{key}-v1" and s.tier == Tier.POSITIONAL
        assert len(s.grid) == 4 and s.default in s.grid
        assert not s.results_blackout and s.min_news_score is None
        assert any("Stop" in rule for rule in s.rules(s.default))
