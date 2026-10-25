"""Spec section 5, the risk manager: one test per rule.

| Rule | Test |
|---|---|
| shares = floor(capital x risk% / (entry - stop)) | test_shares_formula |
| capped at 20% of capital per position | test_position_capped_at_20_pct_of_capital |
| <= 1% of 20-day average volume | test_order_at_most_1_pct_of_average_volume |
| risk per trade 0.5-2% (setting, default 1%) | test_risk_setting_limits |
| regime filter halves risk | test_regime_filter_halves_risk |
| max positions 5 swing / 8 positional / 15 investing, configurable | test_max_open_positions_* |
| sector cap <= 30% of capital | test_sector_cap |
| correlation check (3 banks != 3 trades) | test_correlation_check |
| heat: warn at 5% | test_heat_warning_at_5_pct |
| heat: block new entries at 6% | test_heat_blocks_entries_above_6_pct |
| drawdown 10% -> halve risk | test_drawdown_10_pct_halves_risk |
| drawdown 15% -> pause new entries | test_drawdown_15_pct_pauses_entries |
| stop always defined | test_stop_always_defined |
| stop to breakeven at +1R | test_stop_to_breakeven_at_1r |
| book 50% at T1, trail rest by 2 x ATR (closing basis) | test_half_at_t1_then_trail |
| time stop: swing 15 sessions | test_swing_time_stop |
| time stop: positional review at 60 | test_positional_review_at_60 |
| all Indian costs in P&L and R | test_costs_in_pnl_and_r |
| no entry from 3 sessions before results until the day after | test_results_blackout |
| pre-open job (08:30 IST) | M7 (spec milestone list: "Exit engine: pre-open checks") |

The same rules on my real account, in the trade plan before a real buy
(docs/plans/platform-audit-v1.md, slice 3), and the brief's daily/weekly limits:

| Rule | Test |
|---|---|
| real account: drawdown 10% -> halve risk | test_real_drawdown_10_pct_halves_risk |
| real account: drawdown 15% -> no new entries | test_real_drawdown_15_pct_blocks_the_plan |
| real account: max open positions per tier | test_real_max_open_positions_per_tier |
| daily and weekly realised loss limits | test_real_daily_and_weekly_loss_limits |
| at most N new positions a week (overtrading) | test_real_weekly_entries_cap |
| limits warn instead when JERON_RISK_LIMITS_BLOCK is off | test_real_limits_can_warn_instead |
| equity, peak and drawdown from the journal | test_account_state_from_the_journal |

Scenarios use the golden-test conventions: signal close 100, ATR 2, stop 96, entry
zone up to 101.
"""

from datetime import date
from decimal import Decimal

import numpy as np
import pytest
from pydantic import ValidationError

import tests.test_backtest_engine as golden
from app.backtest.engine import PortfolioRules, simulate
from app.backtest.market import Market
from app.backtest.strategies import Tier
from app.config import Settings
from app.paper.job import MAX_CORRELATED, order_notes, portfolio_rules
from app.plan.calc import Limits, PlanInputs, build_plan
from app.portfolio.calc import AccountState, Holding, Sale, account_state
from app.signals.schema import Signal
from tests.backtest_helpers import (
    NO_COSTS,
    market_of,
    one_stock_market,
    signal_on,
    signals_on,
)
from tests.test_signals import valid_payload

SIGNAL = golden.SIGNAL
FILL = (100.0, 101.0, 99.0, 100.0)
FLAT = golden.FLAT
NO_INTEREST = PortfolioRules(cash_rate_pct=0.0)


def _shares(rules: PortfolioRules, **market_kw: float) -> int:
    m = one_stock_market([SIGNAL, FILL, FLAT], **market_kw)
    result = simulate(m, Tier.SWING, [(0, signal_on(m, 0))], 0, 2, rules, NO_COSTS)
    return result.trades[0].raw_shares


def test_shares_formula():
    # 10,00,000 x 1% / (101 - 96) = 2,000 shares when the 20% cap doesn't bind.
    assert _shares(PortfolioRules(cash_rate_pct=0, max_position_pct=100)) == 2000
    rules = PortfolioRules(cash_rate_pct=0, max_position_pct=100, risk_pct=0.5)
    assert _shares(rules) == 1000


