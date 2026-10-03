"""Spec section 5, the risk manager: one test per rule.

| Rule | Test |
|---|---|
| shares = floor(capital x risk% / (entry - stop)) | test_shares_formula |
| capped at 20% of capital per position | test_position_capped_at_20_pct_of_capital |
| <= 1% of 20-day average volume | test_order_at_most_1_pct_of_average_volume |
| risk per trade 0.5-2% (setting, default 1%) | test_risk_setting_limits |
| regime filter halves risk | test_regime_filter_halves_risk |
| max open positions 5 swing / 8 positional, configurable | test_max_open_positions_* |
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
| pre-open job (08:30 IST) | M7 (spec milestone list: "Exit engine: pre-open checks") |

Scenarios use the golden-test conventions: signal close 100, ATR 2, stop 96, entry
zone up to 101.
"""

import numpy as np
import pytest
from pydantic import ValidationError

import tests.test_backtest_engine as golden
from app.backtest.engine import PortfolioRules, simulate
from app.backtest.market import Market
from app.backtest.strategies import Tier
from app.config import Settings
from app.paper.job import MAX_CORRELATED, order_notes, portfolio_rules
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
