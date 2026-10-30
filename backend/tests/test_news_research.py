from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from app.backtest import news_research
from app.backtest.market import build_market
from app.backtest.strategies import MIN_NEWS_SCORE, RS_PULLBACK, TOP_SCORE
from tests.test_backtest_walkforward import synthetic_inputs


@pytest.fixture(scope="module")
def market():
    base = build_market(synthetic_inputs(n_days=1400, n_stocks=30))
    rng = np.random.default_rng(7)
    shape = base.close.shape
    # Bad news on about a fifth of stock-days, good news on another fifth.
    news = np.where(rng.random(shape) < 0.2, 25.0, np.where(rng.random(shape) < 0.25, 75.0, 50.0))
    blackout = rng.random(shape) < 0.05
    return replace(base, news_score=news, results_blackout=blackout, news_labeller="test-model")


def test_arms_switch_exactly_their_rules():
    # top-score-v1 has both rules on; the arm decides, not the registered version.
    arms = {a.key: news_research.arm_strategy(TOP_SCORE, a) for a in news_research.ARMS}
    assert (arms["none"].min_news_score, arms["none"].results_blackout) == (None, False)
    assert (arms["news"].min_news_score, arms["news"].results_blackout) == (MIN_NEWS_SCORE, False)
    assert (arms["blackout"].min_news_score, arms["blackout"].results_blackout) == (None, True)
    assert (arms["both"].min_news_score, arms["both"].results_blackout) == (MIN_NEWS_SCORE, True)
    assert arms["news"].version == "top-score-v1/news"


def test_an_arm_without_its_input_is_not_run_as_the_base(market):
    bare = replace(market, news_score=None, results_blackout=None)
    rows = news_research.run(bare, [RS_PULLBACK.key])
    assert [r.ev is not None for r in rows] == [True, False, False, False]
    assert "news-label" in (rows[1].error or "")
    assert "events job" in (rows[2].error or "")


def test_news_filter_keeps_bad_news_trades_out(market):
    rows = news_research.run(market, [RS_PULLBACK.key])
    assert all(r.ev is not None for r in rows)
    by_arm = {r.arm.key: r for r in rows}
    for key in ("news", "both"):
        assert all(
            market.news_score[t.s, t.signal_day] >= MIN_NEWS_SCORE for t in by_arm[key].trades
        )
    base = news_research.by_news_score(market, by_arm["none"].trades)
    assert sum(b.trades for b in base) == len(by_arm["none"].trades)
    assert base[0].trades > 0  # the base run did take bad-news trades

    cutoff = market.days[len(market.days) * 3 // 4]
    before, after = news_research.split_at(market, by_arm["none"].trades, cutoff)
    assert before.trades + after.trades == len(by_arm["none"].trades)

    text = news_research.report(rows, market, "test data", cutoff)
    assert "| rs-pullback-v1 | News filter |" in text
    assert f"From {cutoff}" in text
    assert "bad news (below 40)" in text and "test data" in text


def test_report_without_news_says_why(market):
    bare = replace(market, news_score=None)
    rows = news_research.run(bare, [RS_PULLBACK.key])
    text = news_research.report(rows, bare, "note", date(2024, 1, 1))
    assert "not run: no news labels" in text
    assert "by the news score" not in text
