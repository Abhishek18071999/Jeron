"""M8 part 2: the single-regime Gate 5 and the cash-sweep line (docs/plans/M8.md)."""

from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from app.backtest.market import Regime, build_market
from app.backtest.stats import GateRules, TradeStats, cash_sweep_curve, gates, trade_stats
from app.backtest.strategies import SINGLE_REGIME_GATE_FROM, STRATEGIES
from app.backtest.walkforward import evaluate
from tests.test_backtest_walkforward import synthetic_inputs


def _stats(trades: int, expectancy: float) -> TradeStats:
    return replace(trade_stats([]), trades=trades, expectancy_r=expectancy)


def _regime_gate(by_regime, rules=None):
    from app.backtest.stats import CurveStats

    curve = CurveStats(1, 1, 0, 0, 0, 0, 0, 1)
    out = gates(_stats(200, 0.3), curve, by_regime, curve, None, rules)
    return next(g for g in out if g.key == "regimes")


def test_default_gate_5_needs_two_of_three_regimes():
    gate = _regime_gate({"bull": _stats(80, 0.5), "bear": _stats(10, -0.2)})
    assert not gate.passed
    gate = _regime_gate(
        {"bull": _stats(80, 0.5), "sideways": _stats(30, 0.1), "bear": _stats(10, -0.2)}
    )
    assert gate.passed


def test_single_regime_gate_5():
    rules = GateRules(single_regime=("bull",))
    assert _regime_gate({"bull": _stats(80, 0.5)}, rules).passed
    # Positive where it trades, flat (no trades) elsewhere: passes.
    assert _regime_gate({"bull": _stats(80, 0.5), "bear": _stats(0, 0.0)}, rules).passed
    # Losing in a regime it was not registered for: fails.
    gate = _regime_gate({"bull": _stats(80, 0.5), "bear": _stats(5, -0.4)}, rules)
    assert not gate.passed and "losing in bear" in gate.value
    # Not positive in its own regime: fails.
    assert not _regime_gate({"bull": _stats(80, -0.1)}, rules).passed


def test_single_regime_is_only_for_new_strategies():
    base = STRATEGIES["breakout-52w"]
    with pytest.raises(ValueError):
        replace(base, single_regime=(Regime.BULL,))
    with pytest.raises(ValueError):
        replace(base, single_regime=(Regime.BULL,), registered_on=date(2026, 10, 1))
    ok = replace(base, single_regime=(Regime.BULL,), registered_on=SINGLE_REGIME_GATE_FROM)
    assert ok.single_regime == (Regime.BULL,)
    # No registered strategy is re-judged: trend-breakout-v1 stays failed.
    assert all(not s.single_regime for s in STRATEGIES.values())


def test_cash_sweep_curve():
    equity = np.array([100.0, 101.0, 102.0])
    cash = np.array([50.0, 50.0, 50.0])
    index = np.array([10.0, 11.0, 11.0])
    interest = np.array([0.0, 1.0, 0.0])
    out = cash_sweep_curve(equity, cash, index, interest)
    # Day 1: 50 of cash earns the index's 10% (5) instead of the 1 of interest.
    assert out[1] == pytest.approx(101 + 5 - 1)
    # Day 2: index flat, nothing more added.
    assert out[2] == pytest.approx(102 + 4)
    # A missing index level counts as no move.
    gap = cash_sweep_curve(equity, cash, np.array([10.0, np.nan, 11.0]), np.zeros(3))
    assert gap[1] == pytest.approx(101) and gap[2] == pytest.approx(102 + 5)


def test_report_has_the_cash_sweep_beside_the_gates():
    m = build_market(synthetic_inputs())
    ev = evaluate(m, STRATEGIES["breakout-52w"])
    sweep = ev.summary["cash_sweep"]
    assert set(sweep) == {"out_of_sample", "holdout", "note"}
    assert all(g["key"] != "cash_sweep" for g in ev.summary["gates"])
    assert len(ev.sim.cash) == len(ev.sim.equity)
    assert all("sweep" in row for row in ev.equity)
