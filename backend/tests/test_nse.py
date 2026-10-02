from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.data.http import FetchError, NotPublishedError
from app.data.nse import (
    BhavcopyError,
    NseArchive,
    bhavcopy_url,
    parse_bhavcopy,
    parse_pr_corporate_actions,
    parse_purpose,
    pr_url,
)
from app.enums import CorporateActionType
from tests.helpers import LEGACY_HEADER, pr_zip, udiff_row, udiff_zip, zipped

FIXTURES = Path(__file__).parent / "fixtures"

# Real rows from NSE's files (RELIANCE's 1:1 bonus went ex on 2024-10-28).
UDIFF_2024_10_28 = (FIXTURES / "udiff_2024-10-28.csv").read_text()

LEGACY_2016_01_04 = f"""{LEGACY_HEADER}
INFY,EQ,1099.95,1102.45,1076.05,1078.9,1078.5,1105.25,1987681,2162230783.75,04-JAN-2016,53877,INE009A01021,
SBIN,EQ,226.95,226.95,220.05,220.7,221.1,227.8,14092071,3139744222.2,04-JAN-2016,113875,INE062A01020,
SBIN,N2,10940.86,11150,10940.86,11150,11150,11206.25,4,44181.72,04-JAN-2016,2,INE062A08025,
"""


def test_urls_switch_format_on_udiff_start():
    assert bhavcopy_url(date(2024, 7, 5)).endswith(
        "/content/historical/EQUITIES/2024/JUL/cm05JUL2024bhav.csv.zip"
    )
    assert bhavcopy_url(date(2024, 7, 8)).endswith(
        "/content/cm/BhavCopy_NSE_CM_0_0_0_20240708_F_0000.csv.zip"
    )
    assert pr_url(date(2024, 10, 25)).endswith("/archives/equities/bhavcopy/pr/PR251024.zip")


def test_parse_udiff_keeps_mainboard_equities_only():
    day = date(2024, 10, 28)
    parsed = parse_bhavcopy(zipped("x.csv", UDIFF_2024_10_28), day)
    assert [b.symbol for b in parsed.bars] == ["DRREDDY", "RELIANCE"]
    rel = parsed.bars[1]
    assert rel.close == Decimal("1334.35")
    assert rel.prev_close == Decimal("2655.70")  # NSE doesn't adjust prev close
    assert rel.volume == 10824350
    assert rel.turnover == Decimal("14479733719.25")
    assert rel.isin == "INE002A01018"
    assert rel.series == "EQ"


def test_parse_legacy():
    parsed = parse_bhavcopy(zipped("cm04JAN2016bhav.csv", LEGACY_2016_01_04), date(2016, 1, 4))
    assert [(b.symbol, b.close, b.volume) for b in parsed.bars] == [
        ("INFY", Decimal("1078.9"), 1987681),
        ("SBIN", Decimal("220.7"), 14092071),
    ]


def test_file_for_a_different_day_is_rejected():
    with pytest.raises(BhavcopyError, match="rows dated"):
        parse_bhavcopy(zipped("x.csv", UDIFF_2024_10_28), date(2024, 10, 29))


def test_rights_entitlements_are_skipped():
    day = date(2024, 10, 28)
    content = udiff_zip(day, [udiff_row(day, "DUCON-RE1", 1, 1, 1, 1, 1, 100)])
    parsed = parse_bhavcopy(content, day)
    assert parsed.bars == [] and parsed.rejected == []


def test_impossible_rows_are_rejected_not_stored():
    day = date(2024, 10, 28)
    content = udiff_zip(day, [udiff_row(day, "BAD", 10, 9, 8, 11, 10, 100)])
    parsed = parse_bhavcopy(content, day)
    assert parsed.bars == []
    assert parsed.rejected[0][0] == "BAD"


