"""The real account's daily equity curve (app/portfolio/equity.py), hand-worked."""

from datetime import date
from decimal import Decimal

from app.journal.calc import Fill
from app.portfolio.calc import account_state, realised_sales
from app.portfolio.equity import equity_curve

D = Decimal
D1, D2, D3, D4 = (date(2026, 10, d) for d in (19, 20, 21, 22))
CAPITAL = D(100000)


def test_equity_curve_hand_worked() -> None:
    a = [Fill(D1, "buy", 10, D(100), D(10)), Fill(D3, "sell", 10, D(120))]  # cost 101 a share
    b = [Fill(D2, "buy", 4, D(50))]
    closes = {"A": {D1: D(105), D2: D(130), D3: D(120), D4: D(125)}, "B": {D1: D(48), D3: D(55)}}
    index = {D1: D(1000), D2: D(1010), D4: D(1100)}
    c = equity_curve(CAPITAL, [("A", a), ("B", b)], closes, [D1, D2, D3, D4], index)
    # d1: A 10 x 105 - 1,010 = +40. d2: A +290, B 4 x 48 (d1's close, kept) - 200 = -8.
    # d3: A sold, 10 x (120 - 101) = +190 realised; B 4 x 55 - 200 = +20. d4: as d3.
    assert [p.equity for p in c.points] == [D("100040.00"), D("100282.00"), D("100210.00"),
                                             D("100210.00")]  # fmt: skip
    assert [p.drawdown_pct for p in c.points] == [D(0), D(0), D("0.07"), D("0.07")]
    assert c.peak == D("100282.00") and c.max_drawdown_pct == D("0.07")
    assert c.return_pct == D("0.21")
    assert [p.index for p in c.points] == [D("100000.00"), D("101000.00"), None, D("110000.00")]
    assert c.index_return_pct == D("10.00")

    # The curve's peak was open profit given back before selling: the account sees it.
    sales = realised_sales("A", a)
    realised_only = account_state(CAPITAL, sales, [D1, D2], [], D4)
    assert realised_only.peak == D("100190.00")
    with_curve = account_state(CAPITAL, sales, [D1, D2], [], D4, c.peak)
    assert with_curve.peak == D("100282.00") and with_curve.drawdown_pct == D("0.09")


def test_no_buys_no_curve() -> None:
    c = equity_curve(CAPITAL, [], {}, [D1, D2])
    assert c.points == [] and c.peak is None and c.return_pct is None


def test_curve_starts_at_the_first_buy() -> None:
    c = equity_curve(
        CAPITAL, [("A", [Fill(D3, "buy", 1, D(10))])], {"A": {D3: D(11)}}, [D1, D2, D3]
    )
    assert [p.day for p in c.points] == [D3] and c.points[0].equity == D("100001.00")
    assert c.points[0].index is None and c.index_return_pct is None
