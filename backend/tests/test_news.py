# ruff: noqa: E501 - lines copied from NSE files
from datetime import date

from app.data.news import parse_pr_announcements

AN_2026 = """COMPANY NAME    SYMBOL    : ANNOUNCEMENTS
Graphite India Limited GRAPHITE : Credit Rating- Revision GRAPHITE : Graphite India Limited has informed the Exchange about Credit Rating
Deccan Transcon Leasing Limited DECCANTRAN : Resignation of Statutory Auditor DECCANTRAN : Deccan Transcon Leasing Limited has informed
the Exchange about Resignation of Statutory Auditor
UTI MF - UTI Fund - DG    UTIFUNDDG : Declaration of NAV UTIFUNDDG : UTI AMC has informed the Exchange that the NAV is Rs. 11.
Asahi India Glass Limited ASAHIINDIA : Copy of Newspaper Publication ASAHIINDIA : Asahi India Glass Limited has informed the Exchange
Graphite India Limited GRAPHITE : Credit Rating- Revision GRAPHITE : Graphite India Limited has informed the Exchange about Credit Rating
"""

AN_2016 = """COMPANY NAME    SYMBOL    : ANNOUNCEMENTS
HDFC Bank Limited    HDFCBANK : HDUpdatesDFC Bank Limited has informed the Exchange regarding an interview.
Jamna Auto Industries Limited    JAMNAAUTO : JTrading WindowJamna Auto Industries Limited has informed the Exchange
ICICI Prud MF - Plan C - DP-CO    IPRU8782   : Declaration of NAV ICICI Prudential AMC has informed the Exchange that the Net Asset Value is Rs. 11.6.
Some Limited    SOMECO : Something with no known subject.
"""


def test_new_format_subject_noise_and_duplicates():
    items = parse_pr_announcements(AN_2026, date(2026, 8, 31))
    assert [(a.symbol, a.subject) for a in items] == [
        ("GRAPHITE", "Credit Rating- Revision"),
        ("DECCANTRAN", "Resignation of Statutory Auditor"),
    ]
    assert items[1].text.endswith("about Resignation of Statutory Auditor")
    assert items[0].day == date(2026, 8, 31)


def test_old_format_spliced_subjects():
    items = parse_pr_announcements(AN_2016, date(2016, 10, 19))
    assert [(a.symbol, a.subject) for a in items] == [
        ("HDFCBANK", "Updates"),
        ("SOMECO", None),
    ]
    assert items[0].text.startswith("HDFC Bank Limited has informed the Exchange")
