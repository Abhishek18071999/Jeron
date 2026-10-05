"""The trade plan (decision 0010): the engine's size, the spec section 4 checks and the
portfolio limits after the buy. Pure."""

from dataclasses import replace
from decimal import Decimal

import pytest

import tests.test_backtest_engine as golden
from app.backtest.costs import CostModel
from app.backtest.engine import PortfolioRules, reward_risk, simulate
from app.backtest.strategies import Tier
from app.plan.calc import CHECKLIST_KEYS, PlanInputs, build_plan, missing_checklist
from tests.backtest_helpers import one_stock_market, signal_on

FILL = (100.0, 101.0, 99.0, 100.0)
BASE = PlanInputs(
    ticker="AAA",
    tier=Tier.SWING,
    entry=Decimal("101"),
    stop=Decimal("96"),
    capital=Decimal("1000000"),
    risk_pct=1.0,
    risk_multiplier=1.0,
    mood="normal",
    atr=2.0,
    avg_volume20=1e9,
    median_turnover=2e9,
    sector="IT",
    open_risk=Decimal(0),
    sector_value=Decimal(0),
    sector_cap_pct=Decimal(30),
    results_blackout=False,
    results_line="No results meeting announced in the next 30 days.",
)


def _engine_order(risk_pct: float, risk_off: bool, avg_volume: float):
    m = one_stock_market([golden.SIGNAL, FILL, golden.FLAT], avg_volume=avg_volume)
    m.risk_off[:] = risk_off
    rules = PortfolioRules(cash_rate_pct=0.0, risk_pct=risk_pct)
    result = simulate(m, Tier.SWING, [(0, signal_on(m, 0))], 0, 2, rules, CostModel())
    return result.orders[0]


@pytest.mark.parametrize(
    ("risk_pct", "risk_off", "avg_volume"),
    [
        (1.0, False, 1e9),  # 20% of capital binds: floor(2,00,000 / 101)
        (0.5, False, 1e9),  # risk binds: 5,000 / 5
        (2.0, True, 1e9),  # regime filter halves 2%
        (1.0, False, 50_000),  # 1% of average volume binds
        (0.5, True, 1e9),
    ],
)
def test_size_matches_the_engine(risk_pct, risk_off, avg_volume):
    order = _engine_order(risk_pct, risk_off, avg_volume)
    plan = build_plan(
        replace(
            BASE,
            entry=Decimal(str(order.zone_high)),
            stop=Decimal(str(order.stop)),
            risk_pct=risk_pct,
            risk_multiplier=0.5 if risk_off else 1.0,
            avg_volume20=avg_volume,
        )
    )
    assert plan.shares == order.raw_shares
    assert plan.shares > 0


def test_size_numbers():
    plan = build_plan(BASE)
    assert plan.shares == 1980 and plan.sized_by == "20% of capital"
    assert plan.risk_amount == Decimal("9900.00")  # 5 x 1,980
    assert (plan.target1, plan.target2) == (Decimal("111.00"), Decimal("116.00"))
    assert plan.stop_distance_pct == Decimal("4.95") and plan.stop_atr == Decimal("2.50")
    risk = build_plan(replace(BASE, risk_pct=0.5))
    assert risk.shares == 1000 and risk.sized_by == "risk per trade"
    volume = build_plan(replace(BASE, avg_volume20=50_000))
    assert volume.shares == 500 and volume.sized_by.startswith("1% of 20-day")
    defend = build_plan(replace(BASE, risk_pct=0.5, risk_multiplier=0.5, mood="defend"))
    assert defend.shares == 500
    assert next(c for c in defend.checks if c.key == "mood").status == "warn"
    assert defend.ok


def test_reward_risk_is_the_engines():
    plan = build_plan(BASE)
    expected = reward_risk(CostModel(), 101.0, 5.0, 1980, 0.05, 3.0)
    assert plan.reward_risk_t2 == Decimal(str(expected)).quantize(Decimal("0.01"))
    assert plan.reward_risk_t2 < 3  # costs come off the reward
    assert plan.ok and plan.blockers == []


def _status(plan, key):
    return next(c for c in plan.checks if c.key == key).status


def test_stop_checks():
    tight = build_plan(replace(BASE, stop=Decimal("99.5")))  # 1.5 < 2 = 1 ATR
    assert _status(tight, "stop_min_atr") == "fail" and not tight.ok
    far = build_plan(replace(BASE, stop=Decimal("88")))  # 12.9% away
    assert _status(far, "stop_max_pct") == "fail"
    positional = build_plan(replace(BASE, stop=Decimal("88"), tier=Tier.POSITIONAL))
    assert _status(positional, "stop_max_pct") == "pass" and positional.ok
    above = build_plan(replace(BASE, stop=Decimal("102")))
    assert _status(above, "stop_below_entry") == "fail" and above.shares == 0
    assert "Stop below entry" in above.blockers[0]
    no_atr = build_plan(replace(BASE, atr=None))
    assert _status(no_atr, "stop_min_atr") == "fail"


def test_reward_risk_check_fails_when_costs_eat_the_reward():
    # A 1-rupee stop on a 1,000 rupee stock: costs swamp a 3R target.
    plan = build_plan(
        replace(
            BASE,
            entry=Decimal("1000"),
            stop=Decimal("999"),
            atr=0.5,
            median_turnover=1e6,
            risk_pct=0.5,
        )
    )
    assert _status(plan, "reward_risk") == "fail" and not plan.ok


def test_heat_and_sector_after_the_buy():
    warn = build_plan(replace(BASE, open_risk=Decimal("45000")))  # 4.5% + 0.99%
    assert _status(warn, "heat") == "warn" and warn.ok
    assert warn.heat_after_pct == Decimal("5.49")
    block = build_plan(replace(BASE, open_risk=Decimal("55000")))
    assert _status(block, "heat") == "fail" and not block.ok
    sector = build_plan(replace(BASE, sector_value=Decimal("150000")))  # 15% + 20%
    assert _status(sector, "sector") == "fail" and sector.sector_after_pct == Decimal("35.00")
    unknown = build_plan(replace(BASE, sector=None, sector_value=Decimal("900000")))
    assert _status(unknown, "sector") == "warn" and unknown.ok


def test_results_blackout_blocks():
    plan = build_plan(replace(BASE, results_blackout=True, results_line="Results on Tue"))
    assert _status(plan, "results") == "fail" and not plan.ok
    unknown = build_plan(replace(BASE, results_blackout=None))
    assert _status(unknown, "results") == "warn" and unknown.ok


def test_checklist():
    assert missing_checklist(CHECKLIST_KEYS) == []
    assert missing_checklist(["mood", "stop"]) == [
        "No results within the blackout window",
        "Size is from the plan, not a guess",
        "I will record the fill today",
    ]
