"""Stress and tail risk of the real positions (app/portfolio/risk.py), with numbers
worked by hand, and `/portfolio/risk` on a real Postgres."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.exits.job import next_session
from app.journal.service import add_fill, manual_entry
from app.main import app
from app.portfolio.risk import (
    Position,
    Series,
    beta,
    correlation,
    daily_returns,
    risk_report,
    tail,
    worst_gap,
)
from tests.conftest import requires_db
from tests.test_alerts_db import empty_session as empty_session  # noqa: F401 - the fixture
from tests.test_market_db import CAL, DAYS, _adjusted, _seed

D0 = date(2025, 1, 1)


def _days(n: int) -> list[date]:
    return [D0 + timedelta(days=i) for i in range(n)]


def _series(rets: list[float], start: float = 100.0, gaps: dict[int, float] | None = None):
    closes = [start]
    for r in rets:
        closes.append(closes[-1] * (1 + r))
    opens = [c for c in closes]
    for i, g in (gaps or {}).items():
        opens[i] = closes[i - 1] * (1 + g)
    return Series(_days(len(closes)), closes, opens)


# An index that alternates +1% and -1%, and stocks built from it.
IDX = [0.01 if i % 2 == 0 else -0.01 for i in range(120)]


def test_returns_and_correlation():
    s = Series(_days(3), [100.0, 110.0, 99.0])
    r = daily_returns(s)
    assert r[_days(3)[1]] == pytest.approx(0.10) and r[_days(3)[2]] == pytest.approx(-0.10)
    assert correlation([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert correlation([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert correlation([1, 1, 1], [1, 2, 3]) is None


def test_beta_of_a_stock_twice_the_index():
    index = daily_returns(_series(IDX))
    stock = daily_returns(_series([2 * r for r in IDX]))
    b, n, vol = beta(stock, index)
    assert b == pytest.approx(2.0) and n == 120
    # 2% a day either way: sd = 2% x sqrt(120/119), annualised by sqrt(252).
    assert vol == pytest.approx(0.02 * (120 / 119) ** 0.5 * 252**0.5 * 100)
    # Too few common sessions: no beta.
    short = dict(list(stock.items())[:50])
    assert beta(short, index)[0] is None


def test_worst_gap():
    s = _series([0.0] * 10, gaps={4: -0.08, 7: -0.03})
    gap, day = worst_gap(s) or (0, None)
    assert gap == pytest.approx(-0.08) and day == s.days[4]
    assert worst_gap(Series(_days(3), [1.0, 1.0, 1.0])) is None  # no opens


def test_tail_by_hand():
    # 100 days: losses 1..100. 95% VaR: exceeded on 5 days -> the 6th largest, 95.
    losses = [float(x) for x in range(1, 101)]
    var95, var99, es = tail(losses)
    assert var95 == 95 and var99 == 99
    # 97.5% ES: the average of the worst ceil(2.5) = 3 days.
    assert es == pytest.approx((100 + 99 + 98) / 3)
    # Only gains: no loss to report.
    assert tail([-1.0] * 100) == (0.0, 0.0, 0.0)


def test_report_book_shocks_and_gaps():
    index = _series(IDX, 1000)
    a = _series([2 * r for r in IDX], gaps={60: -0.10})
    b = _series([0.5 * r for r in IDX])
    positions = [
        Position("A", 100, a.closes[-1], a.closes[-1] * 0.95),  # stop 5% below
        Position("B", 200, b.closes[-1], None),
    ]
    r = risk_report(positions, {"A": a, "B": b}, index, equity=100_000, as_of=a.days[-1])
    va, vb = 100 * a.closes[-1], 200 * b.closes[-1]
    by = {s.ticker: s for s in r.stocks}
    assert by["A"].beta == pytest.approx(2.0) and by["B"].beta == pytest.approx(0.5)
    assert r.book_beta == pytest.approx((2 * va + 0.5 * vb) / (va + vb))
    # Nifty 500 -10%: A loses 20% of its value, B 5%.
    ten = next(x for x in r.shocks if x.index_move_pct == -10)
    assert ten.loss == pytest.approx(0.2 * va + 0.05 * vb)
    assert ten.loss_pct == pytest.approx(ten.loss / 100_000 * 100)
    # A's worst gap is -10%: 5% past the stop, twice the planned loss.
    assert by["A"].worst_gap_pct == pytest.approx(-10)
    assert by["A"].planned_loss == pytest.approx(0.05 * va)
    assert by["A"].gap_loss == pytest.approx(0.10 * va)
    assert by["A"].beyond_stop == pytest.approx(0.05 * va)
    assert by["B"].planned_loss is None and any("No stop for B" in n for n in r.notes)
    # A and B move together exactly.
    assert r.avg_correlation == pytest.approx(1.0)
    assert [(p.a, p.b) for p in r.high_pairs] == [("A", "B")]
    # VaR over 120 sessions: every down day loses 2% of A and 0.5% of B.
    assert r.var_sessions == 120
    assert r.var95 == pytest.approx(0.02 * va + 0.005 * vb)
    assert r.worst_day_loss == pytest.approx(0.02 * va + 0.005 * vb)


def test_report_says_what_it_lacks():
    index = _series(IDX[:30], 1000)
    a = _series([2 * r for r in IDX[:30]])
    r = risk_report([Position("A", 10, a.closes[-1], None)], {"A": a}, index, 50_000)
    assert r.var95 is None and r.var_sessions == 0 and r.book_beta == pytest.approx(1.0)
    assert any("VaR needs 100 sessions" in n for n in r.notes)
    assert any("Beta taken as 1 for A" in n for n in r.notes)
    empty = risk_report([], {}, None, 50_000)
    assert empty.stocks == [] and empty.var95 is None and empty.shocks[0].loss == 0


@requires_db
def test_portfolio_risk_route(empty_session):
    s = empty_session
    _seed(s)
    day = str(next_session(CAL, DAYS[-1]))
    client = TestClient(app)
    for ticker, shares in (("UP", 100), ("SPLITCO", 50)):
        price = Decimal(f"{_adjusted(ticker)[280]:.2f}")
        e = manual_entry(s, ticker, stop=(price * Decimal("0.9")).quantize(Decimal("0.01")))
        add_fill(s, e, DAYS[280], "buy", shares, price)
    r = client.get("/portfolio/risk", params={"day": day}).json()
    assert r["as_of"] == str(DAYS[-1]) and {x["ticker"] for x in r["stocks"]} == {"UP", "SPLITCO"}
    by = {x["ticker"]: x for x in r["stocks"]}
    # SPLITCO's 2:1 split halved its raw price; adjusted, there is no gap and no loss day.
    assert by["SPLITCO"]["worst_gap_pct"] > -1
    assert r["worst_day_loss"] is not None and r["worst_day_loss"] < 0.01 * r["value"]
    assert r["var_sessions"] == 299 and r["beta_sessions"] == 250
    assert [x["index_move_pct"] for x in r["shocks"]] == [-5, -10, -20]


@requires_db
def test_stock_candles_carry_the_index(empty_session):
    _seed(empty_session)
    stock = TestClient(app).get("/stocks/SPLITCO", params={"sessions": 120}).json()
    candles = stock["candles"]
    assert len(candles) == 120 and all(c["nifty500"] is not None for c in candles)
    # Adjusted for the split, so the line the chart draws against the index has no step.
    closes = [float(c["close"]) for c in candles]
    assert max(b / a for a, b in zip(closes, closes[1:], strict=False)) < 1.01
