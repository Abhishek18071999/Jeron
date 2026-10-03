"""The signal schema (spec section 4) and building a signal from an engine order."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.backtest.engine import PortfolioRules, simulate
from app.backtest.strategies import BREAKOUT_52W, SCORE_SWING, Tier
from app.signals.build import IST, SignalContext, backtest_stats, build_signal, conviction
from app.signals.schema import Signal
from tests.backtest_helpers import NO_COSTS, one_stock_market, signal_on

SIGNAL_BAR = (100.0, 100.5, 99.5, 100.0)
SUMMARY: dict[str, Any] = {
    "periods": {"out_of_sample": ["2019-10-01", "2025-09-30"]},
    "out_of_sample": {
        "trades": {
            "trades": 412,
            "win_rate": 0.41,
            "avg_r": 0.186,
            "expectancy_r": 0.186,
            "profit_factor": 1.25,
        },
        "curve": {"max_drawdown_pct": 18.4},
    },
}


def valid_payload() -> dict[str, Any]:
    return {
        "signal_id": str(uuid4()),
        "created_at": "2026-10-01T19:05:00+05:30",
        "data_as_of": "2026-10-01T15:30:00+05:30",
        "ticker": "AAA",
        "setup_name": "Test setup",
        "strategy_version": "test-v1",
        "tier": "swing",
        "direction": "long",
        "why": ["one", "two", "three"],
        "entry_zone": {"low": "100", "high": "101", "valid_until": "2026-10-03"},
        "stop": {"price": "96", "type": "ATR", "reason": "2 x ATR"},
        "targets": {"t1": "108", "t2": "112", "basis": "+2R, +3R"},
        "risk_reward_t1": "2",
        "risk_reward_t2": "3",
        "expected_holding": {"min_days": 3, "max_days": 15},
        "shares": 1980,
        "capital_at_risk": "9900",
        "exit_plan": "book 50% at T1",
        "time_stop_days": 15,
        "invalidation": "opens below the stop",
        "event_risk": "not checked",
        "conviction": 5,
        "brains_breakdown": {
            "technical": "90",
            "fundamental": None,
            "news": None,
            "combined": "90",
        },
        "backtest_stats": backtest_stats(SUMMARY).model_dump(mode="json"),
        "research_only": True,
        "notes": [],
    }


def test_valid_payload_passes():
    signal = Signal.model_validate(valid_payload())
    assert signal.shares == 1980


@pytest.mark.parametrize(
    "field",
    ["ticker", "why", "entry_zone", "stop", "targets", "invalidation", "backtest_stats", "notes"],
)
def test_every_field_is_required(field):
    payload = valid_payload()
    del payload[field]
    with pytest.raises(ValidationError):
        Signal.model_validate(payload)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"why": ["one", "two"]}, "at least 3"),
        ({"why": ["1", "2", "3", "4", "5", "6"]}, "at most 5"),
        ({"risk_reward_t2": "1.9"}, "reward:risk to T2 below 2"),
        ({"stop": {"price": "87", "type": "ATR", "reason": "x"}}, "more than 12%"),
        ({"stop": {"price": "100", "type": "ATR", "reason": "x"}}, "stop < entry zone low"),
        ({"targets": {"t1": "100.5", "t2": "112", "basis": "x"}}, "entry zone high < T1"),
        ({"conviction": 6}, "less than or equal to 5"),
        ({"direction": "short"}, "'long'"),
        ({"shares": 0}, "greater than or equal to 1"),
        ({"surprise": 1}, "Extra inputs"),
    ],
)
def test_bad_signals_are_rejected(change, message):
    with pytest.raises(ValidationError, match=message):
        Signal.model_validate(valid_payload() | change)


def test_positional_stop_may_be_wider():
    payload = valid_payload() | {
        "tier": "positional",
        "stop": {"price": "85", "type": "ATR", "reason": "x"},
    }
    assert Signal.model_validate(payload).stop.price == Decimal(85)


def test_conviction_from_score():
    assert [conviction(s) for s in (45, 60, 79.9, 80, 95)] == [1, 2, 3, 4, 5]


def test_backtest_stats_from_a_run_summary():
    stats = backtest_stats(SUMMARY)
    assert stats.trades == 412
    assert stats.expectancy_R == Decimal("0.1860")
    assert stats.max_drawdown_pct == Decimal("18.40")
    assert stats.period.startswith("2019-10-01 to 2025-09-30")


def _order(rules: PortfolioRules | None = None):
    m = one_stock_market([SIGNAL_BAR])
    result = simulate(
        m,
        Tier.SWING,
        [(0, signal_on(m, 0))],
        0,
        0,
        rules or PortfolioRules(cash_rate_pct=0),
        NO_COSTS,
        close_at_end=False,
        orders_on_last_day=True,
    )
    (order,) = result.pending
    return m, order


def _context(strategy=SCORE_SWING, params=None, research_only=True) -> SignalContext:
    return SignalContext(
        strategy=strategy,
        params=params or {"min_score": 80.0, "stop_atr": 2.0},
        rules=PortfolioRules(cash_rate_pct=0),
        costs=NO_COSTS,
        backtest=backtest_stats(SUMMARY),
        research_only=research_only,
        created_at=datetime(2024, 1, 1, 19, 5, tzinfo=IST),
        next_session=date(2024, 1, 2),
        notes=["a note"],
    )


def test_signal_from_an_order():
    m, order = _order()
    signal = build_signal(m, order, _context())
    assert signal.ticker == "AAA"
    assert signal.tier == "swing" and signal.direction == "long"
    assert signal.strategy_version == "score-swing-v1 (min_score=80, stop_atr=2)"
    assert signal.data_as_of == datetime(2024, 1, 1, 15, 30, tzinfo=IST)
    assert (signal.entry_zone.low, signal.entry_zone.high) == (Decimal(100), Decimal(101))
    assert signal.entry_zone.valid_until == date(2024, 1, 2)
    assert signal.stop.price == Decimal(96) and signal.stop.type == "ATR"
    assert (signal.targets.t1, signal.targets.t2) == (Decimal(108), Decimal(112))
    # Without costs: +2R and +3R exactly.
    assert (signal.risk_reward_t1, signal.risk_reward_t2) == (Decimal(2), Decimal(3))
    # The engine sized it: 1,980 shares, risking (101 - 96) x 1,980 at the top of the zone.
    assert signal.shares == 1980 and signal.capital_at_risk == Decimal(9900)
    assert signal.time_stop_days == 15
    assert (signal.expected_holding.min_days, signal.expected_holding.max_days) == (3, 15)
    assert signal.conviction == 5
    assert signal.brains_breakdown.technical == Decimal("90.0")
    assert signal.brains_breakdown.fundamental is None
    assert 3 <= len(signal.why) <= 5
    assert signal.why[0].startswith("Technical score rose to 90.0")
    assert signal.research_only and signal.notes == ["a note"]
    assert Signal.model_validate(signal.model_dump(mode="json")) == signal


def test_costs_lower_reward_risk():
    m, order = _order()
    ctx = _context()
    from app.backtest.costs import CostModel

    signal = build_signal(m, order, SignalContext(**(ctx.__dict__ | {"costs": CostModel()})))
    assert signal.risk_reward_t1 < 2 and signal.risk_reward_t2 < 3


def test_breakout_reasons():
    m, order = _order()
    m.prior_high_52w[:] = 98.0
    m.volume_ratio[:] = 2.3
    m.ema200[:] = 90.0
    signal = build_signal(
        m, order, _context(BREAKOUT_52W, {"volume_x": 1.5, "stop_atr": 2.0}, research_only=False)
    )
    assert signal.tier == "positional" and signal.time_stop_days == 60
    assert signal.why[:3] == [
        "Closed at ₹100.00, above the previous 52-week high of ₹98.00",
        "Volume 2.3x its 20-day average (needs 1.5x)",
        "Above its 200-day EMA (₹90.00): long-term uptrend",
    ]
    assert not signal.research_only


def test_next_session_without_the_years_holidays():
    from app.calendar.nse import CalendarEntry, TradingCalendar
    from app.paper.job import next_session

    calendar = TradingCalendar([CalendarEntry(date(2025, 1, 26), "holiday", "Republic Day", True)])
    assert next_session(calendar, date(2025, 1, 24)) == (date(2025, 1, 27), None)
    day, note = next_session(calendar, date(2026, 10, 1))
    assert day == date(2026, 10, 2)
    assert note is not None and "2026 holiday list" in note
