"""The report card's risk profile (app/backtest/stats.py): Sortino, streaks, time under
water, exposure and turnover, against numbers worked by hand."""

import math

import numpy as np
import pytest

from app.backtest.engine import Fill, Trade
from app.backtest.market import Regime
from app.backtest.stats import (
    SESSIONS_PER_YEAR,
    risk_profile,
    sortino,
    streaks,
    underwater,
)


def _trade(day: int, exit_price: float, symbol: str = "A") -> Trade:
    """Bought 10 at 100 with the stop at 95 (R = 50), sold the next session."""
    return Trade(
        s=0,
        symbol=symbol,
        variant="v",
        signal_day=day - 1,
        entry_day=day,
        entry=100.0,
        stop0=95.0,
        t1=110.0,
        shares=10.0,
        raw_shares=10,
        entry_charges=0.0,
        score=0.0,
        regime=Regime.BULL,
        risk_off=False,
        exits=[Fill(day + 1, exit_price, 10.0, 0.0, "target")],
    )


def test_sortino_by_hand():
    # Returns +10%, -10%, +10%: mean 1/30; downside sqrt(0.01 / 3) = 0.057735.
    curve = [100.0, 110.0, 99.0, 108.9]
    expected = (1 / 30) / math.sqrt(0.01 / 3) * math.sqrt(SESSIONS_PER_YEAR)
    assert sortino(curve) == pytest.approx(expected)
    assert sortino(curve) == pytest.approx(9.1652, abs=1e-4)
    # Never below the rate: no downside, reported as 0 rather than infinity.
    assert sortino([100.0, 101.0, 102.0]) == 0.0
    # A higher cash rate counts against every session.
    assert sortino(curve, risk_free_pct=6.5) < sortino(curve)


def test_streaks_in_exit_order():
    # By exit day: win, loss, loss (0R counts as a loss), loss, win, win.
    trades = [
        _trade(9, 110.0),
        _trade(1, 110.0),
        _trade(3, 90.0),
        _trade(5, 100.0),
        _trade(7, 95.0),
        _trade(11, 104.0),
    ]
    assert streaks(trades) == (3, 2)
    assert streaks([]) == (0, 0)


def test_underwater_by_hand():
    # Peaks 100, 120, 120, 120, 130, 130, 130: under water on sessions 2-3 and 5-6.
    w = underwater([100.0, 120.0, 90.0, 100.0, 130.0, 125.0, 126.0])
    assert w.longest_sessions == 2
    # The deepest drop (25%) is from session 1 to 2, back above 120 on session 4.
    assert (w.max_drawdown_sessions, w.recovery_sessions) == (1, 2)
    open_end = underwater([100.0, 80.0, 90.0])
    assert (open_end.longest_sessions, open_end.recovery_sessions) == (2, None)
    flat = underwater([100.0, 100.0, 101.0])
    assert (flat.longest_sessions, flat.max_drawdown_sessions, flat.recovery_sessions) == (0, 0, 0)


def test_risk_profile_exposure_and_turnover():
    # One year of sessions at ₹1,000 equity, half of it in cash.
    curve = np.full(SESSIONS_PER_YEAR + 1, 1000.0)
    cash = np.full(SESSIONS_PER_YEAR + 1, 500.0)
    trades = [_trade(10, 110.0), _trade(20, 90.0, "B")]  # ₹1,000 bought each
    p = risk_profile(curve, cash, trades)
    assert p.exposure_pct == pytest.approx(50.0)
    assert p.trades_per_year == pytest.approx(2.0)
    assert p.turnover == pytest.approx(2.0)  # ₹2,000 bought over ₹1,000 average equity
    assert (p.max_losing_streak, p.max_winning_streak) == (1, 1)
    d = p.to_dict()
    assert set(d) >= {"sortino", "recovery_sessions", "exposure_pct", "turnover"}
    assert risk_profile([], [], []).trades_per_year == 0.0
