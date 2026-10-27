"""The confidence engine (app/backtest/confidence.py) and its walk-forward re-runs."""

import numpy as np
import pytest

from app.backtest import confidence as c
from app.backtest.costs import CostModel
from app.backtest.strategies import STRATEGIES
from app.backtest.walkforward import evaluate, late, scaled_costs
from tests.backtest_helpers import one_stock_market, signal_on
from tests.test_backtest_walkforward import market as market  # noqa: F401 - the fixture


def test_trade_intervals_bracket_the_estimate_and_are_reproducible():
    rs = [2.0, -1.0] * 50  # expectancy +0.5R
    pnl = [r * 1000 for r in rs]
    a = c.trade_intervals(rs, pnl)
    assert a is not None and a == c.trade_intervals(rs, pnl)
    e = a.expectancy_r
    assert e.estimate == pytest.approx(0.5)
    assert e.low < 0.5 < e.high
    # The standard error of the mean is 1.5 / sqrt(100) = 0.15: about +-0.29 at 95%.
    assert e.low == pytest.approx(0.5 - 1.96 * 0.15, abs=0.06)
    assert a.profit_factor.estimate == pytest.approx(2.0)
    assert a.profit_factor.low < 2.0 < a.profit_factor.high
    assert a.win_rate.estimate == pytest.approx(0.5)
    assert a.positive_share > 0.99
    assert c.trade_intervals([1.0], [1.0]) is None


def test_more_trades_narrow_the_interval():
    rng = np.random.default_rng(1)
    few = list(rng.normal(0.1, 1, 50))
    many = list(rng.normal(0.1, 1, 800))
    a, b = c.trade_intervals(few, few), c.trade_intervals(many, many)
    assert a is not None and b is not None
    width = lambda iv: iv.high - iv.low  # noqa: E731
    assert width(b.expectancy_r) < width(a.expectancy_r) / 2


def test_curve_intervals_and_order_risk():
    rng = np.random.default_rng(2)
    curve = 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, 500))
    iv = c.curve_intervals(curve)
    assert iv is not None
    assert iv.max_drawdown_pct.low <= iv.max_drawdown_pct.high
    assert iv.drawdown_95_pct >= iv.max_drawdown_pct.low
    assert c.curve_intervals(curve[:30]) is None  # shorter than two blocks
    order = c.order_risk([1.0, -1.0] * 30)
    assert order is not None
    assert 1 <= order.losing_streak_median <= order.losing_streak_95
    assert order.drawdown_r_95 >= order.drawdown_r_median > 0
    # All winners: no losing streak, no drawdown.
    sure = c.order_risk([1.0] * 20)
    assert sure is not None and sure.losing_streak_95 == 0 and sure.drawdown_r_95 == 0


def test_concentration_finds_one_trade_one_year_one_sector():
    rs = [20.0] + [-0.1] * 99
    years = ["2020"] + ["2021"] * 99
    sectors = ["IT"] + ["Banks"] * 49 + [None] * 50
    k = c.concentration(rs, years, sectors)
    assert k is not None
    assert k.top_share > 1  # the best trades make more than the whole result
    assert k.without_top_r < 0
    assert k.best_year == "2020" and k.without_best_year_r == pytest.approx(-0.1)
    assert k.best_sector == "IT" and k.best_sector_share == 1.0
    assert k.sectors_known == 0.5


def _intervals(mean: float, n: int = 300) -> c.TradeIntervals:
    rs = [mean + 1, mean - 1] * (n // 2)  # standard deviation 1
    out = c.trade_intervals(rs, rs)
    assert out is not None
    return out


def test_evidence_rating():
    good = c.Scenario("slippage", "slippage x2", 300, 0.4, 1.8)
    grid = [c.GridPoint(f"g{i}", 100, 0.3, i == 0) for i in range(3)]
    conc = c.concentration([0.5] * 300, [str(2018 + i % 5) for i in range(300)], [None] * 300)
    strong = c.evidence(_intervals(0.5), 60, 0.4, 1.6, 0.99, [good], grid, conc)
    assert strong.rating == "strong" and all(ch.passed for ch in strong.checks)

    # Like the RS pullback: positive point estimate, weak holdout, deflated Sharpe 0.39.
    weak = c.evidence(_intervals(0.02), 40, 0.022, 0.96, 0.39, [good], grid, conc)
    assert weak.rating == "weak"
    failed = {ch.key for ch in weak.checks if not ch.passed}
    assert {"expectancy_ci", "holdout", "deflated_sharpe"} <= failed

    moderate = c.evidence(_intervals(0.5), 60, 0.4, 1.6, 0.6, [good], grid, conc)
    assert moderate.rating == "moderate"  # only the deflated Sharpe failed

    few = c.evidence(
        c.trade_intervals([1.0, -1.0] * 10, [1.0, -1.0] * 10), 0, 0, 0, 0, [], [], None
    )
    assert few.rating == "insufficient"
    assert c.evidence(None, 0, 0, 0, 0, [], [], None).rating == "insufficient"


def test_scaled_costs_and_late_entries():
    base = CostModel()
    worse = scaled_costs(base, slippage=2.0, charges=1.5)
    assert worse.slippage_pct(200e7) == pytest.approx(2 * base.slippage_pct(200e7))
    value = 1_000_000.0
    assert worse.charges(value, "buy").total == pytest.approx(
        1.5 * base.charges(value, "buy").total
    )
    m = one_stock_market([(100.0, 101.0, 99.0, 100.0)] * 4)
    v = signal_on(m, 0, 2)
    shifted = late(v)
    assert list(shifted.entries[0]) == [False, True, False, True]
    assert list(v.entries[0]) == [True, False, True, False]


def test_evaluation_reports_confidence_provenance_and_costs(market):  # noqa: F811
    ev = evaluate(market, STRATEGIES["pullback-trend"])
    conf = ev.summary["confidence"]
    assert conf["version"] == c.CONFIDENCE_VERSION
    assert {s["key"] for s in conf["scenarios"]} == {"slippage", "charges", "late"}
    assert len(conf["grid"]) == len(STRATEGIES["pullback-trend"].grid)
    assert sum(g["chosen"] for g in conf["grid"]) == 1
    oos = ev.summary["out_of_sample"]["trades"]
    if oos["trades"] >= 2:
        e = conf["out_of_sample"]["expectancy_r"]
        assert e["low"] <= oos["expectancy_r"] <= e["high"]
    assert conf["evidence"]["rating"] in ("strong", "moderate", "weak", "insufficient")
    # Harder costs never help.
    by_key = {s["key"]: s for s in conf["scenarios"]}
    if oos["trades"]:
        assert by_key["slippage"]["expectancy_r"] <= oos["expectancy_r"] + 1e-9
    p = ev.summary["provenance"]
    assert p["data"] == ev.fingerprint and len(p["code"]) == 16 and p["settings"]
    b = ev.summary["pnl_breakdown"]["out_of_sample"]
    assert b["net_pnl"] == pytest.approx(sum(t.net_pnl for t in ev.oos_trades), abs=0.05)
    assert b["before_slippage"] >= b["gross_pnl"]
    plain = evaluate(market, STRATEGIES["pullback-trend"], robust=False)
    assert plain.summary["confidence"]["scenarios"] == []
    assert plain.summary["out_of_sample"] == ev.summary["out_of_sample"]


def test_the_confidence_block_is_plain_json(market):  # noqa: F811
    import json

    ev = evaluate(market, STRATEGIES["breakout-52w"])
    json.dumps(ev.summary)  # numpy booleans or floats would fail here
