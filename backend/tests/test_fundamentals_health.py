"""fundamentals-v2 (docs/plans/fundamentals-v2.md): the balance sheet and year-to-date
facts of the results XBRL, and ROE, ROCE, debt/equity, cash flow and EV/EBITDA."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.data.fundamentals import parse_xbrl
from app.fundamentals.health import BALANCE_STALE_DAYS, cash_flow_years, health
from tests.test_fundamentals import _quarters

FIXTURES = Path(__file__).parent / "fixtures"


def test_tcs_half_year_filing_has_the_balance_sheet_and_cash_flow():
    r = parse_xbrl((FIXTURES / "xbrl_tcs_2024q2.xml").read_bytes())
    assert (r.symbol, r.period_end, r.consolidated) == ("TCS", date(2024, 9, 30), True)
    # As reported on 30 September 2024: owners' equity ₹1,01,495 crore, cash ₹8,155
    # crore; operating cash flow ₹21,999 crore for the six months.
    assert r.balance["EquityAttributableToOwnersOfParent"] == Decimal("1014950000000.00")
    assert r.balance["CashAndCashEquivalents"] == Decimal("81550000000.00")
    assert r.ytd["CashFlowsFromUsedInOperatingActivities"] == Decimal("219990000000.00")
    # The quarter's own numbers are untouched: the six months' revenue is year to date.
    assert r.ytd["RevenueFromOperations"] > r.numbers["revenue"]
    assert "CashAndCashEquivalents" not in r.facts


def _with_balance(n=8, equity=100.0, debt=50.0, cash=10.0, **kw):
    q = _quarters(n, profit=10.0, grow=0.0, **kw)
    last = replace(q[-1], equity=equity, debt=debt, cash=cash)
    return [*q[:-1], last]


def test_returns_and_leverage():
    q = _with_balance()
    as_of = q[-1].period_end + timedelta(days=40)
    h = health(q, as_of, price=20.0)
    assert h.balance_sheet_as_of == q[-1].period_end
    profit = sum(x.net_profit for x in q[-4:])
    assert h.roe == pytest.approx(profit / 100)
    pbt = sum(x.profit_before_tax for x in q[-4:])
    assert h.roce == pytest.approx((pbt + 4 * 1.0) / 150)
    assert h.debt_equity == pytest.approx(0.5)
    ebitda = pbt + 4 * 1.0 + 4 * 2.0
    assert h.ev_ebitda == pytest.approx((20 * 10 + 50 - 10) / ebitda)


def test_a_stale_balance_sheet_is_unknown():
    q = _with_balance()
    h = health(q, q[-1].period_end + timedelta(days=BALANCE_STALE_DAYS + 1), price=20.0)
    assert h.roe is None and h.debt_equity is None and h.balance_sheet_as_of is None
    assert "over 400 days old" in h.notes[0]
    none = health(_quarters(8), date(2025, 1, 1), price=20.0)
    assert none.roe is None and "No balance sheet" in none.notes[0]


def test_banks_get_roe_only():
    q = [replace(x, financial=True) for x in _with_balance()]
    h = health(q, q[-1].period_end + timedelta(days=40), price=20.0)
    assert h.roe is not None
    assert h.roce is None and h.debt_equity is None and h.ev_ebitda is None
    assert any("Bank or NBFC" in n for n in h.notes)


def test_wrong_units_give_no_ratio():
    q = _with_balance()
    q[-1] = replace(q[-1], eps=q[-1].eps * 1000)  # EPS filed in the wrong units
    h = health(q, q[-1].period_end + timedelta(days=40), price=20.0)
    assert h.roe is None and h.roce is None and h.ev_ebitda is None


def _years(*ocf: float, financial: bool = False):
    """Quarters from March 2021 with an operating cash flow on each March."""
    q = _quarters(4 * len(ocf) + 1, profit=10.0, grow=0.0, financial=financial)
    out, march = [], iter(ocf)
    for x in q:
        out.append(replace(x, ocf_ytd=next(march, None)) if x.period_end.month == 3 else x)
    return out


def test_cash_flow_by_financial_year():
    q = _years(30.0, 35.0, 40.0)
    years = cash_flow_years(q)
    assert [y.operating_cash_flow for y in years][:3] == [40.0, 35.0, 30.0]
    assert all(y.year_end.month == 3 for y in years)
    to_march = [x.net_profit for x in q if x.period_end <= years[0].year_end]
    assert years[0].profit == pytest.approx(sum(to_march[-4:]))
    h = health(q, q[-1].period_end + timedelta(days=40), price=20.0)
    assert not h.warnings


def test_three_years_of_negative_cash_flow_is_a_warning():
    q = _years(-5.0, -3.0, -1.0)
    h = health(q, q[-1].period_end + timedelta(days=40), price=20.0)
    assert any("negative in each of the last three" in w for w in h.warnings)


def test_profit_not_turning_into_cash_is_a_warning():
    q = _years(30.0, 35.0, 5.0)  # the latest year's cash flow far under its profit
    h = health(q, q[-1].period_end + timedelta(days=40), price=20.0)
    assert any("under half the profit" in w for w in h.warnings)


def test_lenders_get_no_cash_flow_warning():
    q = _years(-5.0, -3.0, -1.0, financial=True)
    h = health(q, q[-1].period_end + timedelta(days=40), price=20.0)
    assert not h.warnings
    assert any("loans it makes" in n for n in h.notes)
