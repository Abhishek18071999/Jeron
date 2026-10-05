"""The market mood rule (app.market.mood), without a database."""

from datetime import date, timedelta

import numpy as np
import pytest

from app.backtest.market import Regime, market_state
from app.market.mood import (
    DEFEND_RISK_MULTIPLIER,
    HIGH_LOW_SESSIONS,
    Mode,
    RegimeDetail,
    StockMood,
    breadth,
    market_mood,
    mode_for,
    regime_detail,
    sector_strength,
)

DAY = date(2026, 10, 1)


def _stock(
    symbol="A",
    close=110.0,
    ema200=100.0,
    sector="IT",
    n500=True,
    ret=0.1,
    high=111.0,
    low=105.0,
    prior_high=120.0,
    prior_low=90.0,
    sessions=HIGH_LOW_SESSIONS,
) -> StockMood:
    return StockMood(
        symbol, sector, n500, close, ema200, ret, high, low, prior_high, prior_low, sessions
    )


def _regime(risk_off=False, n50_below=False, vix_high=False) -> RegimeDetail:
    return RegimeDetail(
        day=DAY,
        regime=Regime.BULL,
        risk_off=risk_off,
        nifty50=95.0 if n50_below else 105.0,
        nifty50_ema200=100.0,
        nifty50_below=n50_below,
        vix=30.0 if vix_high else 12.0,
        vix_top_decile=25.0,
        vix_high=vix_high,
    )


def _days(n: int) -> list[date]:
    start = date(2020, 1, 1)
    return [start + timedelta(days=i) for i in range(n)]


@pytest.mark.parametrize("seed", range(6))
def test_regime_detail_agrees_with_the_engine(seed):
    rng = np.random.default_rng(seed)
    days = _days(900)
    walk = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, len(days))))
    n500 = {d: float(v) for d, v in zip(days, walk, strict=True)}
    n50 = {d: float(v) * 1.1 for d, v in zip(days, walk, strict=True)}
    vix = {d: float(v) for d, v in zip(days, rng.uniform(10, 30, len(days)), strict=True)}
    if seed % 2:
        vix[days[-1]] = 40.0  # in the top decile
    detail = regime_detail(days, n500, n50, vix)
    state = market_state(days, n500, n50, vix)
    assert detail is not None and state is not None
    assert detail.risk_off == state.risk_off
    assert detail.regime == state.regime
    assert detail.risk_off == (detail.nifty50_below or detail.vix_high)
    if seed % 2:
        assert detail.vix_high and detail.vix_top_decile is not None


def test_regime_detail_without_vix_or_history():
    days = _days(100)
    n = {d: 100.0 + i for i, d in enumerate(days)}
    detail = regime_detail(days, n, n, {})
    assert detail is not None
    assert detail.nifty50_ema200 is None and not detail.nifty50_below
    assert detail.vix is None and not detail.vix_high and not detail.risk_off
    assert regime_detail([], {}, {}, {}) is None


def test_new_highs_and_lows_need_a_full_year():
    assert _stock(high=121.0).new_high
    assert not _stock(high=120.0).new_high  # equal is not new
    assert _stock(low=89.0).new_low
    assert not _stock(high=121.0, sessions=HIGH_LOW_SESSIONS - 1).new_high
    assert not _stock(low=1.0, prior_low=None).new_low


def test_breadth_counts():
    stocks = [
        _stock("A", close=110, high=130),  # above, new high
        _stock("B", close=90, low=80, n500=False),  # below, new low
        _stock("C", close=90, low=80),  # below, new low
        _stock("D", ema200=None),  # too short for the EMA: not in the %
    ]
    b = breadth(stocks)
    assert (b.stocks, b.above_ema200, b.pct_above_ema200) == (3, 1, 33.3)
    assert (b.nifty500_stocks, b.nifty500_above_ema200, b.nifty500_pct_above_ema200) == (
        2,
        1,
        50.0,
    )
    assert (b.new_highs, b.new_lows) == (1, 2)
    assert breadth([]).pct_above_ema200 is None


def test_defend_whenever_the_regime_filter_is_on():
    healthy = breadth([_stock(high=130)] * 10)
    mode, reason, mult = mode_for(_regime(risk_off=True, n50_below=True), healthy)
    assert mode == Mode.DEFEND and mult == DEFEND_RISK_MULTIPLIER == 0.5
    assert "Nifty 50 is 5.0% below its 200-day EMA" in reason
    _, reason, _ = mode_for(_regime(risk_off=True, vix_high=True), healthy)
    assert "India VIX 30.0" in reason


def test_attack_needs_breadth_and_more_highs_than_lows():
    six_of_ten = [_stock(str(i), high=130) for i in range(6)] + [
        _stock(str(i), close=90) for i in range(6, 10)
    ]
    mode, reason, mult = mode_for(_regime(), breadth(six_of_ten))
    assert (mode, mult) == (Mode.ATTACK, 1.0)
    assert "60% of stocks" in reason and "6 new highs vs 0 new lows" in reason

    five_of_ten = [_stock(str(i), high=130) for i in range(5)] + [
        _stock(str(i), close=90) for i in range(5, 10)
    ]
    mode, reason, mult = mode_for(_regime(), breadth(five_of_ten))
    assert (mode, mult) == (Mode.NORMAL, 1.0)
    assert "only 50%" in reason

    no_highs = [_stock(str(i)) for i in range(10)]  # all above, no new highs or lows
    mode, reason, _ = mode_for(_regime(), breadth(no_highs))
    assert mode == Mode.NORMAL and "new lows (0) are not fewer than new highs (0)" in reason


def test_normal_without_index_closes_or_universe():
    mode, reason, mult = mode_for(None, breadth([_stock(high=130)]))
    assert (mode, mult) == (Mode.NORMAL, 1.0) and "regime is unknown" in reason
    mode, reason, _ = mode_for(_regime(), breadth([]))
    assert mode == Mode.NORMAL and "universe is empty" in reason


def test_sector_strength_by_median_six_month_return():
    stocks = [
        _stock("A", sector="IT", ret=0.10),
        _stock("B", sector="IT", ret=0.30, close=90),
        _stock("C", sector="IT", ret=-0.05),
        _stock("D", sector="Banks", ret=0.40, n500=False),
        _stock("E", sector="Metals", ret=None),
        _stock("F", sector=None, ret=0.9),
    ]
    rows = sector_strength(stocks)
    assert [r.sector for r in rows] == ["Banks", "IT", "Metals"]
    it = rows[1]
    assert (it.stocks, it.median_return_6m, it.pct_above_ema200) == (3, 0.1, 66.7)
    assert rows[2].median_return_6m is None


def test_market_mood_puts_it_together():
    m = market_mood(DAY, [_stock(high=130)], _regime())
    assert m.mode == Mode.ATTACK and m.day == DAY and m.sectors[0].sector == "IT"
