"""The degradation monitor (app/analytics/health.py) and strategy statuses
(app/analytics/status.py). Pure."""

from datetime import date, datetime

import pytest

from app.analytics import status as st
from app.analytics.health import assess, false_retirement, percentile_of_mean

BACKTEST = [2.0, -1.0] * 100  # +0.5R a trade, standard deviation 1.5


def _assess(paper, **kw):
    kw = {
        "paper_entries": len(paper),
        "paper_sessions": 20,
        "backtest_trades_per_session": None,
    } | kw
    return assess(paper, BACKTEST, **kw)


def test_percentile_of_mean():
    assert percentile_of_mean(0.5, 50, BACKTEST) == pytest.approx(50, abs=8)
    assert percentile_of_mean(-1.0, 50, BACKTEST) < 1
    assert percentile_of_mean(0.0, 0, BACKTEST) is None


def test_verdicts_tell_variance_from_deterioration():
    assert _assess([-1.0] * 5).verdict == "too early"
    assert _assess([2.0, -1.0] * 10).verdict == "on track"
    # 20 trades at 0R: below the middle, but a backtest-like stretch.
    ordinary = _assess([1.0, -1.0] * 10)
    assert ordinary.verdict == "ordinary variance", ordinary.detail
    assert "no change needed" in ordinary.detail
    assert _assess([-1.0] * 20).verdict == "watch"  # bad, but only 20 trades
    worse = _assess([-1.0, 0.5] * 20)
    assert worse.verdict == "deteriorating" and "Unlikely to be bad luck" in worse.detail


def test_flags_for_frequency_losses_and_sectors():
    h = _assess(
        [-1.6] * 6 + [2.0] * 6,
        paper_entries=2,
        paper_sessions=100,
        backtest_trades_per_session=0.2,  # 20 expected
        paper_sectors=["IT"] * 12,
    )
    keys = {f.key for f in h.flags}
    assert keys == {"frequency", "losses", "sector"}
    calm = _assess([2.0, -1.0] * 6, paper_sessions=100, backtest_trades_per_session=0.12)
    assert calm.flags == []


def test_the_50_trade_rule_retires_good_strategies_sometimes():
    """How often the revalidation would retire a strategy exactly as good as its
    backtest: often for a thin edge, rarely for a strong one."""
    thin = false_retirement([2.0, -1.0] * 10 + [-1.0] * 6)  # about +0.12R a trade
    strong = false_retirement([2.0, -1.0] * 100)  # +0.5R
    assert thin is not None and strong is not None
    # A thin edge is nearly always retired within 200 trades; even +0.5R sometimes is.
    assert thin > 0.8 and 0.05 < strong < 0.2
    assert false_retirement([1.0]) is None


T = datetime(2026, 10, 1, 12, 0).astimezone()


def test_derived_status():
    research = st.derived(
        has_run=True, live_eligible=False, run_date=date(2026, 9, 1),
        failed_gates=["holdout"], account_status=None, account_start=None,
        retired_on=None, retired_reason=None,
    )  # fmt: skip
    assert research.status == st.RESEARCH and "holdout" in research.reason
    paper = st.derived(
        has_run=True, live_eligible=True, run_date=date(2026, 9, 1), failed_gates=[],
        account_status="active", account_start=date(2026, 9, 2), retired_on=None,
        retired_reason=None,
    )  # fmt: skip
    assert paper.status == st.PAPER and paper.since == date(2026, 9, 2)
    assert "Not yet proven" in paper.reason
    retired = st.derived(
        has_run=True, live_eligible=True, run_date=None, failed_gates=[],
        account_status="retired", account_start=None, retired_on=date(2026, 10, 5),
        retired_reason="rolling 50-trade expectancy -0.10R",
    )  # fmt: skip
    assert retired.status == st.RETIRED
    # My change counts, unless Jeron retired the strategy after it.
    mine = st.Change(st.SMALL, "Paper passed and evidence moderate", "owner", T)
    assert st.current(paper, [mine]).status == st.SMALL
    assert st.current(retired, [mine]).status == st.RETIRED


def _refusal(target, now_status=st.PAPER, **kw):
    kw = {
        "paper_gate": "passed",
        "real_gate": None,
        "evidence": "moderate",
        "revalidated": False,
    } | kw
    return st.refusal(
        target, st.StatusView(now_status, None, "", "jeron"), "a good long reason", **kw
    )


def test_promotion_needs_the_evidence():
    assert _refusal(st.SMALL) is None
    assert "paper gate" in _refusal(st.SMALL, paper_gate="not yet")
    assert "weak" in _refusal(st.SMALL, evidence="weak")
    assert "not rated" in _refusal(st.SMALL, evidence=None)
    assert "Small capital comes first" in _refusal(st.APPROVED)
    assert "real trades" in _refusal(st.APPROVED, now_status=st.SMALL, real_gate="not yet")
    assert _refusal(st.APPROVED, now_status=st.SMALL, real_gate="passed") is None
    assert _refusal(st.RESEARCH) is None  # demotion is always allowed
    assert "Unknown status" in _refusal("live")
    view = st.StatusView(st.PAPER, None, "", "jeron")
    assert "reason" in st.refusal(st.RETIRED, view, "no", paper_gate=None, real_gate=None,
                                  evidence=None, revalidated=False)  # fmt: skip


def test_a_retired_strategy_needs_a_revalidation():
    assert "must pass the gates" in _refusal(st.PAPER, now_status=st.RETIRED)
    assert _refusal(st.PAPER, now_status=st.RETIRED, revalidated=True) is None
    assert "paper first" in _refusal(st.SMALL, now_status=st.RETIRED, revalidated=True)