def test_position_capped_at_20_pct_of_capital():
    # floor(2,00,000 / 101) = 1,980.
    assert _shares(NO_INTEREST) == 1980


def test_order_at_most_1_pct_of_average_volume():
    assert _shares(NO_INTEREST, avg_volume=50_000) == 500


def test_risk_setting_limits():
    assert Settings().risk_pct == 1.0
    for ok in (0.5, 2.0):
        assert Settings(risk_pct=ok).risk_pct == ok
    for bad in (0.4, 2.1):
        with pytest.raises(ValidationError):
            Settings(risk_pct=bad)
    rules = portfolio_rules(Settings(risk_pct=1.5, capital=500_000), Tier.SWING)
    assert (rules.risk_pct, rules.capital) == (1.5, 500_000)


def test_regime_filter_halves_risk():
    m = one_stock_market([SIGNAL, FILL, FLAT])
    m.risk_off[:] = True
    result = simulate(m, Tier.SWING, [(0, signal_on(m, 0))], 0, 2, NO_INTEREST, NO_COSTS)
    assert result.trades[0].raw_shares == 1000


def _ten_stocks() -> Market:
    return market_of({f"S{i}": [SIGNAL, FILL, FLAT] for i in range(10)})


def test_max_open_positions_per_tier():
    m = _ten_stocks()
    rules = PortfolioRules(cash_rate_pct=0, max_position_pct=5)
    for tier, expected in ((Tier.SWING, 5), (Tier.POSITIONAL, 8)):
        result = simulate(m, tier, [(0, signals_on(m, 0))], 0, 2, rules, NO_COSTS)
        assert len(result.orders) == expected
        assert sum(s.reason == "no free position slot" for s in result.skipped) == 10 - expected


def test_max_open_positions_investing():
    m = market_of({f"S{i:02d}": [SIGNAL, FILL, FLAT] for i in range(18)})
    rules = PortfolioRules(cash_rate_pct=0, max_position_pct=3, heat_block_pct=100)
    result = simulate(m, Tier.INVEST, [(0, signals_on(m, 0, 3.0))], 0, 2, rules, NO_COSTS)
    assert len(result.orders) == 15
    assert portfolio_rules(Settings(max_positions_invest=10), Tier.INVEST).max_positions == 10


def test_max_open_positions_is_configurable():
    m = _ten_stocks()
    assert portfolio_rules(Settings(max_positions_swing=3), Tier.SWING).max_positions == 3
    rules = PortfolioRules(cash_rate_pct=0, max_position_pct=5, max_positions=3)
    result = simulate(m, Tier.SWING, [(0, signals_on(m, 0))], 0, 2, rules, NO_COSTS)
    assert len(result.orders) == 3


def test_sector_cap():
    sectors = {"BANK1": "Financial Services", "BANK2": "Financial Services", "IT1": "IT"}
    m = market_of(
        {s: [SIGNAL, FILL, FLAT] for s in ("BANK1", "BANK2", "IT1", "NOSECTOR")}, sectors=sectors
    )
    # Each position is about 20% of equity: a second bank would make 40% > 30%.
    rules = PortfolioRules(cash_rate_pct=0, sector_cap_pct=30.0)
    result = simulate(m, Tier.SWING, [(0, signals_on(m, 0))], 0, 2, rules, NO_COSTS)
    ordered = sorted(m.symbols[o.s] for o in result.orders)
    assert ordered == ["BANK1", "IT1", "NOSECTOR"]
    assert [s.reason for s in result.skipped] == ["sector Financial Services above 30% of equity"]
    # Off in backtests: all four are ordered.
    plain = simulate(m, Tier.SWING, [(0, signals_on(m, 0))], 0, 2, NO_INTEREST, NO_COSTS)
    assert len(plain.orders) == 4


