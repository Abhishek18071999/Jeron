"""Golden tests for the backtest engine: known bars -> known trades -> known P&L.

Every scenario starts from a signal on day 0: close 100, ATR 2, stop 2 x ATR = 96,
entry zone up to 101. Capital ₹10,00,000 at 1% risk sizes 10,000 / (101 - 96) = 2,000
shares, capped at 20% of capital: floor(2,00,000 / 101) = 1,980 shares. Idle cash
earns nothing in these scenarios unless a test says otherwise.
"""

from datetime import date

import pytest

from app.backtest.costs import CostModel
from app.backtest.engine import PortfolioRules, simulate
from app.backtest.strategies import Tier
from tests.backtest_helpers import NO_COSTS, one_stock_market, signal_on, weekdays

SIGNAL = (100.0, 100.5, 99.5, 100.0)
FLAT = (101.0, 101.5, 99.5, 101.0)
NO_INTEREST = PortfolioRules(cash_rate_pct=0.0)


def run(bars, costs=NO_COSTS, tier=Tier.SWING, rules=NO_INTEREST, **market_kw):
    m = one_stock_market(bars, **market_kw)
    return simulate(m, tier, [(0, signal_on(m, 0))], 0, len(bars) - 1, rules, costs)


def test_half_at_target_then_trailing_stop():
    bars = [
        SIGNAL,
        (100.0, 101.0, 99.0, 100.5),  # fill at the open, 100; stop 96, T1 = 100 + 2 x 4 = 108
        (101.0, 104.5, 100.5, 104.2),  # close >= 104 (+1R): stop to breakeven
        (104.0, 109.0, 103.5, 108.5),  # T1: sell 990 at 108; trail 108.5 - 4 = 104.5
        (109.0, 112.0, 108.0, 111.0),  # trail 111 - 4 = 107
        (110.0, 110.5, 106.5, 106.8),  # close below 107: sell the rest next open
        (106.0, 107.0, 105.0, 106.0),  # sell 990 at 106
        (106.0, 107.0, 105.0, 106.0),
    ]
    result = run(bars)
    (trade,) = result.trades
    assert trade.entry == 100.0 and trade.stop0 == 96.0 and trade.t1 == 108.0
    assert trade.raw_shares == 1980
    assert [(f.day, f.price, f.shares) for f in trade.exits] == [(3, 108.0, 990), (6, 106.0, 990)]
    assert trade.exit_reason.startswith("trailing stop")
    assert trade.net_pnl == pytest.approx(990 * 8 + 990 * 6)  # 13,860
    assert trade.r_multiple == pytest.approx(13_860 / (4 * 1980))  # 1.75R
    assert result.equity[-1] == pytest.approx(1_013_860)


def test_gap_below_stop_sells_at_the_open():
    bars = [SIGNAL, (100.0, 101.0, 99.0, 100.0), (95.0, 96.0, 94.0, 95.5), FLAT]
    (trade,) = run(bars).trades
    assert (trade.exit_day, trade.exit_price, trade.exit_reason) == (2, 95.0, "stop")
    assert trade.net_pnl == pytest.approx(-5 * 1980)
    assert trade.r_multiple == pytest.approx(-1.25)


def test_stop_inside_the_day_sells_at_the_stop():
    bars = [SIGNAL, (100.0, 101.0, 99.0, 100.0), (99.0, 99.5, 95.0, 97.0), FLAT]
    (trade,) = run(bars).trades
    assert (trade.exit_day, trade.exit_price) == (2, 96.0)
    assert trade.r_multiple == pytest.approx(-1.0)


def test_lower_circuit_stop_fills_at_next_open():
    bars = [
        SIGNAL,
        (100.0, 101.0, 99.0, 100.0),
        (95.0, 95.0, 95.0, 95.0),  # locked at the 5% lower band all day: no fill
        (93.0, 94.0, 92.0, 93.5),  # sold at the open
        FLAT,
    ]
    (trade,) = run(bars, band_pct=5.0).trades
    assert (trade.exit_day, trade.exit_price) == (3, 93.0)
    assert "lower circuit" in trade.exit_reason
    assert trade.r_multiple == pytest.approx(-7 * 1980 / (4 * 1980))


def test_time_stop_after_15_sessions_without_1r():
    bars = [SIGNAL, (100.0, 101.0, 99.0, 100.0)] + [FLAT] * 16
    (trade,) = run(bars).trades
    # Sessions after entry: day 2 is the 1st, day 16 the 15th; sold at day 17's open.
    assert (trade.exit_day, trade.exit_price) == (17, 101.0)
    assert trade.exit_reason.startswith("time stop")
    assert trade.net_pnl == pytest.approx(1980)


def test_positional_time_stop_is_longer():
    bars = [SIGNAL, (100.0, 101.0, 99.0, 100.0)] + [FLAT] * 20
    (trade,) = run(bars, tier=Tier.POSITIONAL).trades
    assert trade.open_at_end


def test_open_above_zone_buys_at_the_zone_if_touched():
    bars = [SIGNAL, (103.0, 104.0, 100.8, 102.0), FLAT, FLAT]
    (trade,) = run(bars).trades
    assert trade.entry == 101.0


