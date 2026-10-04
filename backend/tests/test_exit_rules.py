"""Exit rules for real positions (spec section 5), checked on hand-built bars and
against the engine on the same trades."""

import math
from datetime import date

import pytest

from app.backtest.engine import PortfolioRules, simulate
from app.backtest.strategies import Tier
from app.exits.rules import Action, ExitBar, exit_plan
from tests.backtest_helpers import NO_COSTS, one_stock_market, signal_on, weekdays

SIGNAL = (100.0, 100.5, 99.5, 100.0)
FLAT = (101.0, 101.5, 99.5, 101.0)


def bars(rows, atr=2.0):
    days = weekdays(date(2024, 1, 2), len(rows))
    return [ExitBar(d, *row, atr) for d, row in zip(days, rows, strict=True)]


def test_breakeven_then_half_at_t1_then_trail():
    # Entry 100, stop 96 (R = 4): +1R close 104, T1 108.
    rows = [(100.0, 101.0, 99.0, 100.5), (101.0, 104.5, 100.5, 104.2)]
    plan = exit_plan(100.0, 96.0, Tier.SWING, bars(rows), half_booked=False)
    assert plan.action == Action.HOLD and plan.stop == 100.0 and plan.reached_1r
    assert plan.t1 == 108.0 and plan.trail is None

    rows.append((104.0, 109.0, 103.5, 108.5))
    plan = exit_plan(100.0, 96.0, Tier.SWING, bars(rows), half_booked=False)
    assert plan.action == Action.SELL_HALF and plan.t1_hit is not None
    assert plan.trail == pytest.approx(104.5)

    rows.append((109.0, 112.0, 108.0, 111.0))
    plan = exit_plan(100.0, 96.0, Tier.SWING, bars(rows), half_booked=True)
    assert plan.action == Action.HOLD and plan.trail == pytest.approx(107.0)
    assert "107.00" in plan.reason

    rows.append((110.0, 110.5, 106.5, 106.8))  # close below the trail
    plan = exit_plan(100.0, 96.0, Tier.SWING, bars(rows), half_booked=True)
    assert plan.action == Action.SELL_ALL and "trail" in plan.reason


def test_trail_only_moves_up():
    rows = [(100.0, 101.0, 99.0, 100.5), (104.0, 109.0, 103.5, 108.5), (109, 112, 108, 111.0)]
    rows.append((110.0, 110.5, 108.0, 109.0))  # lower close, trail stays at 107
    plan = exit_plan(100.0, 96.0, Tier.SWING, bars(rows), half_booked=True)
    assert plan.trail == pytest.approx(107.0) and plan.action == Action.HOLD


def test_stop_hit_says_sell_even_if_still_held():
    rows = [(100.0, 101.0, 99.0, 100.0), (99.0, 99.5, 95.0, 97.0), (97.0, 98.0, 96.5, 97.5)]
    plan = exit_plan(100.0, 96.0, Tier.SWING, bars(rows), half_booked=False)
    assert plan.action == Action.SELL_ALL and plan.exit_day == bars(rows)[1].day
    assert "stop ₹96.00 hit" in plan.reason and "still held" in plan.reason


def test_breakeven_stop_is_named():
    rows = [(100.0, 101.0, 99.0, 100.0), (101.0, 104.5, 100.5, 104.2), (103, 103, 99.5, 100.2)]
    plan = exit_plan(100.0, 96.0, Tier.SWING, bars(rows), half_booked=False)
    assert plan.action == Action.SELL_ALL and plan.reason.startswith("breakeven stop")


def test_time_stops_by_tier():
    rows = [(100.0, 101.0, 99.0, 100.0)] + [FLAT] * 14
    plan = exit_plan(100.0, 96.0, Tier.SWING, bars(rows), half_booked=False)
    assert plan.action == Action.HOLD and plan.sessions == 14
    assert "14 of 15 sessions" in plan.notes[0] and "within 1 more" in plan.notes[0]
    plan = exit_plan(100.0, 96.0, Tier.SWING, bars(rows + [FLAT]), half_booked=False)
    assert plan.action == Action.SELL_ALL and plan.reason.startswith("time stop")
    plan = exit_plan(100.0, 96.0, Tier.POSITIONAL, bars(rows + [FLAT] * 20), half_booked=False)
    assert plan.action == Action.HOLD and plan.time_stop_sessions == 60


def test_no_atr_no_trail():
    rows = [(100.0, 101.0, 99.0, 100.5), (104.0, 109.0, 103.5, 108.5)]
    plan = exit_plan(100.0, 96.0, Tier.SWING, bars(rows, atr=math.nan), half_booked=True)
    assert plan.trail is None and plan.action == Action.HOLD


def test_bad_inputs():
    with pytest.raises(ValueError):
        exit_plan(100.0, 101.0, Tier.SWING, bars([FLAT]), half_booked=False)
    with pytest.raises(ValueError):
        exit_plan(100.0, 96.0, Tier.SWING, [], half_booked=False)


@pytest.mark.parametrize(
    "rows",
    [
        [(100.0, 101.0, 99.0, 100.5), (101, 104.5, 100.5, 104.2), (104, 109, 103.5, 108.5),
         (109.0, 112.0, 108.0, 111.0), (110.0, 110.5, 106.5, 106.8), FLAT],
        [(100.0, 101.0, 99.0, 100.0), (99.0, 99.5, 95.0, 97.0), FLAT],
        [(100.0, 101.0, 99.0, 100.0)] + [FLAT] * 16,
        [(100.0, 101.0, 99.0, 100.0), (101, 104.5, 100.5, 104.2), (103, 103, 99.5, 100.2), FLAT],
    ],
)  # fmt: skip
def test_matches_the_engine(rows):
    """The engine fills at day 1's open (100) with stop 96; the exit plan on the same
    bars must call for an exit on the day the engine decided it."""
    m = one_stock_market([SIGNAL, *rows])
    rules = PortfolioRules(cash_rate_pct=0.0)
    result = simulate(m, Tier.SWING, [(0, signal_on(m, 0))], 0, len(rows), rules, NO_COSTS)
    (trade,) = result.trades
    assert trade.entry == 100.0 and trade.stop0 == 96.0
    exit_bars = [
        ExitBar(m.days[t], m.open[0, t], m.high[0, t], m.low[0, t], m.close[0, t], 2.0)
        for t in range(1, len(rows) + 1)
    ]
    plan = exit_plan(100.0, 96.0, Tier.SWING, exit_bars, half_booked=False)
    assert plan.exit_day is not None
    final = trade.exits[-1]
    decided = final.day if final.reason.startswith(("stop", "breakeven")) else final.day - 1
    assert plan.exit_day == m.days[decided]
    assert (plan.t1_hit is not None) == any("T1" in f.reason for f in trade.exits)
