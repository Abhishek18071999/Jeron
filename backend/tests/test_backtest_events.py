"""M6 in the backtester: the news score per stock and day, and the strategy versions with
the results blackout and the news filter."""

from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest

from app.backtest.market import build_market, news_scores
from app.backtest.strategies import MIN_NEWS_SCORE, STRATEGIES, with_events
from app.backtest.walkforward import evaluate
from app.config import Settings
from app.data.events import ResultsDate
from app.news.labels import DatedLabel, EventType, news_score
from app.paper.job import portfolio_rules
from tests.backtest_helpers import one_stock_market, weekdays
from tests.test_backtest_walkforward import synthetic_inputs

E = EventType


def test_news_scores_match_the_score_function():
    days = weekdays(date(2024, 1, 1), 200)
    labels = {
        "AAA": [
            DatedLabel(date(2024, 1, 10), E.RESULTS, -2),
            DatedLabel(date(2024, 2, 3), E.ORDER_WIN, 2),  # a Saturday
            DatedLabel(date(2024, 3, 1), E.OTHER, 0),
        ],
        "BBB": [DatedLabel(date(2024, 5, 1), E.REGULATORY_ACTION, -1)],
    }
    scores = news_scores(days, ["AAA", "BBB", "CCC"], labels)
    assert scores is not None
    for k, symbol in enumerate(["AAA", "BBB", "CCC"]):
        expected = [news_score(labels.get(symbol, []), d) for d in days]
        assert scores[k] == pytest.approx(expected)
    assert news_scores(days, ["AAA"], None) is None


def test_bad_news_keeps_a_stock_out():
    m = one_stock_market([(100.0, 101.0, 99.0, 100.0)] * 60)
    score = np.full((1, 60), 50.0)
    score[0, 20:30] = 25.0  # after a -2 results label
    strategy = replace(STRATEGIES["score-swing"], condition=lambda m, p: np.ones_like(m.universe))
    events = with_events(strategy)
    plain = strategy.entries(m, strategy.default)
    assert plain.all()
    assert events.entries(m, events.default).all()  # no labels: no filter
    filtered = events.entries(replace(m, news_score=score), events.default)
    assert not filtered[0, 20:30].any() and filtered[0, :20].all() and filtered[0, 30:].all()
    assert MIN_NEWS_SCORE == 40


def test_events_versions_are_new_strategies():
    for key in ("score-swing", "breakout-52w", "pullback-trend"):
        base, events = STRATEGIES[key], STRATEGIES[f"{key}-events"]
        assert events.version == f"{key}-events-v1"
        assert events.results_blackout and not base.results_blackout
        assert events.min_news_score == MIN_NEWS_SCORE and base.min_news_score is None
        assert events.grid == base.grid and events.tier == base.tier
        rules = events.rules(events.default)
        assert any("results board meeting" in r for r in rules)
        assert any("news score" in r for r in rules)
        assert not any("news score" in r for r in base.rules(base.default))


def test_evaluate_turns_on_the_blackout_and_reports_coverage():
    inputs = synthetic_inputs(n_stocks=12)
    symbol = inputs.stocks[0].symbol
    meetings = [
        ResultsDate(d, d - timedelta(days=10)) for d in inputs.days[100::63]
    ]  # quarterly-ish
    inputs.results = {symbol: meetings}
    inputs.news = {symbol: [DatedLabel(inputs.days[400], E.RESULTS, -2)]}
    inputs.news_labeller = "test-model"
    m = build_market(inputs)
    base = evaluate(m, STRATEGIES["breakout-52w"])
    events = evaluate(m, STRATEGIES["breakout-52w-events"])
    assert base.summary["brains"]["results_blackout"] is False
    brains = events.summary["brains"]
    assert brains["results_blackout"] is True
    assert brains["news_labeller"] == "test-model"
    labelled = inputs.days[400]
    horizon = labelled + timedelta(days=30 * 4)  # results: 30-day half-life, 4 half-lives
    assert brains["news_years"] == sorted({labelled.year, horizon.year})
    assert brains["results_calendar_years"][0] == inputs.days[97].year
    blocked = m.results_blackout
    assert blocked is not None
    assert not any(blocked[0, t.signal_day] for t in events.sim.trades if t.symbol == symbol)


def test_paper_accounts_of_events_versions_use_the_blackout():
    settings = Settings()
    assert portfolio_rules(settings, STRATEGIES["score-swing"].tier).results_blackout is False
    events = STRATEGIES["score-swing-events"]
    assert portfolio_rules(settings, events.tier, events.results_blackout).results_blackout