def test_results_blackout():
    from dataclasses import replace

    from app.backtest.market import results_blackout
    from app.data.events import ResultsDate

    m = one_stock_market([SIGNAL, FILL, FLAT, FLAT, FLAT, FLAT])
    # Results on day 4: fills on days 1-4 are blocked, so signals on days 0-3 are skipped.
    results = {"AAA": [ResultsDate(m.days[4], known_from=None)]}
    m = replace(m, results_blackout=results_blackout(m.days, m.symbols, results))
    on = PortfolioRules(cash_rate_pct=0, results_blackout=True)
    blocked = simulate(m, Tier.SWING, [(0, signal_on(m, 0))], 0, 5, on, NO_COSTS)
    assert blocked.orders == []
    assert [s.reason for s in blocked.skipped] == ["results due: no new entry around results"]
    # Off by default (earlier strategy versions keep their results).
    plain = simulate(m, Tier.SWING, [(0, signal_on(m, 0))], 0, 5, NO_INTEREST, NO_COSTS)
    assert len(plain.orders) == 1
    # A date announced after the signal day doesn't count yet.
    late = {"AAA": [ResultsDate(m.days[4], known_from=m.days[1])]}
    m = replace(m, results_blackout=results_blackout(m.days, m.symbols, late))
    early = simulate(m, Tier.SWING, [(0, signal_on(m, 0))], 0, 5, on, NO_COSTS)
    assert len(early.orders) == 1


def _walk(rng: np.random.Generator, returns: np.ndarray) -> list[tuple[float, float, float, float]]:
    closes = 100 * np.cumprod(1 + returns)
    return [(c, c * 1.005, c * 0.995, c) for c in closes]


def test_correlation_check():
    rng = np.random.default_rng(3)
    n = 130
    common = rng.normal(0, 0.01, n)
    stocks = {
        "BANKA": _walk(rng, common + rng.normal(0, 0.002, n)),
        "BANKB": _walk(rng, common + rng.normal(0, 0.002, n)),
        "BANKC": _walk(rng, common + rng.normal(0, 0.002, n)),
        "PHARMA": _walk(rng, rng.normal(0, 0.01, n)),
    }
    m = market_of(stocks)
    rules = PortfolioRules(cash_rate_pct=0, max_position_pct=10, max_correlated=MAX_CORRELATED)
    day = n - 2
    result = simulate(m, Tier.SWING, [(day, signals_on(m, day))], day, n - 1, rules, NO_COSTS)
    assert sorted(m.symbols[o.s] for o in result.orders) == ["BANKA", "BANKB", "PHARMA"]
    (skip,) = result.skipped
    assert m.symbols[skip.s] == "BANKC"
    assert skip.reason == "moves with BANKA, BANKB (correlation >= 0.7)"


def test_heat_blocks_entries_above_6_pct():
    m = _ten_stocks()
    # 1.9% at risk each: three trades are 5.7% of equity, a fourth would be 7.6%.
    rules = PortfolioRules(cash_rate_pct=0, max_position_pct=100, risk_pct=1.9)
    result = simulate(m, Tier.SWING, [(0, signals_on(m, 0))], 0, 2, rules, NO_COSTS)
    assert len(result.orders) == 3
    assert result.skipped[0].reason == "portfolio heat above 6%"


def test_heat_warning_at_5_pct():
    m = _ten_stocks()
    rules = PortfolioRules(cash_rate_pct=0, max_position_pct=100, risk_pct=1.9)
    result = simulate(
        m,
        Tier.SWING,
        [(0, signals_on(m, 0))],
        0,
        0,
        rules,
        NO_COSTS,
        close_at_end=False,
        orders_on_last_day=True,
    )
    notes = order_notes(m, result, result.pending, rules)
    heat_notes = [
        [n for n in notes[id(o)] if n.startswith("Portfolio heat")] for o in result.pending
    ]
    # 1.9%, 3.8%: no warning; 5.7%: warned.
    assert [len(n) for n in heat_notes] == [0, 0, 1]
    assert "5.7%" in heat_notes[2][0]


def test_drawdown_10_pct_halves_risk():
    rules = PortfolioRules(capital=100_000, cash_rate_pct=0, max_position_pct=100)
    # 200 shares lose 60 each at a gap: equity 88,000, a 12% drawdown. The next trade
    # risks 88,000 x 1% / 2 = 440, so 440 / 5 = 88 shares.
    bars = [SIGNAL, FILL, (40.0, 41.0, 39.0, 40.0), SIGNAL, FILL, FLAT]
    m = one_stock_market(bars)
    result = simulate(m, Tier.SWING, [(0, signal_on(m, 0, 3))], 0, 5, rules, NO_COSTS)
    first, second = result.trades
    assert first.raw_shares == 200
    assert second.raw_shares == 88


