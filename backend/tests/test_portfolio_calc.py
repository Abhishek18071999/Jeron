"""Portfolio maths (app.portfolio.calc): open risk, heat, give-back, sector exposure."""

from datetime import date
from decimal import Decimal

from app.portfolio.calc import UNKNOWN_SECTOR, Holding, tax_notes, totals


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


def test_idle_cash_is_flagged_both_ways():
    # 100 shares at 100 = 10,000 invested; 20,000 of signals to buy at the next open.
    t = totals([_h()], Decimal("100000"), Decimal(5), Decimal(6), Decimal(30), Decimal("20000"))
    assert (t.invested, t.pending_cost, t.idle_cash) == (
        Decimal("10000.00"),
        Decimal("20000.00"),
        Decimal("70000.00"),
    )
    assert t.cash_action is not None and t.cash_action.startswith("₹70,000 is idle: park it")
    small = totals([_h()], Decimal("50000"), Decimal(5), Decimal(6), Decimal(30), Decimal("1000"))
    assert small.cash_action is None  # 39,000 idle: under the line
    short = totals([_h()], Decimal("25000"), Decimal(5), Decimal(6), Decimal(30), Decimal("20000"))
    assert short.cash_action is not None
    assert short.cash_action.startswith("Open positions and the next session's signals need ₹5,000")


def test_idle_cash_can_go_to_an_index_fund():
    args = ([_h()], Decimal("100000"), Decimal(5), Decimal(6), Decimal(30))
    t = totals(*args, Decimal("20000"), True)
    assert t.cash_action is not None
    assert t.cash_action.startswith("₹70,000 is idle: park it in a Nifty 50 or Nifty 500")
    short = totals(
        [_h()], Decimal("25000"), Decimal(5), Decimal(6), Decimal(30), Decimal("20000"), True
    )
    assert short.cash_action is not None and "of the index fund" in short.cash_action


def test_tax_notes_flag_a_gain_about_to_turn_long_term():
    # Bought 1 Sep 2026: long-term (held more than 365 days) from 2 Sep 2027.
    h = _h(close="150")  # 100 shares, ₹5,000 gain
    assert tax_notes([h], date(2027, 6, 1)) == []  # 273 days: too early
    (note,) = tax_notes([h], date(2027, 8, 1))
    assert note.startswith("A becomes long-term on 02 Sep 2027 (in 32 days)")
    assert "₹5,000 gain is taxed at 12.5% instead of 20%, up to ₹375 less" in note
    assert tax_notes([h], date(2027, 9, 2)) == []  # already long-term
    assert tax_notes([_h(close="90")], date(2027, 8, 1)) == []  # a loss: nothing to wait for


def test_tax_notes_list_losses_before_the_financial_year_ends():
    loser = _h(close="80")  # ₹2,000 below cost
    assert tax_notes([loser], date(2027, 1, 15)) == []
    (note,) = tax_notes([loser], date(2027, 3, 10))
    assert note.startswith("A is ₹2,000 below cost.")
    assert tax_notes([_h(close="120")], date(2027, 3, 10)) == []


def test_totals_carry_the_tax_notes_when_given_a_day():
    args = ([_h(close="80")], Decimal("100000"), Decimal(5), Decimal(6), Decimal(30))
    assert totals(*args).tax_notes == []
    assert len(totals(*args, as_of=date(2027, 2, 1)).tax_notes) == 1
