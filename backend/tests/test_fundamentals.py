"""Quarterly results: NSE's Financial Results CSV, the XBRL filings (real samples) and the
fundamental score."""

import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.data.fundamentals import (
    IST,
    ResultsFormatError,
    integrated_quarter_ends,
    name_key,
    parse_xbrl,
    read_integrated_list,
    read_results_csv,
    symbols_by_name,
)
from app.fundamentals import job
from app.fundamentals.job import choose
from app.fundamentals.score import Quarter, fund_score, pe_ratio, ttm

FIXTURES = Path(__file__).parent / "fixtures"


def test_reads_the_csv_nse_offers():
    refs = read_results_csv((FIXTURES / "nse_financial_results.csv").read_text("utf-8-sig"))
    assert len(refs) == 9
    ril = next(r for r in refs if r.company == "Reliance Industries Limited" and r.consolidated)
    assert ril.period_end == date(2024, 12, 31) and not ril.audited
    assert ril.standard == "Ind-AS New" and ril.relating_to == "Third Quarter"
    assert ril.xbrl_url and ril.xbrl_url.endswith("INDAS_117297_1348248_16012025081520.xml")
    assert ril.disseminated_at == datetime(2025, 1, 16, 20, 15, 46, tzinfo=IST)
    videocon = next(r for r in refs if r.company.startswith("Videocon"))
    assert videocon.xbrl_url is None  # NSE lists no XBRL for it


def test_other_csvs_are_refused():
    with pytest.raises(ResultsFormatError, match="Financial Results CSV"):
        read_results_csv('"SYMBOL","PURPOSE"\n"TCS","Results"\n')


def test_reliance_q3_fy25_consolidated():
    r = parse_xbrl((FIXTURES / "xbrl_reliance_2024q3.xml").read_bytes())
    assert (r.symbol, r.period_start, r.period_end) == (
        "RELIANCE",
        date(2024, 10, 1),
        date(2024, 12, 31),
    )
    assert r.consolidated
    # As reported: revenue ₹2,43,865 crore, profit to owners ₹18,540 crore, EPS ₹13.70.
    assert r.numbers["revenue"] == Decimal("2438650000000.00")
    assert r.numbers["profit_to_owners"] == Decimal("185400000000.00")
    assert r.numbers["eps"] == Decimal("13.70")
    assert r.numbers["paid_up_capital"] / r.numbers["face_value"] == 13_532_000_000


def test_bank_form():
    r = parse_xbrl((FIXTURES / "xbrl_sbi_2024q3.xml").read_bytes())
    assert (r.symbol, r.isin) == ("SBIN", "INE062A01020")
    assert r.numbers["finance_costs"] == r.facts["InterestExpended"]  # interest paid
    assert r.numbers["profit_to_owners"] == Decimal("188531600000.00")  # ₹18,853 crore
    assert r.numbers["eps"] == Decimal("21.12")


def test_older_form_without_the_quarter_start():
    # Banks' 2019 form gives the quarter's end but not its start.
    r = parse_xbrl((FIXTURES / "xbrl_sbi_2019q1_old_form.xml").read_bytes())
    assert (r.period_start, r.period_end) == (date(2019, 4, 1), date(2019, 6, 30))
    assert r.numbers["net_profit"] == Decimal("23122000000.00")  # ₹2,312 crore
    assert r.numbers["eps"] == Decimal("2.59")


def test_filing_without_dates_takes_the_quarter_from_the_list():
    content = (FIXTURES / "xbrl_sbi_2019q1_old_form.xml").read_bytes()
    content = content.replace(b"DateOfEndOfReportingPeriod", b"Removed")
    with pytest.raises(ResultsFormatError):
        parse_xbrl(content)
    r = parse_xbrl(content, date(2019, 6, 30))
    assert (r.period_start, r.period_end) == (date(2019, 4, 1), date(2019, 6, 30))
    r = parse_xbrl(content, date(2018, 12, 31))
    assert r.period_start == date(2018, 10, 1)