def test_drawdown_15_pct_pauses_entries():
    golden.test_drawdown_pause_blocks_new_entries()


def test_stop_always_defined():
    payload = valid_payload()
    del payload["stop"]
    with pytest.raises(ValidationError):
        Signal.model_validate(payload)
    m = one_stock_market([SIGNAL, FILL, FLAT])
    result = simulate(m, Tier.SWING, [(0, signal_on(m, 0))], 0, 2, NO_INTEREST, NO_COSTS)
    assert all(t.stop0 > 0 for t in result.trades)


def test_stop_to_breakeven_at_1r():
    bars = [
        SIGNAL,
        FILL,  # fill 100, stop 96, R = 4
        (101.0, 104.5, 100.5, 104.2),  # close >= 104 (+1R): stop to 100
        (103.0, 103.5, 99.5, 100.0),  # trades through 100: out at breakeven
        FLAT,
    ]
    m = one_stock_market(bars)
    (trade,) = simulate(m, Tier.SWING, [(0, signal_on(m, 0))], 0, 4, NO_INTEREST, NO_COSTS).trades
    assert (trade.exit_day, trade.exit_price, trade.exit_reason) == (3, 100.0, "breakeven stop")
    assert trade.net_pnl == pytest.approx(0.0)


def test_half_at_t1_then_trail():
    golden.test_half_at_target_then_trailing_stop()


def test_swing_time_stop():
    golden.test_time_stop_after_15_sessions_without_1r()


def test_positional_review_at_60():
    bars = [SIGNAL, FILL] + [FLAT] * 62
    m = one_stock_market(bars)
    result = simulate(
        m, Tier.POSITIONAL, [(0, signal_on(m, 0))], 0, len(bars) - 1, NO_INTEREST, NO_COSTS
    )
    (trade,) = result.trades
    # The 60th session after entry is day 61; sold at day 62's open.
    assert (trade.exit_day, trade.exit_reason) == (62, "time stop (60 sessions)")


def test_costs_in_pnl_and_r():
    golden.test_costs_and_slippage_on_a_losing_trade()


# --- The real account, in the trade plan ------------------------------------------------

