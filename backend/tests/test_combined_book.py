"""The combined book (docs/plans/combined-book-v1.md): two strategies in one account."""

from collections import Counter

import pytest

from app.backtest.engine import Book, PortfolioRules, Variant, simulate
from app.backtest.market import build_market
from app.backtest.strategies import COMBINED_BOOK, STRATEGIES, Combined, Tier
from app.backtest.walkforward import evaluate, evaluate_combined
from tests import test_backtest_engine as golden
from tests.backtest_helpers import NO_COSTS, market_of
from tests.test_backtest_walkforward import synthetic_inputs

SIGNAL = golden.SIGNAL
FILL = (100.0, 101.0, 99.0, 100.0)
FLAT = golden.FLAT
RULES = PortfolioRules(cash_rate_pct=0, max_position_pct=5, max_positions=3)


def _market(n_stocks=6, days=5):
    return market_of({f"S{i}": [SIGNAL, FILL, *[FLAT] * (days - 2)] for i in range(n_stocks)})


def _on(m, label, signals):
    """A variant with entries at {day: [stock indices]}."""
    entries = m.universe & False
    for day, stocks in signals.items():
        for s in stocks:
            entries[s, day] = True
    return Variant(label, {"stop_atr": 2.0}, entries)


def test_tie_goes_to_the_first_book_and_a_stock_is_ordered_once():
    m = _market()
    a = Book("A", [(0, _on(m, "a", {0: [0, 1]}))])
    b = Book("B", [(0, _on(m, "b", {0: [1, 2, 3]}))])
    result = simulate(m, Tier.POSITIONAL, [a, b], 0, 4, RULES, NO_COSTS)
    assert [(o.book, m.symbols[o.s]) for o in result.orders] == [
        ("A", "S0"),
        ("A", "S1"),
        ("B", "S2"),
    ]
    reasons = {(m.symbols[s.s], s.reason) for s in result.skipped if s.day == 0}
    assert ("S1", "already ordered by A") in reasons
    assert ("S3", "no free position slot") in reasons
    assert {t.symbol: t.book for t in result.trades} == {"S0": "A", "S1": "A", "S2": "B"}


def test_the_book_with_fewer_open_positions_orders_first():
    m = _market()
    # Day 0: A buys S0. Day 2: both books signal with one slot left; B holds nothing.
    a = Book("A", [(0, _on(m, "a", {0: [0], 2: [1, 2]}))])
    b = Book("B", [(0, _on(m, "b", {2: [3, 4]}))])
    rules = PortfolioRules(cash_rate_pct=0, max_position_pct=5, max_positions=2)
    result = simulate(m, Tier.POSITIONAL, [a, b], 0, 4, rules, NO_COSTS)
    assert [(o.book, o.signal_day, m.symbols[o.s]) for o in result.orders] == [
        ("A", 0, "S0"),
        ("B", 2, "S3"),
    ]


def test_a_stock_held_by_one_book_is_not_bought_by_the_other():
    m = _market()
    a = Book("A", [(0, _on(m, "a", {0: [0]}))])
    b = Book("B", [(0, _on(m, "b", {2: [0, 1]}))])
    result = simulate(m, Tier.POSITIONAL, [a, b], 0, 4, RULES, NO_COSTS)
    assert [(o.book, m.symbols[o.s]) for o in result.orders] == [("A", "S0"), ("B", "S1")]


def test_one_book_trades_as_a_plain_schedule():
    m = _market()
    v = _on(m, "a", {0: [0, 1, 2, 3]})
    plain = simulate(m, Tier.POSITIONAL, [(0, v)], 0, 4, RULES, NO_COSTS)
    booked = simulate(m, Tier.POSITIONAL, [Book("", [(0, v)])], 0, 4, RULES, NO_COSTS)
    assert list(plain.equity) == list(booked.equity)
    assert [(t.symbol, t.entry, t.exit_price) for t in plain.trades] == [
        (t.symbol, t.entry, t.exit_price) for t in booked.trades
    ]


def test_the_pre_registered_book():
    assert COMBINED_BOOK.version == "combined-book-v1"
    assert [s.version for s in COMBINED_BOOK.members] == ["rs-pullback-v1", "results-drift-v1"]
    assert COMBINED_BOOK.tier == Tier.POSITIONAL
    assert COMBINED_BOOK.key not in STRATEGIES  # no paper account is opened for it


@pytest.fixture(scope="module")
def market():
    return build_market(synthetic_inputs())


def test_combined_walk_forward_keeps_each_strategys_own_choices(market):
    book = Combined(
        "test-book",
        "test-book-v1",
        "Test book",
        "two positional strategies",
        (STRATEGIES["rs-pullback"], STRATEGIES["breakout-52w"]),
    )
    ev = evaluate_combined(market, book, all_trial_sharpes=[0.01] * 60)
    for strategy in book.members:
        own = evaluate(market, strategy)
        mine = [(s, label) for s, label, _ in ev.schedule if label.startswith(strategy.version)]
        assert mine == [(s, f"{strategy.version}: {label}") for s, label, _ in own.schedule]
    combined = ev.summary["combined"]
    assert combined["trials_all"] == 61
    assert ev.summary["out_of_sample"]["variants_tried"] == 8
    parts = combined["by_strategy"]
    assert sum(p["out_of_sample"]["trades"] for p in parts.values()) == len(ev.oos_trades)
    assert all(t.book in parts for t in ev.sim.trades)
    assert all(p["out_of_sample"]["trades"] > 0 for p in parts.values())
    # One position per stock, and at most 8 open at once.
    open_on: Counter[int] = Counter()
    for t in ev.sim.trades:
        for day in range(t.entry_day, t.exit_day):
            open_on[day] += 1
    assert max(open_on.values()) <= 8
    by_symbol: dict[str, list[tuple[int, int]]] = {}
    for t in ev.sim.trades:
        by_symbol.setdefault(t.symbol, []).append((t.entry_day, t.exit_day))
    for spans in by_symbol.values():
        spans.sort()
        assert all(b[0] >= a[1] for a, b in zip(spans, spans[1:], strict=False))
