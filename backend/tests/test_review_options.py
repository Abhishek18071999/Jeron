"""The 2026-10 trading review's research options (docs/plans/review-v1.md): all off by
default, so the golden trades don't move; each does what it says when on."""

from dataclasses import replace

import numpy as np
import pytest

from app.backtest.engine import PortfolioRules, Skip, simulate
from app.backtest.market import crash_guard_days
from app.backtest.missed import missed_entries, missed_r
from app.backtest.strategies import Tier
from tests.backtest_helpers import NO_COSTS, one_stock_market, signal_on

SIGNAL = (100.0, 100.5, 99.5, 100.0)
FLAT = (101.0, 101.5, 99.5, 101.0)
RULES = PortfolioRules(cash_rate_pct=0.0)


def _run(bars, rules=RULES, tier=Tier.SWING, results_on=None):
    m = one_stock_market(bars)
    if results_on is not None:
        m.results_session = np.zeros_like(m.universe)
        m.results_session[0, results_on] = True
    return simulate(m, tier, [(0, signal_on(m, 0))], 0, len(bars) - 1, rules, NO_COSTS)


def test_defaults_are_off():
    r = PortfolioRules()
    assert r.results_exit is None and not r.crash_guard and r.time_stop


def test_sell_before_results_at_the_meeting_session_open():
    bars = [SIGNAL, FLAT, FLAT, FLAT, (90.0, 91.0, 89.0, 90.0), FLAT]
    held = _run(bars, results_on=4)
    (trade,) = held.trades
    assert trade.exit_reason == "stop" and trade.exit_day == 4  # gapped through the stop
    (sold,) = _run(bars, replace(RULES, results_exit="sell"), results_on=4).trades
    assert (sold.exit_day, sold.exit_price, sold.exit_reason) == (4, 90.0, "before results")
    # Decided at day 3's close, sold at day 4's open: in this made-up market the gap is
    # at the open, so selling there doesn't help. A gap at day 5 shows the point.
    bars = [SIGNAL, FLAT, FLAT, FLAT, FLAT, (90.0, 91.0, 89.0, 90.0)]
    (sold,) = _run(bars, replace(RULES, results_exit="sell"), results_on=4).trades
    assert (sold.exit_day, sold.exit_price) == (4, 101.0)


def test_halve_before_results():
    bars = [SIGNAL, FLAT, FLAT, FLAT, FLAT, FLAT]
    (trade,) = _run(bars, replace(RULES, results_exit="half"), results_on=4).trades
    assert [f.reason for f in trade.exits][0] == "before results, half"
    assert trade.exits[0].shares == pytest.approx(trade.shares / 2, abs=1)


def test_time_stop_off_keeps_the_position():
    bars = [SIGNAL, (100.0, 101.0, 99.0, 100.0)] + [FLAT] * 16
    (trade,) = _run(bars).trades
    assert trade.exit_reason.startswith("time stop")
    (kept,) = _run(bars, replace(RULES, time_stop=False)).trades
    assert kept.open_at_end


def test_crash_guard_days():
    # 260 sessions falling below the 200-day EMA, then a 10% rebound in 20 sessions.
    falling = np.linspace(200, 100, 260)
    rebound = np.linspace(100, 112, 21)[1:]
    guard = crash_guard_days(np.concatenate([falling, rebound]))
    assert not guard[:260].any()
    assert guard[-1]
    # A steady bull market never trips it.
    assert not crash_guard_days(np.linspace(100, 300, 400)).any()


def test_crash_guard_blocks_new_entries():
    m = one_stock_market([SIGNAL, FLAT, FLAT])
    guarded = replace(RULES, crash_guard=True)
    result = simulate(m, Tier.SWING, [(0, signal_on(m, 0))], 0, 2, guarded, NO_COSTS)
    assert result.trades  # too little index history to know: no guard
    m2 = one_stock_market([SIGNAL] * 282)
    m2.nifty500 = np.concatenate([np.linspace(200, 100, 260), np.linspace(100, 112, 22)[1:]])
    result = simulate(m2, Tier.SWING, [(0, signal_on(m2, 280))], 0, 281, guarded, NO_COSTS)
    assert [s.reason for s in result.skipped] == ["momentum-crash guard"]


def test_missed_entry_outcome():
    # Opened at 103 (above the 101 zone), then ran to T1 (+2R) and fell back to the
    # breakeven stop: half at +2R, half at 0R = +1R.
    bars = [SIGNAL, (103.0, 104.0, 102.0, 103.0), (104.0, 117.0, 103.5, 116.0)]
    bars += [(116.0, 116.5, 102.0, 102.5)]
    m = one_stock_market(bars)
    result = simulate(m, Tier.SWING, [(0, signal_on(m, 0))], 0, 3, RULES, NO_COSTS)
    (skip,) = result.skipped
    assert skip.reason == "opened above the entry zone" and skip.stop == 96.0
    assert missed_r(m, Tier.SWING, RULES, NO_COSTS, skip, 3) == pytest.approx(1.0)
    summary = missed_entries(m, Tier.SWING, RULES, NO_COSTS, result.skipped, [], 0, 3)
    assert (summary.missed, summary.missed_avg_r, summary.missed_win_rate) == (1, 1.0, 1.0)
    assert summary.filled == 0 and summary.filled_avg_r is None
    assert missed_r(m, Tier.SWING, RULES, NO_COSTS, Skip(0, 1, "x"), 3) is None  # no stop


def test_effective_trials():
    from app.backtest.stats import deflated_sharpe, effective_trials

    rng = np.random.default_rng(1)
    independent = rng.normal(size=(10, 500))
    assert effective_trials(independent) == pytest.approx(10, rel=0.2)
    same = np.tile(rng.normal(size=500), (10, 1))
    assert effective_trials(same) == pytest.approx(1.0)
    # Fewer effective trials, a lower bar: the deflated Sharpe can only go up.
    returns = rng.normal(0.001, 0.01, 500)
    sharpes = list(rng.normal(0.02, 0.02, 60))
    assert deflated_sharpe(returns, sharpes, 5.0) >= deflated_sharpe(returns, sharpes)