REAL = dict(
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
TODAY = date(2026, 10, 21)  # a Wednesday


def _account(drawdown="0", today="0", week="0", entries=0, swing=0) -> AccountState:
    return AccountState(
        capital=Decimal("1000000"),
        equity=Decimal("1000000"),
        peak=Decimal("1000000"),
        drawdown_pct=Decimal(drawdown),
        realised_today=Decimal(today),
        realised_week=Decimal(week),
        entries_week=entries,
        open_by_tier={"swing": swing} if swing else {},
        as_of=TODAY,
    )


def _plan(account: AccountState, limits: Limits | None = None, **changes):
    inputs = PlanInputs(**{**REAL, **changes}, account=account, limits=limits or Limits(5))
    return build_plan(inputs)


def _check(plan, key):
    (check,) = [c for c in plan.checks if c.key == key]
    return check


def test_real_drawdown_10_pct_halves_risk():
    # 0.5% risk: 5,000 / 5 = 1,000 shares (the 20% cap is 1,980, so risk binds).
    assert _plan(_account("9.99"), risk_pct=0.5).shares == 1000
    braked = _plan(_account("10"), risk_pct=0.5)
    assert braked.shares == 500
    assert _check(braked, "drawdown").status == "warn"
    assert braked.ok
    # With the mood's halving too: a quarter.
    assert _plan(_account("12"), risk_pct=0.5, risk_multiplier=0.5).shares == 250


def test_real_drawdown_15_pct_blocks_the_plan():
    plan = _plan(_account("15"))
    assert _check(plan, "drawdown").status == "fail"
    assert not plan.ok
    assert _plan(_account("14.99")).ok


def test_real_max_open_positions_per_tier():
    assert _plan(_account(swing=4)).ok
    full = _plan(_account(swing=5))
    assert _check(full, "positions").status == "fail" and not full.ok
    # Five swing trades open don't stop a positional one.
    assert _plan(_account(swing=5), Limits(8), tier=Tier.POSITIONAL, stop=Decimal("92")).ok


def test_real_daily_and_weekly_loss_limits():
    # 2% of 10 lakh = 20,000 a day; 4% = 40,000 a week.
    assert _plan(_account(today="-19999")).ok
    day = _plan(_account(today="-20000", week="-20000"))
    assert _check(day, "daily_loss").status == "fail" and not day.ok
    week = _plan(_account(today="0", week="-40000"))
    assert _check(week, "weekly_loss").status == "fail" and not week.ok
    assert _plan(_account(today="5000", week="-39999")).ok
    off = Limits(5, daily_loss_pct=0, weekly_loss_pct=0)
    assert _plan(_account(today="-90000", week="-90000"), off).ok


def test_real_weekly_entries_cap():
    assert _plan(_account(entries=4)).ok
    capped = _plan(_account(entries=5))
    assert _check(capped, "entries_week").status == "fail" and not capped.ok
    assert _plan(_account(entries=50), Limits(5, max_entries_week=0)).ok


def test_real_limits_can_warn_instead():
    warn = Limits(5, block=False)
    plan = _plan(_account(today="-50000", week="-50000", entries=9), warn)
    assert plan.ok
    assert {_check(plan, k).status for k in ("daily_loss", "weekly_loss", "entries_week")} == {
        "warn"
    }
    # The spec's rules still block.
    assert not _plan(_account("15"), warn).ok
    assert not _plan(_account(swing=5), warn).ok


def _sale(day: date, gain: str) -> Sale:
    return Sale("AAA", day, 10, Decimal(gain), 30)


def _held(close: str, entry: str = "100", shares: int = 100, tier: str = "swing") -> Holding:
    return Holding(
        entry_id=1,
        ticker="BBB",
        strategy_key=None,
        sector=None,
        shares=shares,
        avg_entry=Decimal(entry),
        last_close=Decimal(close),
        last_close_date=TODAY,
        stop=Decimal("90"),
        initial_stop=Decimal("90"),
        pnl=None,
        r_multiple=None,
        first_date=date(2026, 9, 1),
        sessions_held=10,
        action="hold",
        reason="stop",
        tier=tier,
    )


def test_account_state_from_the_journal():
    capital = Decimal("1000000")
    sales = [
        _sale(date(2026, 9, 1), "60000"),  # running 60,000: the peak is 10,60,000
        _sale(date(2026, 10, 5), "-30000"),  # 30,000
        _sale(date(2026, 10, 19), "-50000"),  # Monday: -20,000
        _sale(date(2026, 10, 21), "-25000"),  # today: -45,000
        _sale(date(2026, 10, 22), "-99999"),  # after `as_of`: not counted
    ]
    # Open: 100 shares bought at 100, last close 80: -2,000.
    a = account_state(capital, sales, [date(2026, 10, 19), date(2026, 10, 1)], [_held("80")], TODAY)
    assert a.equity == Decimal("953000.00")  # 10,00,000 - 45,000 - 2,000
    assert a.peak == Decimal("1060000.00")
    # 1 - 9,53,000 / 10,60,000 = 10.094...%
    assert a.drawdown_pct == Decimal("10.09")
    assert a.realised_today == Decimal("-25000.00")
    assert a.realised_week == Decimal("-75000.00")  # Monday and today
    assert a.entries_week == 1
    assert a.open_by_tier == {"swing": 1}
    # At a new high (open profit above the realised peak) the drawdown is 0.
    up = account_state(capital, sales[:1], [], [_held("200")], TODAY)
    assert (up.equity, up.peak, up.drawdown_pct) == (
        Decimal("1070000.00"),
        Decimal("1070000.00"),
        Decimal("0.00"),
    )
    # No trades yet: the capital, no drawdown.
    empty = account_state(capital, [], [], [], TODAY)
    assert (empty.equity, empty.drawdown_pct, empty.entries_week) == (capital, Decimal("0.00"), 0)
