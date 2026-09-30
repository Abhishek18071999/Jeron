from datetime import date
from decimal import Decimal

from app.data.crosscheck import CloseComparison, CloseDiff
from app.data.provider import CorporateActionRecord
from app.data.quality import DayData, build_report
from app.enums import CorporateActionType, QualityStatus
from tests.helpers import bar

DAY = date(2024, 10, 28)


def checks(report):
    return {c.name: c for c in report.checks}


def clean_day(**overrides):
    values = dict(
        trade_date=DAY,
        file_status="ok",
        calendar_trading_day=True,
        bars=[
            bar("A", DAY, 100, 102, 99, 101, prev_close=100),
            bar("B", DAY, 50, 51, 49, 50, prev_close=50),
        ],
        previous_day_rows=2,
        recent_closes={"A": [Decimal(98), Decimal(99), Decimal(100), Decimal(100)]},
        close_comparison=CloseComparison(checked=2),
    )
    values.update(overrides)
    return DayData(**values)


def test_clean_day_passes():
    report = build_report(clean_day())
    assert report.status == QualityStatus.PASS
    assert report.reasons == []
    assert report.to_dict()["status"] == "pass"


def test_missing_trading_day_fails():
    report = build_report(DayData(DAY, "not_published", calendar_trading_day=True))
    assert report.status == QualityStatus.FAIL
    assert "no bhavcopy" in report.reasons[0]


def test_download_failure_fails():
    assert build_report(DayData(DAY, "not_fetched", None)).status == QualityStatus.FAIL


def test_holiday_passes():
    assert build_report(DayData(DAY, "not_published", None)).status == QualityStatus.PASS


def test_truncated_file_fails():
    report = build_report(clean_day(previous_day_rows=10))
    assert checks(report)["row_count"].status == QualityStatus.FAIL
    assert report.status == QualityStatus.FAIL


def test_big_move_without_action_warns_but_bonus_is_explained():
    bonus = CorporateActionRecord(
        "R", DAY, CorporateActionType.BONUS, Decimal(2), Decimal(1), raw_text="BONUS 1:1"
    )
    report = build_report(
        clean_day(
            bars=[
                bar("R", DAY, 1337, 1353, 1322.1, 1334.35, prev_close=2655.70),
                bar("J", DAY, 130, 130, 125, 126, prev_close=100),
            ],
            actions_today=[bonus],
        )
    )
    big = checks(report)["big_moves"]
    assert big.status == QualityStatus.WARN
    assert [i["symbol"] for i in big.items] == ["J"]


def test_move_on_unadjusted_scheme_is_listed_separately():
    demerger = CorporateActionRecord("H", DAY, CorporateActionType.OTHER, raw_text="DEMERGER")
    report = build_report(
        clean_day(bars=[bar("H", DAY, 60, 62, 58, 60, prev_close=100)], actions_today=[demerger])
    )
    big = checks(report)["big_moves"]
    assert "rights issue or scheme" in big.message
    assert big.items[0]["actions"] == "DEMERGER"


def test_stale_prices_warn():
    report = build_report(
        clean_day(recent_closes={"B": [Decimal(50)] * 4}, bars=[bar("B", DAY, 50, 50, 50, 50)])
    )
    assert checks(report)["stale_prices"].status == QualityStatus.WARN


def test_cross_check_mismatch_rates():
    few = CloseComparison(
        checked=100,
        mismatches=[CloseDiff("A", DAY, Decimal(100), Decimal(101), Decimal("1.00"))],
    )
    assert checks(build_report(clean_day(close_comparison=few)))["cross_check"].status == (
        QualityStatus.WARN
    )
    many = CloseComparison(
        checked=10,
        mismatches=[CloseDiff("A", DAY, Decimal(100), Decimal(101), Decimal("1.00"))],
    )
    assert build_report(clean_day(close_comparison=many)).status == QualityStatus.FAIL
    assert checks(build_report(clean_day(close_comparison=None)))["cross_check"].status == (
        QualityStatus.WARN
    )
    sparse = CloseComparison(checked=5, missing_in_secondary=["X"] * 5)
    assert checks(build_report(clean_day(close_comparison=sparse)))["cross_check"].status == (
        QualityStatus.WARN
    )


def test_rejected_and_zero_volume_rows_warn():
    report = build_report(
        clean_day(
            rejected=[("BAD", "high below close")],
            bars=[bar("Z", DAY, 10, 10, 10, 10, volume=0)],
            previous_day_rows=1,
        )
    )
    assert checks(report)["invalid_rows"].status == QualityStatus.WARN
    assert checks(report)["zero_volume"].status == QualityStatus.WARN
    assert report.status == QualityStatus.WARN


def test_first_trade_moves_are_labelled_as_listings():
    report = build_report(clean_day(bars=[bar("NEWCO", DAY, 140, 150, 138, 147, prev_close=100)]))
    big = checks(report)["big_moves"]
    assert "first trade" in big.message
    assert big.items[0]["symbol"] == "NEWCO"
