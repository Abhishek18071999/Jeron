"""Portfolio maths (app.portfolio.calc): open risk, heat, give-back, sector exposure."""

from datetime import date
from decimal import Decimal

from app.portfolio.calc import UNKNOWN_SECTOR, Holding, totals


def _h(ticker="A", sector="IT", shares=100, entry="100", close="110", stop="95", pnl="1000"):
    return Holding(
        entry_id=1,
        ticker=ticker,
        strategy_key=None,
        sector=sector,
        shares=shares,
        avg_entry=Decimal(entry),
        last_close=None if close is None else Decimal(close),
        last_close_date=date(2026, 10, 1),
        stop=None if stop is None else Decimal(stop),
        initial_stop=None if stop is None else Decimal(stop),
        pnl=None if pnl is None else Decimal(pnl),
        r_multiple=None,
        first_date=date(2026, 9, 1),
        sessions_held=20,
        action="hold",
        reason="stop",
    )


def _totals(holdings, capital="100000"):
    return totals(holdings, Decimal(capital), Decimal(5), Decimal(6), Decimal(30))


def test_one_position():
    h = _h()
    assert h.value == Decimal("11000.00")
    assert h.open_risk == Decimal("500.00")  # (100 - 95) x 100
    assert h.give_back == Decimal("1500.00")  # (110 - 95) x 100
    assert h.stop_distance_pct == Decimal("13.64")
    assert h.days_held(date(2026, 10, 1)) == 30


def test_stop_at_breakeven_or_above_adds_no_risk():
    h = _h(stop="105")
    assert h.open_risk == Decimal("0.00") and h.give_back == Decimal("500.00")
    below = _h(close="90", stop="95")
    assert below.give_back == Decimal("0.00") and below.stop_distance_pct == Decimal("-5.56")


def test_no_stop_or_no_close():
    h = _h(stop=None, close=None, pnl=None)
    assert h.open_risk is None and h.give_back is None and h.stop_distance_pct is None
    assert h.value is None
    t = _totals([h])
    assert t.without_stop == 1 and t.open_risk == Decimal("0.00")
    assert any("without a stop" in w for w in t.warnings)


def test_heat_against_the_limits():
    # 5,000 at risk on 100,000 = 5%: the warning level.
    t = _totals([_h(shares=1000, close="100", entry="100", stop="95", sector=None)])
    assert t.heat_pct == Decimal("5.00")
    assert t.warnings == [
        "Portfolio heat 5.0% is at the 5% warning level (new entries blocked above 6%)."
    ]
    t = _totals([_h(shares=1300, close="100", entry="100", stop="95", sector=None)])
    assert "above 6%: no new entries" in t.warnings[0]
    assert _totals([_h()]).warnings == []


def test_sector_exposure_and_cap():
    t = _totals(
        [
            _h("A", "IT", close="200", shares=100),  # 20,000
            _h("B", "IT", close="150", shares=100),  # 15,000
            _h("C", "Banks", close="100", shares=100),  # 10,000
            _h("D", None, close="400", shares=100),  # 40,000, not capped
        ]
    )
    assert [(s.sector, s.positions, s.value) for s in t.sectors] == [
        (UNKNOWN_SECTOR, 1, Decimal("40000.00")),
        ("IT", 2, Decimal("35000.00")),
        ("Banks", 1, Decimal("10000.00")),
    ]
    it = t.sectors[1]
    assert it.pct_of_capital == Decimal("35.00") and it.over_cap
    assert not t.sectors[0].over_cap
    assert t.warnings == ["IT is 35.0% of capital, above the 30% sector cap."]
    assert t.positions == 4 and t.value == Decimal("85000.00") and t.pnl == Decimal("4000.00")
