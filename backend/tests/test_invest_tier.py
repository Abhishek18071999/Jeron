"""The invest tier and quality-trend-v1 (docs/plans/sections-v1.md): wider targets and
trail, the 250-session time stop, a strategy's own exit rule, and the point-in-time
fundamental score."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from app.backtest.engine import PortfolioRules, simulate
from app.backtest.market import fund_scores
from app.backtest.strategies import (
    COMMON_RULES,
    QUALITY_TREND,
    STRATEGIES,
    TIERS,
    ExitSignal,
    Tier,
    common_rules,
)
from app.fundamentals.score import Quarter, known_quarters, score_with_history
from tests.backtest_helpers import NO_COSTS, one_stock_market, signal_on, weekdays

IST = ZoneInfo("Asia/Kolkata")
NAN = float("nan")

# Signal at 100 (ATR 2, stop 3 x ATR = 94, R = 6): +1R on day 2, T1 (+3R = 118) on
# day 3, then the 4 x ATR trail (8 below the highest close) is broken on day 5.
BARS = [
    (100, 100, 100, 100),
    (100, 101, 99, 100),
    (100, 112, 100, 111),
    (111, 119, 110, 118),
    (118, 121, 117, 120),
    (120, 120, 111, 111.5),
    (110, 111, 109, 110),
    (110, 111, 109, 110),
]


def test_invest_books_half_at_3r_and_trails_at_4_atr():
    m = one_stock_market(BARS)
    result = simulate(m, Tier.INVEST, [(0, signal_on(m, 0, stop_atr=3.0))], 0, 7, None, NO_COSTS)
    (trade,) = result.trades
    assert trade.t1 == pytest.approx(118.0)
    reasons = [(f.day, f.reason) for f in trade.exits]
    assert reasons == [
        (3, "target T1 (+3R), half"),
        (6, "trailing stop (4 x ATR, closing basis)"),
    ]
    assert trade.exits[0].price == pytest.approx(118.0)
    assert trade.exits[1].price == pytest.approx(110.0)


def test_swing_keeps_the_section_5_target():
    m = one_stock_market(BARS)
    result = simulate(m, Tier.SWING, [(0, signal_on(m, 0, stop_atr=3.0))], 0, 7, None, NO_COSTS)
    assert result.trades[0].exits[0].reason == "target T1 (+2R), half"
    assert result.trades[0].t1 == pytest.approx(112.0)


def test_invest_time_stop_is_250_sessions():
    flat = [(100.0, 101.0, 99.0, 100.0)] * 260
    m = one_stock_market(flat)
    result = simulate(m, Tier.INVEST, [(0, signal_on(m, 0, stop_atr=3.0))], 0, 259, None, NO_COSTS)
    (trade,) = result.trades
    assert trade.exit_reason == "time stop (250 sessions)"
    assert trade.exit_day == 1 + 250 + 1  # entry day 1, 250 sessions later, next open


def test_exit_rule_sells_at_the_next_open():
    m = one_stock_market([(100, 101, 99, 100)] * 10)
    when = np.zeros_like(m.universe)
    when[0, 4] = True
    variant = replace(signal_on(m, 0, stop_atr=3.0), exit=ExitSignal(when, "results weakened"))
    result = simulate(m, Tier.INVEST, [(0, variant)], 0, 9, None, NO_COSTS)
    (trade,) = result.trades
    assert trade.exit_reason == "results weakened"
    assert trade.exit_day == 5


def test_tier_rules_apply_only_their_overrides():
    rules = PortfolioRules(risk_pct=1.5)
    assert TIERS[Tier.SWING].apply(rules) is rules
    invest = TIERS[Tier.INVEST].apply(rules)
    assert (invest.t1_r, invest.t2_r, invest.trail_atr, invest.risk_pct) == (3.0, 5.0, 4.0, 1.5)


def test_rules_text_is_unchanged_for_swing_and_positional():
    old = (
        "Book half at +2R, stop to breakeven at +1R (closing basis), trail the rest by "
        "2 x ATR(14) on closing basis, exiting at the next open."
    )
    assert old in common_rules(Tier.SWING)
    assert old in common_rules(Tier.POSITIONAL)
    assert len(common_rules(Tier.INVEST)) == len(COMMON_RULES)
    text = " ".join(QUALITY_TREND.rules(QUALITY_TREND.default))
    assert "Book half at +3R" in text and "4 x ATR(14)" in text
    assert "fund-v1 below 50" in text
    assert "250 sessions" in text


# The point-in-time fundamental score ----------------------------------------------


def _quarter_ends(start: date, n: int) -> list[date]:
    out, end = [], start
    for _ in range(n):
        out.append(end)
        month = end.month + 3
        year = end.year + (month > 12)
        month = month - 12 if month > 12 else month
        end = date(year, month, {3: 31, 6: 30, 9: 30, 12: 31}[month])
    return out


def _filing(end: date, published: date, profit: float, *, consolidated: bool = True, **kw):
    return Quarter(
        period_end=end,
        disseminated_at=datetime.combine(published, datetime.min.time(), IST) + timedelta(hours=16),
        consolidated=consolidated,
        revenue=profit * 10,
        net_profit=profit,
        eps=profit / 10,
        finance_costs=1.0,
        depreciation=2.0,
        profit_before_tax=profit * 1.3,
        other_income=0.5,
        shares=10.0,
        **kw,
    )


def _history(n: int = 8, grow: float = 0.05) -> list[Quarter]:
    ends = _quarter_ends(date(2022, 3, 31), n)
    return [_filing(e, e + timedelta(days=40), 10.0 * (1 + grow) ** i) for i, e in enumerate(ends)]


def _days_and_close(first: date, n: int) -> tuple[list[date], np.ndarray]:
    days = weekdays(first, n)
    return days, np.full((1, n), 500.0)


def test_a_filing_counts_from_the_next_session():
    filings = _history()
    last = filings[-1].disseminated_at.date()
    days, close = _days_and_close(last - timedelta(days=10), 30)
    scores = fund_scores(days, ["AAA"], {"AAA": filings}, close)
    assert scores is not None
    on_filing_day = days.index(last)
    expected = score_with_history(
        known_quarters(
            filings, datetime.combine(last + timedelta(days=1), datetime.min.time(), IST)
        ),
        last,
        {q.disseminated_at.date(): 500.0 for q in filings},
    ).score
    assert expected is not None
    assert scores[0, on_filing_day + 1] == pytest.approx(expected)
    # The day before the newest filing it is still the score from the filing before.
    assert scores[0, on_filing_day] != pytest.approx(expected)


def test_a_revision_replaces_the_quarter_and_no_data_is_nan():
    filings = _history()
    last = filings[-1]
    revised_on = last.disseminated_at.date() + timedelta(days=14)
    revision = _filing(last.period_end, revised_on, -50.0)  # a loss after all
    days, close = _days_and_close(last.disseminated_at.date() - timedelta(days=3), 30)
    scores = fund_scores(
        days, ["AAA", "BBB"], {"AAA": [*filings, revision]}, np.vstack([close, close])
    )
    assert scores is not None
    before, after = days.index(revised_on), days.index(revised_on) + 1
    assert scores[0, after] < scores[0, before]
    assert np.isnan(scores[1]).all()
    assert fund_scores(days, ["AAA"], None, close) is None


def test_a_stale_score_is_nan_and_a_qualified_opinion_scores_zero():
    filings = _history()
    last = filings[-1]
    days, close = _days_and_close(last.disseminated_at.date(), 200)
    scores = fund_scores(days, ["AAA"], {"AAA": filings}, close)
    assert scores is not None
    stale = last.period_end + timedelta(days=201)
    assert not np.isnan(scores[0, 1])
    assert np.isnan(scores[0, [i for i, d in enumerate(days) if d >= stale]]).all()

    qualified = [*filings[:-1], replace(last, audit_opinion="Qualified")]
    scores = fund_scores(days, ["AAA"], {"AAA": qualified}, close)
    assert scores is not None and scores[0, 1] == 0.0


def test_consolidated_beats_a_later_standalone_filing():
    filings = _history()
    last = filings[-1]
    standalone = _filing(
        last.period_end, last.disseminated_at.date() + timedelta(days=5), -50.0, consolidated=False
    )
    later = datetime.combine(date(2030, 1, 1), datetime.min.time(), IST)
    assert known_quarters([*filings, standalone], later)[-1] is last


# quality-trend-v1 -----------------------------------------------------------------


def test_quality_trend_enters_on_the_first_day_and_exits_on_weak_results():
    m = one_stock_market([(100, 101, 99, 100)] * 8)
    m.ema50 = np.full((1, 8), 90.0)
    m.ema200 = np.array([[95.0, 95, 85, 85, 85, 85, 85, 85]])
    m.fund_score = np.array([[80.0, 80, 80, 80, 45, NAN, 80, 80]])
    params = {"min_fund": 70.0, "stop_atr": 3.0}
    entries = QUALITY_TREND.entries(m, params)
    # Uptrend from day 2 (50-day above 200-day); fund falls below 70 on day 4 and is
    # unknown on day 5, so day 6 is a new first day.
    assert entries[0].tolist() == [False, False, True, False, False, False, True, False]
    exits = QUALITY_TREND.exits(m, params)
    assert exits is not None
    assert exits.when[0].tolist() == [False, False, False, False, True, False, False, False]
    assert STRATEGIES["quality-trend"].tier is Tier.INVEST


def test_quality_trend_needs_the_fundamentals():
    m = one_stock_market([(100, 101, 99, 100)] * 3)
    with pytest.raises(ValueError, match="fundamentals-import"):
        QUALITY_TREND.entries(m, QUALITY_TREND.default)
