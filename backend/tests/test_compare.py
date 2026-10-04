"""Backtest vs paper vs real (spec section 7): gates, expected ranges, stages and the
causes of divergence; then the same on Postgres."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.analytics.compare import (
    ClosedTrade,
    Pair,
    divergence,
    expected_range,
    paper_gate,
    real_gate,
    record,
    stage,
)
from app.analytics.service import compare
from app.journal.service import add_fill, decide, manual_entry
from app.main import app
from app.models import BacktestTrade, PaperDay, PaperTrade
from tests.conftest import requires_db
from tests.journal_helpers import make_account, make_signal
from tests.test_alerts_db import empty_session as empty_session  # noqa: F401 - the fixture

D0 = date(2025, 1, 1)


def trades(rs):
    return [ClosedTrade(r, r * 1000, 5, D0 + timedelta(days=i)) for i, r in enumerate(rs)]


def test_record_and_drawdown_in_r():
    rec = record(trades([1.0, -1.0, -1.0, 2.0, -0.5]))
    assert rec.trades == 5 and rec.win_rate == pytest.approx(0.4)
    assert rec.expectancy_r == pytest.approx(0.1)
    assert rec.profit_factor == pytest.approx(3000 / 2500)
    assert rec.max_drawdown == pytest.approx(2.0) and rec.drawdown_unit == "R"
    assert record([]).expectancy_r is None


def test_expected_range_narrows_with_more_trades():
    ref = [2.0, -1.0, -1.0, 1.5, -1.0, 3.0, -1.0, 0.5]  # mean 0.375
    short = expected_range(ref, 10)
    long = expected_range(ref, 200)
    assert short is not None and long is not None
    assert short[0] < long[0] < 0.375 < long[1] < short[1]
    assert expected_range(ref, 10) == short  # seeded: reproducible
    assert expected_range([], 10) is None


def test_paper_gate():
    ref = [2.0, -1.0, -1.0, 1.5, -1.0, 3.0, -1.0, 0.5] * 10
    few = record(trades([1.0] * 10))
    gate, _ = paper_gate(few, 40, ref)
    assert gate.status == "not yet" and "40 of 91 days" in gate.detail
    assert "10 of 30 closed trades" in gate.detail
    good = record(trades([2.0, -1.0, -1.0, 1.5, -1.0, 3.0, -1.0, 0.5] * 5))
    assert paper_gate(good, 120, ref)[0].status == "passed"
    losing = record(trades([-1.0, 0.5] * 20))
    assert paper_gate(losing, 120, ref)[0].status == "failed"
    too_good = record(trades([3.0] * 40))  # far above the backtest: something is off
    assert "outside" in paper_gate(too_good, 120, ref)[0].detail


def test_real_gate_and_stages():
    paper_rs = [2.0, -1.0, -1.0, 1.5, -1.0, 3.0, -1.0, 0.5] * 5
    assert real_gate(record([]), 0, paper_rs)[0].status == "not yet"
    mine = record(trades([2.0, -1.0, 1.5, -1.0, 0.5, 1.0]))
    assert real_gate(mine, 30, paper_rs)[0].status == "not yet"
    passed = real_gate(mine, 100, paper_rs)[0]
    assert passed.status == "passed"
    paper_passed, _ = paper_gate(record(trades(paper_rs)), 120, paper_rs)
    assert stage(False, paper_passed, passed) == "research only"
    assert stage(True, None, None) == "paper"
    assert stage(True, paper_passed, None) == "small real"
    assert stage(True, paper_passed, passed) == "full capital"


def test_divergence_names_the_causes():
    pairs = [
        Pair(D0, "AAA", 100.0, 96.0, D0, 1.0, 101.0, D0 + timedelta(days=3), 0.2),
        Pair(D0, "BBB", 200.0, 190.0, D0, 2.0, 202.0, D0 + timedelta(days=1), 1.0),
    ]
    d = divergence(pairs, [2.5, -1.0])
    assert d.slippage_r == pytest.approx((0.25 + 0.2) / 2)
    assert d.late_days == pytest.approx(2.0)
    assert d.exit_gap_r == pytest.approx(-0.9)
    assert (d.skipped, d.skipped_winners, d.skipped_r) == (2, 1, 1.5)
    text = " ".join(d.causes)
    for word in ("Slippage", "Late entries", "Exits", "Skipped signals"):
        assert word in text
    clean = divergence([Pair(D0, "AAA", 100.0, 96.0, D0, 1.0, 100.0, D0, 1.0)], [])
    assert clean.causes == []


def _paper_trade(account, seq, signal_id, ticker, entry_date, r, status="closed"):
    return PaperTrade(
        account_id=account.id,
        seq=seq,
        signal_id=signal_id,
        ticker=ticker,
        status=status,
        signal_date=entry_date - timedelta(days=1),
        entry_date=entry_date,
        entry_price=Decimal(100),
        initial_stop=Decimal(90),
        target_t1=Decimal(120),
        shares=10,
        shares_held=0 if status == "closed" else 10,
        exit_date=entry_date + timedelta(days=7) if status == "closed" else None,
        exit_price=Decimal(100 + 10 * r) if status == "closed" else None,
        charges=Decimal(0),
        dividends=Decimal(0),
        net_pnl=Decimal(100 * r),
        r_multiple=Decimal(r),
        sessions=5,
    )


@requires_db
def test_compare_on_postgres(empty_session):
    s = empty_session
    summary = {
        "out_of_sample": {
            "trades": {"trades": 120, "win_rate": 0.45, "expectancy_r": 0.2,
                       "profit_factor": "inf", "avg_sessions": 8.5},
            "curve": {"max_drawdown_pct": 12.5},
        },
        "periods": {"out_of_sample": ["2019-01-01", "2024-06-28"]},
    }  # fmt: skip
    account = make_account(s, live=True, summary=summary)
    account.last_date = date(2025, 5, 30)
    for i, r in enumerate([2.0, -1.0, -1.0, 1.5, -1.0, 3.0]):
        s.add(
            BacktestTrade(
                run_id=account.backtest_run_id, seq=i, segment="oos", symbol="X", variant="v",
                signal_date=D0, entry_date=D0, exit_date=D0, entry_price=1, stop_price=1,
                target_price=1, exit_price=1, shares=1, exit_reason="stop", gross_pnl=0,
                charges=0, dividends=0, net_pnl=0, r_multiple=r, regime="bull", score=90,
                sessions=1,
            )
        )  # fmt: skip
    taken = make_signal(s, account, "AAA", date(2025, 3, 3), date(2025, 3, 5))
    skipped = make_signal(s, account, "BBB", date(2025, 3, 10), date(2025, 3, 12))
    pending = make_signal(s, account, "CCC", date(2025, 3, 17), date(2025, 3, 19))
    s.add_all(
        [
            _paper_trade(account, 1, taken, "AAA", date(2025, 3, 4), 1.0),
            _paper_trade(account, 2, skipped, "BBB", date(2025, 3, 11), 2.0),
            _paper_trade(account, 3, pending, "CCC", date(2025, 3, 18), -1.0),
            PaperDay(account_id=account.id, trade_date=date(2025, 5, 30), equity=1,
                     drawdown_pct=Decimal("4.5"), heat_pct=0, open_positions=0),
        ]
    )  # fmt: skip
    s.commit()
    entry = decide(s, taken, "taken", stop=Decimal(90))
    add_fill(s, entry, date(2025, 3, 6), "buy", 10, Decimal(102))
    add_fill(s, entry, date(2025, 3, 20), "sell", 10, Decimal(104))
    decide(s, skipped, "skipped", reason="results next week")
    own = manual_entry(s, "OWN", stop=Decimal(50))
    add_fill(s, own, date(2025, 4, 1), "buy", 5, Decimal(60))

    rows = compare(s, as_of=date(2025, 6, 2))
    (row, mine) = rows
    assert row.backtest is not None and row.backtest.trades == 120
    assert row.backtest.profit_factor is None and row.backtest.max_drawdown == 12.5
    assert row.paper is not None and row.paper.trades == 3 and row.paper.max_drawdown == 4.5
    assert row.paper_gate is not None and row.paper_gate.status == "not yet"
    assert row.stage == "paper"
    assert row.real.trades == 1 and row.real.expectancy_r == pytest.approx(0.1667, abs=1e-3)
    d = row.divergence
    assert d is not None and d.pairs == 1
    assert d.slippage_r == pytest.approx(0.2) and d.late_days == 2.0
    assert d.exit_gap_r == pytest.approx(0.1667 - 1.0, abs=1e-3)
    assert (d.skipped, d.skipped_winners) == (2, 1)  # skipped BBB and pending CCC
    assert mine.stage == "own ideas" and mine.real.trades == 0

    body = TestClient(app).get("/analytics/compare").json()
    assert body[0]["stage"] == "paper" and body[0]["paper_gate"]["status"] == "not yet"