def test_not_xbrl():
    with pytest.raises(ResultsFormatError):
        parse_xbrl(b"<html>Access Denied</html>")


def test_name_matching():
    assert name_key("V.S.T Tillers Tractors Limited") == name_key("V.S.T. TILLERS TRACTORS LTD")
    assert name_key("Larsen & Toubro Limited") == "LARSENANDTOUBRO"
    assert name_key("The Ramco Cements Limited") == name_key("Ramco Cements Ltd")
    found = symbols_by_name([("A", "Same Name Ltd"), ("B", "Same Name Limited"), ("C", "Other")])
    assert found == {"OTHER": "C"}  # two stocks share the name: neither is guessed


def test_consolidated_preferred(tmp_path):
    refs = read_results_csv((FIXTURES / "nse_financial_results.csv").read_text("utf-8-sig"))
    chosen = choose(refs)
    by_company = {r.company: r for r in chosen if r.company.startswith("Reliance")}
    assert by_company["Reliance Industries Limited"].consolidated
    assert all(not r.consolidated for r in chosen if r.company.startswith("Videocon"))


# The score ------------------------------------------------------------------------


def _quarters(n, revenue=100.0, profit=10.0, grow=0.05, start=date(2021, 6, 30), **kw):
    out = []
    end = start
    for i in range(n):
        g = (1 + grow) ** i
        out.append(
            Quarter(
                period_end=end,
                disseminated_at=datetime.combine(end + timedelta(days=40), datetime.min.time()),
                consolidated=True,
                revenue=revenue * g,
                net_profit=profit * g,
                eps=profit * g / 10,
                finance_costs=1.0,
                depreciation=2.0,
                profit_before_tax=profit * g * 1.3,
                other_income=0.5,
                shares=10.0,
                **kw,
            )
        )
        month = end.month + 3
        year = end.year + (month > 12)
        month = month - 12 if month > 12 else month
        end = date(year, month, {3: 31, 6: 30, 9: 30, 12: 31}[month])
    return out


def test_ttm_needs_four_consecutive_quarters():
    q = _quarters(8)
    assert ttm(q, "revenue") == pytest.approx(sum(x.revenue for x in q[-4:]))
    assert ttm(q[:3], "revenue") is None
    assert ttm([*q[:2], *q[3:5]], "revenue") is None  # a quarter missing


def test_pe_uses_the_share_count():
    q = _quarters(4, profit=10.0, grow=0.0)
    assert pe_ratio(q, price=20.0) == pytest.approx(20 * 10 / 40)


def test_a_steady_grower_scores_high_and_a_loss_maker_low():
    good = _quarters(16, grow=0.05)  # about 22% a year
    as_of = good[-1].period_end + timedelta(days=50)
    s = fund_score(good, as_of, price=50.0, pe_history=[30.0] * 12)
    assert s.score is not None and s.score >= 80
    assert s.facts["sales_growth"] == pytest.approx(1.05**4 - 1)
    bad = _quarters(16, profit=-5.0, grow=0.0)
    b = fund_score(bad, as_of, price=50.0)
    assert b.score is not None and b.score < 30
    assert b.facts["pe"] is None


def test_too_little_or_stale_data_is_no_score():
    q = _quarters(3)
    assert fund_score(q, q[-1].period_end, 10.0).score is None
    q = _quarters(8)
    stale = fund_score(q, q[-1].period_end + timedelta(days=300), 10.0)
    assert stale.score is None and "stale" in stale.notes[0]


def test_qualified_audit_opinion_is_a_hard_reject():
    q = _quarters(8, audit_opinion="Qualified opinion: inventories not verified")
    s = fund_score(q, q[-1].period_end + timedelta(days=50), 10.0)
    assert s.rejected and "Qualified" in s.rejected
    ok = _quarters(8, audit_opinion="Unmodified opinion")
    assert fund_score(ok, ok[-1].period_end + timedelta(days=50), 10.0).rejected is None


