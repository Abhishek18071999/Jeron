"""Portfolio maths (app.portfolio.calc): open risk, heat, give-back, sector exposure."""

from datetime import date
from decimal import Decimal

from app.journal.calc import Fill
from app.portfolio.calc import (
    UNKNOWN_SECTOR,
    Holding,
    Sale,
    long_term_exemption,
    realised_sales,
    sell_now_or_later,
    tax_notes,
    totals,
)


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
    # The whole ₹1.25 lakh exemption is left: no tax after the mark.
    assert "₹5,000 gain, selling now costs about ₹1,000 in tax (20% short-term)" in note
    assert "selling after that about ₹0 (12.5% above the ₹125,000 of this financial" in note
    assert "₹1,000 less" in note
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


def test_tax_notes_use_the_exemption_left_this_year():
    h = _h(close="1200", shares=200)  # ₹2,20,000 gain
    (note,) = tax_notes([h], date(2027, 8, 1), Decimal("25000"))
    # Now: 20% of 2,20,000 = 44,000. After: 12.5% of (2,20,000 - 25,000) = 24,375.
    assert "about ₹44,000 in tax" in note
    assert "about ₹24,375 (12.5% above the ₹25,000 of this financial year's" in note
    assert "₹19,625 less" in note


def test_sell_later_in_the_next_financial_year_gets_a_new_exemption():
    gain = Decimal("200000")
    # The mark on 2 Apr 2027 is in FY 2027-28: the exemption used in 2026-27 doesn't count.
    now, later, exempt = sell_now_or_later(gain, date(2027, 3, 1), date(2027, 4, 2), Decimal(0))
    assert (now, later, exempt) == (Decimal("40000"), Decimal("9375"), Decimal("125000"))
    now, later, exempt = sell_now_or_later(gain, date(2027, 5, 1), date(2027, 6, 2), Decimal(0))
    assert (later, exempt) == (Decimal("25000"), Decimal(0))


def test_realised_sales_match_lots_first_in_first_out():
    fills = [
        Fill(date(2025, 1, 10), "buy", 10, Decimal("100"), Decimal("10")),  # ₹101 a share
        Fill(date(2025, 6, 10), "buy", 10, Decimal("200")),
        Fill(date(2026, 2, 1), "sell", 15, Decimal("300"), Decimal("15")),  # ₹299 net
    ]
    first, second = realised_sales("A", fills)
    assert (first.shares, first.gain, first.held_days, first.long_term) == (
        10,
        Decimal("1980.00"),
        387,
        True,
    )
    assert (second.shares, second.gain, second.long_term) == (5, Decimal("495.00"), False)
    # Nothing sold: no sales.
    assert realised_sales("A", fills[:2]) == []


def _sale(day, gain, days):
    return Sale("A", day, 1, Decimal(gain), days)


def test_long_term_exemption_used_this_financial_year():
    sales = [
        _sale(date(2026, 3, 20), "90000", 400),  # last financial year: not counted
        _sale(date(2026, 5, 1), "80000", 400),
        _sale(date(2026, 7, 1), "-10000", 400),
        _sale(date(2026, 8, 1), "-5000", 100),  # a short-term loss is set off first
        _sale(date(2026, 9, 1), "30000", 500),
    ]
    e = long_term_exemption(sales, date(2026, 10, 25))
    assert (e.year, e.label) == (2026, "2026-27")
    assert (e.long_term, e.short_term) == (Decimal("100000.00"), Decimal("-5000.00"))
    assert (e.used, e.left) == (Decimal("95000.00"), Decimal("30000.00"))
    assert e.line.startswith("FY 2026-27: ₹95,000 of the ₹125,000 long-term exemption used")
    big = long_term_exemption([*sales, _sale(date(2026, 10, 1), "90000", 800)], date(2026, 10, 25))
    assert big.left == 0 and "used up" in big.line
    # A sale after the day isn't counted yet.
    assert long_term_exemption(sales, date(2026, 6, 1)).used == Decimal("80000.00")


def test_totals_carry_the_exemption_and_pass_what_is_left_to_the_notes():
    holdings = [_h(close="1200", shares=200)]
    args = (holdings, Decimal("10000000"), Decimal(5), Decimal(6), Decimal(30))
    assert totals(*args).exemption is None
    t = totals(*args, as_of=date(2027, 8, 1), sales=[_sale(date(2027, 5, 1), "100000", 400)])
    assert t.exemption is not None and t.exemption.left == Decimal("25000.00")
    assert "₹25,000 of this financial year's" in t.tax_notes[0]