@pytest.mark.parametrize(
    ("purpose", "expected"),
    [
        ("BONUS 1:1", [("bonus", "2", "1", None)]),
        ("BONUS 1:2", [("bonus", "3", "2", None)]),
        ("BONUS 2:1", [("bonus", "3", "1", None)]),
        ("FV SPLT FRM RS 5 TO RE 1", [("split", "5", "1", None)]),
        ("FVSPLT FRM RS 10 TO RS 2", [("split", "10", "2", None)]),
        (
            "FACE VALUE SPLIT (SUB-DIVISION) - FROM RS 10/- PER SHARE TO RE 1/- PER SHARE",
            [("split", "10", "1", None)],
        ),
        ("CONSOLIDATION FROM RS 1 TO RS 10", [("split", "1", "10", None)]),
        ("INTDIV - RS 21 PER SH", [("dividend", None, None, "21")]),
        ("DIV - RE 0.30 PER SH", [("dividend", None, None, "0.30")]),
        ("DIV/SPDV - RS 2 & 1", [("dividend", None, None, "3")]),
        ("INTDVSPDVRS 7.50 & 86.50", [("dividend", None, None, "94.00")]),
        ("FIN DIV RS 6+SPL DIV RS 4", [("dividend", None, None, "10")]),
        ("INTERIM DIVIDEND", [("dividend", None, None, None)]),
        ("DIVIDEND 50%", [("dividend", None, None, None)]),
        (
            "BONUS 1:1 / DIV RS 2",
            [("bonus", "2", "1", None), ("dividend", None, None, "2")],
        ),
        ("RGHTS 119:758 PRM RS 218", [("rights", "119", "758", None)]),
        ("RIGHTS- 7CCPS/ 7WRNTS:40", [("rights", None, None, None)]),
        ("DEMERGER", [("other", None, None, None)]),
        ("ANNUAL GENERAL MEETING", []),
        ("BUY BACK", []),
        ("INTEREST PAYMENT", []),
    ],
)
def test_parse_purpose(purpose, expected):
    actions = parse_purpose("X", date(2024, 1, 1), purpose)
    got = [
        (
            a.action_type.value,
            None if a.ratio_new is None else str(a.ratio_new),
            None if a.ratio_old is None else str(a.ratio_old),
            None if a.amount is None else str(a.amount),
        )
        for a in actions
    ]
    assert got == expected


def test_parse_pr_corporate_actions_both_date_formats_and_dedupes():
    content = pr_zip(
        date(2024, 10, 25),
        [
            "EQ,RELIANCE,Reliance Industries Ltd,28/10/2024, , ,28/10/2024, , ,BONUS 1:1       ",
            "BE,RELIANCE,RELIANCE IND - DEPO SETT.,28/10/2024, , ,28/10/2024, , ,BONUS 1:1",
            "EQ,LEXUS,Lexus Granito (India) Ltd, ,23/10/2024,25/10/2024,22/10/2024, , ,EGM",
            "N0,12AFIL27A,AFIL 12% 2027,2026-09-30,,,2026-09-30,,,INTEREST PAYMENT",
            "EQ,INFY,Infosys Limited,2024-10-29,,,2024-10-29,,,INTDIV - RS 21 PER SH",
            "EQ,JUBLINDS,Jubilant Industries Ltd,28/10/2024, , , , , ,MERGER",
        ],
    )
    actions = parse_pr_corporate_actions(content)
    assert [(a.symbol, a.ex_date, a.action_type) for a in actions] == [
        ("RELIANCE", date(2024, 10, 28), CorporateActionType.BONUS),
        ("INFY", date(2024, 10, 29), CorporateActionType.DIVIDEND),
    ]


class FakeFetcher:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, params=None):
        self.calls.append(url)
        result = self.responses[url]
        if isinstance(result, Exception):
            raise result
        return result


def test_archive_caches_files_and_settled_404s(tmp_path: Path):
    old, recent = date(2024, 10, 25), date(2024, 10, 28)
    fetcher = FakeFetcher(
        {
            bhavcopy_url(old): b"zip-bytes",
            bhavcopy_url(recent): NotPublishedError("404"),
            pr_url(old): FetchError("blocked"),
        }
    )
    archive = NseArchive(fetcher, tmp_path, settle_days=3)  # type: ignore[arg-type]
    today = date(2024, 10, 29)
    assert archive.bhavcopy(old, today) == b"zip-bytes"
    assert archive.bhavcopy(old, today) == b"zip-bytes"
    assert archive.bhavcopy(recent, today) is None
    assert archive.bhavcopy(recent, today) is None
    # The cached file is served from disk; the recent 404 is asked again.
    assert fetcher.calls.count(bhavcopy_url(old)) == 1
    assert fetcher.calls.count(bhavcopy_url(recent)) == 2
    with pytest.raises(FetchError):
        archive.pr_bundle(old, today)