def test_valuation_against_own_history():
    q = _quarters(12, grow=0.0)
    as_of = q[-1].period_end + timedelta(days=50)
    cheap = fund_score(q, as_of, price=10.0, pe_history=[20.0 + i for i in range(10)])
    dear = fund_score(q, as_of, price=100.0, pe_history=[5.0 + i for i in range(10)])
    assert cheap.valuation == 30 and dear.valuation == 0


def test_a_filing_in_the_wrong_units_gets_no_pe():
    q = _quarters(8, grow=0.0)
    assert pe_ratio(q, 20.0) is not None
    wrong = [*q[:-1], replace(q[-1], eps=q[-1].eps * 10)]  # EPS filed 10 times too big
    assert pe_ratio(wrong, 20.0) is None
    s = fund_score(wrong, wrong[-1].period_end + timedelta(days=50), 20.0)
    assert s.valuation == 0 and any("wrong units" in n for n in s.notes)


def test_reads_the_integrated_filing_list():
    # NSE's Financial Results list ends at the December 2024 quarter; later quarters are
    # in the "Integrated Filing - Financials" list.
    refs, total = read_integrated_list((FIXTURES / "nse_integrated_filings.json").read_bytes())
    assert total == 4 and len(refs) == 4
    gammon, revision, nbfc, bank = refs
    assert gammon.company == "Gammon India Limited" and gammon.consolidated
    assert gammon.period_end == date(2025, 9, 30) and not gammon.audited
    assert gammon.xbrl_url and gammon.xbrl_url.endswith("_WEB.xml")
    # The later of the broadcast and creation times: never known early.
    assert gammon.disseminated_at == datetime(2026, 11, 2, 11, 24, 42, tzinfo=IST)
    # A revision has no broadcast time: it is known from when it was created.
    assert revision.relating_to == "Revision"
    assert revision.disseminated_at == datetime(2026, 11, 5, 10, 34, 27, tzinfo=IST)
    # `quarter_of` scores interest cover only for "Ind-AS New" filers.
    assert [r.standard for r in refs] == ["Ind-AS New", "NBFC-IND", "NBFC-IND", "Non-Ind-AS"]


def test_other_json_is_refused_as_an_integrated_list():
    with pytest.raises(ResultsFormatError, match="integrated filing"):
        read_integrated_list(b'{"rows": []}')
    with pytest.raises(ResultsFormatError, match="integrated filing"):
        read_integrated_list(b"<html>Access Denied</html>")


def test_integrated_quarter_ends():
    assert integrated_quarter_ends(date(2020, 1, 1), date(2025, 3, 31)) == []
    assert integrated_quarter_ends(date(2020, 1, 1), date(2025, 10, 5)) == [
        date(2025, 3, 31),
        date(2025, 6, 30),
        date(2025, 9, 30),
    ]
    assert integrated_quarter_ends(date(2026, 6, 30), date(2026, 11, 11)) == [
        date(2026, 6, 30),
        date(2026, 9, 30),
    ]


def test_integrated_filing_xbrl_parses_like_the_old_form():
    r = parse_xbrl((FIXTURES / "xbrl_integrated_airolam_2025q2.xml").read_bytes())
    assert (r.symbol, r.period_start, r.period_end) == (
        "AIROLAM",
        date(2025, 7, 1),
        date(2025, 9, 30),
    )
    assert r.numbers["revenue"] == Decimal("625268000")
    assert r.numbers["net_profit"] == Decimal("26941000")


def test_fetch_integrated_pages_through_each_quarter(monkeypatch):
    page = json.loads((FIXTURES / "nse_integrated_filings.json").read_text())
    calls = []

    def get(url, params):
        calls.append(params)
        rows = page["data"][:2] if params["page"] == "1" else page["data"][2:3]
        return json.dumps({"data": rows, "totalCount": 3}).encode()

    monkeypatch.setattr(job, "INTEGRATED_PAGE", 2)
    refs = job.fetch_integrated(get, [date(2025, 9, 30)])
    assert len(refs) == 3
    assert [c["page"] for c in calls] == ["1", "2"]
    assert calls[0]["period_ended"] == "30-Sep-2025"
    assert calls[0]["type"] == "Integrated Filing- Financials"
