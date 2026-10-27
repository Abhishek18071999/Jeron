"""The paper review (docs/plans/paper-review-v1.md): the 90+ strategy, signal context
and its groups, the proposal rule, the validation rule and the review's numbers."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import numpy as np
import pytest

from app.backtest.market import Regime, build_market
from app.backtest.strategies import STRATEGIES, TOP_SCORE, TOP_SCORE_MIN
from app.models import StrategyProposal
from app.paper import proposals as pr
from app.paper.optimize import filtered_strategy
from app.paper.proposals import (
    DIMENSIONS,
    ClosedTrade,
    Result,
    band,
    candidates,
    forward_split,
    group_mask,
    group_of,
    judge,
    signal_context,
)
from app.paper.review import TradeRow, journal, observations, plan_evaluation, review
from tests.backtest_helpers import market_of
from tests.test_backtest_walkforward import synthetic_inputs


@pytest.fixture(scope="module")
def market():
    m = build_market(synthetic_inputs(n_days=700, n_stocks=12, seed=9))
    m.sectors = ["Banks" if i % 3 == 0 else ("IT" if i % 3 == 1 else None) for i in range(12)]
    return m


# --- top-score-v1 ------------------------------------------------------------------------


def test_top_score_is_a_new_version_with_one_grid_point():
    assert STRATEGIES["top-score"] is TOP_SCORE
    assert TOP_SCORE.version == "top-score-v1"
    assert TOP_SCORE.grid == [{"min_score": 90.0, "stop_atr": 2.0}]
    assert TOP_SCORE.results_blackout and TOP_SCORE.min_news_score == 40.0
    assert "90" in TOP_SCORE.rules(TOP_SCORE.default)[0]


def test_top_score_enters_when_the_score_crosses_90():
    bars = [(100.0, 101.0, 99.0, 100.0)] * 6
    m = market_of({"A": bars, "B": bars})
    m.score = np.array([[85, 89.9, 90, 95, 80, 91], [91, 92, 93, 94, 95, 96]], dtype=float)
    entries = TOP_SCORE.entries(m, TOP_SCORE.default)
    assert entries[0].tolist() == [False, False, True, False, False, True]
    # Above 90 all along crosses only on the first day (no day before it).
    assert entries[1].tolist() == [True, False, False, False, False, False]
    # The regime filter's 85 doesn't lower the bar.
    m.risk_off = np.ones(6, dtype=bool)
    assert TOP_SCORE.entries(m, TOP_SCORE.default)[0].tolist() == entries[0].tolist()
    assert TOP_SCORE_MIN == 90.0


# --- Context, groups and masks ---------------------------------------------------------


def test_bands_take_the_first_band_whose_edge_is_above():
    assert band("score_band", 89.99) == "80-90"
    assert band("score_band", 90) == "90-95"
    assert band("score_band", 100) == "95+"
    assert band("atr_band", 1.0) == "ATR below 2%"
    assert band("rsi_band", 80) == "RSI 80+"
    assert band("volume_band", 1.5) == "volume 1.5-2x"
    assert band("rsi_band", None) is None and band("rsi_band", float("nan")) is None


def test_group_of_reads_the_context():
    ctx = {"regime": "bull", "risk_off": True, "sector": None, "score": 93.0, "atr_pct": 2.5}
    assert group_of("regime", ctx) == "bull"
    assert group_of("risk_off", ctx) == "regime filter on"
    assert group_of("sector", ctx) == "no sector"
    assert group_of("score_band", ctx) == "90-95"
    assert group_of("atr_band", ctx) == "ATR 2-3%"
    assert group_of("rsi_band", ctx) is None
    assert group_of("regime", {}) is None


def test_masks_match_the_context_everywhere(market):
    m = market
    t0 = 300
    for dimension in DIMENSIONS:
        seen = {}
        for s in range(len(m.symbols)):
            for t in range(t0, len(m.days), 7):
                g = group_of(dimension, signal_context(m, s, t))
                seen[(s, t)] = g
        for value in {g for g in seen.values() if g is not None}:
            mask = group_mask(m, dimension, value)
            assert mask.shape == m.close.shape
            for (s, t), g in seen.items():
                assert bool(mask[s, t]) == (g == value), (dimension, value, s, t)


def test_signal_context_is_what_the_close_knew(market):
    m = market
    ctx = signal_context(m, 1, 400)
    assert ctx["regime"] == m.regime[400].value
    assert ctx["risk_off"] == bool(m.risk_off[400])
    assert ctx["sector"] == "IT"
    assert ctx["atr_pct"] == pytest.approx(m.atr14[1, 400] / m.close[1, 400] * 100, abs=1e-4)


def test_a_filtered_strategy_skips_the_group(market):
    m = market
    base = STRATEGIES["score-swing"]
    p = StrategyProposal(
        id=7, dimension="sector", group_value="Banks", text="Skip entries where sector is Banks: x"
    )
    f = filtered_strategy(base, p)
    assert f.version == "score-swing-v1+proposal-7" and f.key != base.key
    params = {"min_score": 70.0, "stop_atr": 2.0}
    before, after = base.entries(m, params), f.entries(m, params)
    banks = np.array([sec == "Banks" for sec in m.sectors])
    assert before[banks].any() and not after[banks].any()
    assert (after[~banks] == before[~banks]).all()


# --- The proposal rule -----------------------------------------------------------------


def _trades(n_bad: int, n_good: int, bad_r=-0.8, good_r=0.6) -> list[ClosedTrade]:
    out = []
    for i in range(n_bad):
        out.append(ClosedTrade(bad_r + (0.1 if i % 2 else -0.1), -800.0, {"regime": "bear"}))
    for i in range(n_good):
        out.append(ClosedTrade(good_r + (0.2 if i % 2 else -0.2), 600.0, {"regime": "bull"}))
    return out


def test_a_clearly_losing_group_becomes_a_proposal():
    found = candidates(_trades(25, 30))
    assert [(c.group.dimension, c.group.value) for c in found] == [("regime", "bear")]
    c = found[0]
    assert c.group.trades == 25 and c.rest.trades == 30
    assert c.group.interval[1] < 0
    assert c.text.startswith("Skip entries where market regime is bear: 25 paper trades")
    assert c.evidence()["review_version"] == "paper-review-v1"


def test_no_proposal_from_too_few_trades_or_a_strategy_that_loses_everywhere():
    assert candidates(_trades(pr.MIN_GROUP_TRADES - 1, 30)) == []
    assert candidates(_trades(25, pr.MIN_GROUP_TRADES - 1)) == []
    # Losing in both regimes: nothing to filter, that is the revalidation's job.
    assert candidates(_trades(25, 30, good_r=-0.6)) == []
    # A range that reaches zero is not clear enough.
    wide = [ClosedTrade(r, 0.0, {"regime": "bear"}) for r in [-3.0, 2.5] * 12] + _trades(0, 30)
    assert candidates(wide) == []


def test_forward_split():
    out = forward_split(_trades(2, 3), "regime", "bear")
    assert out["trades"] == 5
    assert out["skipped"]["trades"] == 2 and out["kept"]["trades"] == 3
    assert out["skipped"]["avg_r"] == pytest.approx(-0.8)


# --- Validation ------------------------------------------------------------------------

BASE = Result(300, 0.10, 60, 0.05, 15.0)


def test_judge_passes_a_better_filter():
    ok, fails = judge(BASE, Result(220, 0.16, 45, 0.09, 14.0))
    assert ok and fails == []


@pytest.mark.parametrize(
    ("filtered", "text"),
    [
        (Result(90, 0.20, 40, 0.10, 14.0), "90 out-of-sample trades"),
        (Result(250, 0.10, 40, 0.10, 14.0), "out-of-sample expectancy"),
        (Result(250, 0.15, 40, -0.01, 14.0), "is not above 0"),
        (Result(250, 0.15, 40, 0.04, 14.0), "is not above the strategy's +0.050R"),
        (Result(250, 0.15, 40, 0.10, 17.5), "more than 2 points worse"),
    ],
)
def test_judge_fails_each_condition(filtered, text):
    ok, fails = judge(BASE, filtered)
    assert not ok and len(fails) == 1 and text in fails[0]


# --- The review ------------------------------------------------------------------------


def _row(seq, r, *, status="closed", sessions=8, pnl=None, ctx=None, exit_reason="stop"):
    day = date(2026, 1, 1) + timedelta(days=seq)
    return TradeRow(
        seq=seq,
        ticker=f"T{seq}",
        status=status,
        signal_id=None,
        signal_date=day,
        entry_date=day + timedelta(days=1),
        entry_price=Decimal("100"),
        initial_stop=Decimal("95"),
        target_t1=Decimal("110"),
        shares=100,
        current_stop=Decimal("97") if status == "open" else None,
        last_close=Decimal("104") if status == "open" else None,
        shares_held=100 if status == "open" else 0,
        exit_date=None if status == "open" else day + timedelta(days=sessions),
        exit_price=None if status == "open" else Decimal("95"),
        exit_reason=None if status == "open" else exit_reason,
        charges=Decimal("40"),
        net_pnl=Decimal(str(pnl if pnl is not None else r * 500)),
        r_multiple=Decimal(str(r)),
        sessions=sessions,
        context=ctx if ctx is not None else {"regime": "bull", "sector": "IT", "score": 92.0},
    )


def test_journal_allocation():
    rows = [_row(1, 0.8, status="open", ctx={"sector": "Banks"}), _row(2, -1.0)]
    j = journal(rows, 100_000.0, {})
    (pos,) = j["open"]
    assert pos["value"] == 10_400.0 and pos["pct_of_equity"] == 10.4
    assert j["allocation"]["cash"] == 89_600.0
    assert j["allocation"]["sectors"] == [
        {"sector": "Banks", "value": 10_400.0, "pct_of_equity": 10.4}
    ]
    assert [c["ticker"] for c in j["closed"]] == ["T2"]


def test_review_numbers_false_signals_and_gaps():
    sid = uuid4()
    rows = [
        _row(1, 2.0, exit_reason="trailing stop (2 x ATR, closing basis)", sessions=12),
        _row(2, -1.0, sessions=2),  # a false signal
        _row(3, -1.5, sessions=5),  # through the stop
        _row(4, 0.5, exit_reason="time stop (15 sessions)", sessions=15),
        _row(5, 0.3, status="open"),
    ]
    rows[0] = TradeRow(**{**rows[0].__dict__, "signal_id": sid})
    summary = {
        "equity": 1_000_000.0,
        "notes": ["Rejected signal X on 2026-01-02: bad", "The replay no longer gives the..."],
        "missed": {"taken": {"count": 4}},
        "performance": {
            "curve": {"total_return": 0.05, "max_drawdown_pct": 3.0},
            "benchmark": {"total_return": 0.02},
            "profile": {"exposure_pct": 40.0},
            "cash_rate_pct": 6.5,
        },
    }
    out = review(rows, summary, None, late_signals=2, why={sid: ["a", "b", "c"]})
    t = out["performance"]["trades"]
    assert t["trades"] == 4 and t["wins"] == 2 and t["win_rate"] == 0.5
    assert t["avg_win_r"] == 1.25 and t["avg_loss_r"] == -1.25 and t["payoff_ratio"] == 1.0
    assert (
        t["expectancy_r"] == 0.0 and t["expectancy_interval"][0] < 0 < t["expectancy_interval"][1]
    )
    assert "too few to judge" in t["sample_note"]
    assert out["performance"]["excess_return"] == 0.03
    plan = out["plan"]
    assert {e["exit"] for e in plan["exits"]} == {"trailing stop", "stop", "time stop"}
    assert plan["false_signals"]["trades"] == 1 and plan["false_signals"]["tickers"] == ["T2"]
    assert plan["gap_through"]["trades"] == 1
    assert plan["best"][0]["ticker"] == "T1" and plan["best"][0]["why"] == ["a", "b", "c"]
    assert plan["worst"][0]["ticker"] == "T3"
    assert plan["deviations"]["late_signals"] == 2
    assert len(plan["deviations"]["rejected_signals"]) == 1
    assert len(plan["deviations"]["replay_changes"]) == 1
    regimes = next(d for d in out["root_causes"]["dimensions"] if d["dimension"] == "regime")
    assert regimes["groups"][0]["trades"] == 4
    assert [b["ticker"] for b in out["root_causes"]["big_losses"]] == ["T3", "T2"]
    # Too few trades for observations.
    assert out["observations"] == []
    assert out["limitations"][0].startswith("Simulated")


def test_observations_need_30_trades_and_name_the_numbers():
    rows = [_row(i, -0.9, sessions=2) for i in range(12)] + [
        _row(100 + i, 0.6, sessions=10) for i in range(20)
    ]
    closed = [r for r in rows if r.status == "closed"]
    from app.paper.review import performance

    perf = performance(closed, {"performance": {"profile": {"exposure_pct": 20.0}}}, None)
    plan = plan_evaluation(closed, {}, 0, {})
    text = " ".join(observations(perf, plan))
    assert "Winners average 0.60R" in text
    assert "38% of closed trades were stopped out within 3 sessions" in text
    assert "20% of the account was in stocks" in text


def test_a_trade_without_context_counts_as_no_context():
    out = review([_row(1, -1.0, ctx={})], {}, None, 0, {})
    assert out["root_causes"]["no_context"] == 1
    assert out["root_causes"]["dimensions"] == []


def test_regime_mask_broadcasts_over_stocks():
    bars = [(100.0, 101.0, 99.0, 100.0)] * 4
    m = market_of({"A": bars, "B": bars})
    m.regime = [Regime.BULL, Regime.BEAR, Regime.BEAR, Regime.SIDEWAYS]
    mask = group_mask(m, "regime", "bear")
    assert mask.tolist() == [[False, True, True, False]] * 2