def test_runaway_open_and_open_below_stop_are_skipped():
    result = run([SIGNAL, (103.0, 104.0, 101.5, 103.0), FLAT])
    assert result.trades == []
    assert [s.reason for s in result.skipped] == ["ran above the entry zone"]
    result = run([SIGNAL, (95.5, 97.0, 95.0, 96.0), FLAT])
    assert result.trades == []
    assert [s.reason for s in result.skipped] == ["opened below the stop"]


def test_upper_circuit_lock_blocks_the_buy():
    result = run([SIGNAL, (105.0, 105.0, 105.0, 105.0), FLAT], band_pct=5.0)
    assert result.trades == []
    assert [s.reason for s in result.skipped] == ["locked at the upper circuit"]


def test_volume_cap_and_risk_halving():
    bars = [SIGNAL, (100.0, 101.0, 99.0, 100.0), FLAT]
    # 1% of 50,000 average volume = 500 shares.
    (trade,) = run(bars, avg_volume=50_000).trades
    assert trade.raw_shares == 500
    m = one_stock_market(bars)
    m.risk_off[:] = True  # regime filter: half risk -> 5,000 / 5 = 1,000 shares
    result = simulate(m, Tier.SWING, [(0, signal_on(m, 0))], 0, 2, None, NO_COSTS)
    assert result.trades[0].raw_shares == 1000


def test_stop_too_wide_is_rejected():
    bars = [(10.0, 10.5, 9.5, 10.0), FLAT]
    # ATR 2 on a ₹10 stock: a 2 x ATR stop is 40% away, above the 12% swing limit.
    result = run(bars)
    assert result.skipped[0].reason == "stop more than 12% away"


def test_costs_and_slippage_on_a_losing_trade():
    """Default Zerodha costs, 0.05% slippage (median turnover ₹200 crore)."""
    bars = [SIGNAL, (100.0, 101.0, 99.0, 100.0), (95.0, 96.0, 94.0, 95.5), FLAT]
    (trade,) = run(bars, costs=CostModel()).trades
    shares = 1980
    buy = 100.0 * 1.0005  # 100.05
    sell = 95.0 * 0.9995  # 94.9525
    buy_value, sell_value = buy * shares, sell * shares
    buy_charges = (
        buy_value * 0.001  # STT
        + buy_value * 0.0000297  # exchange
        + buy_value * 0.000001  # SEBI
        + buy_value * 0.00015  # stamp duty
        + 0.18 * (buy_value * 0.0000297 + buy_value * 0.000001)  # GST
    )
    sell_charges = (
        sell_value * 0.001
        + sell_value * 0.0000297
        + sell_value * 0.000001
        + 0.18 * (sell_value * 0.0000297 + sell_value * 0.000001)
        + 15.34  # DP charge
    )
    assert trade.entry == pytest.approx(buy)
    assert trade.charges == pytest.approx(buy_charges + sell_charges)
    expected = (sell - buy) * shares - buy_charges - sell_charges
    assert trade.net_pnl == pytest.approx(expected)
    assert trade.r_multiple == pytest.approx(expected / ((buy - 96.0) * shares))


def test_drawdown_pause_blocks_new_entries():
    rules = PortfolioRules(capital=100_000, risk_pct=20.0, max_position_pct=100.0)
    # Big loss on the first trade (-25% of equity), then a fresh signal is ignored.
    bars = [SIGNAL, (100.0, 101.0, 99.0, 100.0), (80.0, 81.0, 79.0, 80.0), SIGNAL, FLAT, FLAT]
    m = one_stock_market(bars)
    result = simulate(m, Tier.SWING, [(0, signal_on(m, 0, 3))], 0, 5, rules, NO_COSTS)
    assert len(result.trades) == 1
    assert result.brake_events and "paused" in result.brake_events[0][1]


def test_dividend_is_paid_even_when_the_ex_date_gap_hits_the_stop():
    """A huge special dividend: the price falls by the dividend on the ex-date and
    the stop sells at the open, but the dividend is still paid."""
    bars = [SIGNAL, (100.0, 101.0, 99.0, 100.0), (40.0, 41.0, 39.0, 40.0), FLAT]
    m = one_stock_market(bars)
    m.dividend[0, 2] = 60.0
    result = simulate(m, Tier.SWING, [(0, signal_on(m, 0))], 0, 3, None, NO_COSTS)
    (trade,) = result.trades
    assert (trade.exit_day, trade.exit_price) == (2, 40.0)
    assert trade.dividends == pytest.approx(60.0 * 1980)
    assert trade.net_pnl == pytest.approx((40 - 100) * 1980 + 60 * 1980)


def test_idle_cash_earns_the_liquid_fund_rate_per_calendar_day():
    bars = [FLAT] * 10
    m = one_stock_market(bars)
    result = simulate(m, Tier.SWING, [], 0, len(bars) - 1, None, NO_COSTS)
    # Ten weekdays from Monday 1 January 2024: 11 calendar days, one weekend.
    assert m.days == weekdays(date(2024, 1, 1), 10)
    elapsed = (m.days[-1] - m.days[0]).days
    assert elapsed == 11
    assert result.equity[-1] == pytest.approx(1_000_000 * 1.065 ** (elapsed / 365))
    assert sum(a for _, a in result.interest) == pytest.approx(result.equity[-1] - 1_000_000)
    # Over a Friday-to-Monday gap, three days' interest.
    friday_to_monday = result.equity[5] / result.equity[4]
    assert friday_to_monday == pytest.approx(1.065 ** (3 / 365))
