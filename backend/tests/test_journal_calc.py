"""Journal maths: positions from fills, and stats per strategy."""

from datetime import date
from decimal import Decimal

import pytest

from app.journal.calc import Fill, JournalRow, position, strategy_stats

D = Decimal


def test_open_position_marked_at_the_close():
    fills = [
        Fill(date(2026, 1, 2), "buy", 100, D(100), D(20)),
        Fill(date(2026, 1, 5), "buy", 100, D(102), D(20)),
    ]
    p = position(fills, stop=D(95), last_close=D(106))
    assert p.status == "open" and p.held == 200
    assert p.avg_entry == D("101.0000")
    assert p.realised_pnl == D("-40.00")  # charges so far
    assert p.open_pnl == D("1000.00")
    assert p.initial_risk == D("1200.00")  # (101 - 95) x 200
    assert p.r_multiple == D("0.8000")  # (1000 - 40) / 1200


def test_partial_then_full_exit():
    fills = [
        Fill(date(2026, 1, 2), "buy", 100, D(100), D(10)),
        Fill(date(2026, 1, 9), "sell", 50, D(110), D(10)),
        Fill(date(2026, 1, 20), "sell", 50, D(100), D(10)),
    ]
    p = position(fills, stop=D(95), last_close=D(90))
    assert p.status == "closed" and p.held == 0
    assert p.avg_exit == D("105.0000")
    assert p.realised_pnl == D("470.00")  # 500 profit - 30 charges
    assert p.open_pnl == D(0)
    assert p.r_multiple == D("0.9400")  # 470 / 500
    assert (p.first_date, p.last_date) == (date(2026, 1, 2), date(2026, 1, 20))


def test_no_stop_no_r_and_no_overselling():
    p = position([Fill(date(2026, 1, 2), "buy", 10, D(50))], stop=None, last_close=None)
    assert p.r_multiple is None and p.open_pnl is None
    assert position([], None, None).status == "no fills"
    with pytest.raises(ValueError, match="Sold 20"):
        position(
            [Fill(date(2026, 1, 2), "buy", 10, D(50)), Fill(date(2026, 1, 3), "sell", 20, D(50))],
            None,
            None,
        )


def row(key, decision, status=None, r=None, pnl=None, followed=None, days=None, signal=True):
    return JournalRow(key, decision, followed, status, r, pnl, days, has_signal=signal)


def test_stats_per_strategy():
    rows = [
        row("a", "taken", "closed", D(2), D(2000), True, 10),
        row("a", "taken", "closed", D(-1), D(-1000), False, 4),
        row("a", "modified", "open", D("0.5"), None),
        row("a", "skipped"),
        row("a", None),
        row(None, "taken", "closed", D(1), D(500), None, 2, signal=False),
    ]
    a, manual = strategy_stats(rows)
    assert (a.signals, a.pending, a.taken, a.skipped, a.modified) == (5, 1, 2, 1, 1)
    assert (a.open, a.closed, a.wins) == (1, 2, 1)
    assert a.win_rate == D("0.5000") and a.avg_r == D("0.5000")
    assert a.profit_factor == D("2.0000") and a.net_pnl == D(1000)
    assert a.avg_holding_days == D("7.0000")
    assert (a.followed_avg_r, a.deviated_avg_r) == (D("2.0000"), D("-1.0000"))
    assert manual.strategy_key is None and manual.signals == 0 and manual.closed == 1
