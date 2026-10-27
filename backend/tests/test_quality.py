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
    scheme = CorporateActionRecord(
        "H", DAY, CorporateActionType.OTHER, raw_text="SCHEME OF ARRANGEMENT"
    )
    report = build_report(
        clean_day(bars=[bar("H", DAY, 60, 62, 58, 60, prev_close=100)], actions_today=[scheme])
    )
    big = checks(report)["big_moves"]
    assert "rights issue or scheme" in big.message
    assert big.items[0]["actions"] == "SCHEME OF ARRANGEMENT"


def test_priced_demerger_and_rights_issue_explain_the_gap():
    """Decision 0017: a demerger is priced by the ex-date open, a rights issue by its
    theoretical ex-rights price, so neither gap is a big move or a held drop."""
    demerger = CorporateActionRecord("H", DAY, CorporateActionType.OTHER, raw_text="DEMERGER")
    rights = CorporateActionRecord(
        "R",
        DAY,
        CorporateActionType.RIGHTS,
        Decimal(1),
        Decimal(1),
        raw_text="RIGHTS 1:1 @ RS 20",
    )
    report = build_report(
        clean_day(
            bars=[
                bar("H", DAY, 60, 62, 58, 61, prev_close=100),
                # TERP (100 + 20) / 2 = 60.
                bar("R", DAY, 60, 61, 58, 59, prev_close=100),
            ],
            recent_closes={"H": [Decimal(100)], "R": [Decimal(100)]},
            actions_today=[demerger, rights],
        )
    )
    assert checks(report)["big_moves"].status == QualityStatus.PASS
    assert checks(report)["unexplained_drops"].status == QualityStatus.PASS


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


def test_scaled_closes_count_as_agreeing():
    scaled = CloseComparison(
        checked=2,
        scaled=[CloseDiff("A", DAY, Decimal(500), Decimal(100), Decimal("80.00"), Decimal("0.2"))],
    )
    check = checks(build_report(clean_day(close_comparison=scaled)))["cross_check"]
    assert check.status == QualityStatus.PASS
    assert "1 closes differ only by the factor" in check.message
    assert check.items[0]["second_source_factor"] == "0.2000"
    # Scaled closes don't dilute or add to the mismatch rate.
    many = CloseComparison(
        checked=10,
        mismatches=[CloseDiff("B", DAY, Decimal(100), Decimal(101), Decimal("1.00"))],
        scaled=scaled.scaled,
    )
    check = checks(build_report(clean_day(close_comparison=many)))["cross_check"]
    assert check.status == QualityStatus.FAIL
    assert "factor" in check.message


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


def test_unexplained_drop_over_15pct_holds_the_stock():
    scheme = CorporateActionRecord(
        "H", DAY, CorporateActionType.OTHER, raw_text="CAPITAL REDUCTION"
    )
    split = CorporateActionRecord(
        "S", DAY, CorporateActionType.SPLIT, Decimal(2), Decimal(1), raw_text="SPLIT"
    )
    recent = {s: [Decimal(100)] for s in ("H", "D", "S", "L", "U")}
    report = build_report(
        clean_day(
            bars=[
                bar("H", DAY, 70, 72, 68, 70, prev_close=100),  # unpriced scheme: held, named
                bar("D", DAY, 84, 85, 83, 84, prev_close=100),  # -16%: held
                bar("S", DAY, 50, 51, 49, 50, prev_close=100),  # split 2:1: explained
                bar("L", DAY, 80, 80, 80, 80, prev_close=100),  # locked lower circuit: real
                bar("U", DAY, 86, 87, 85, 86, prev_close=100),  # -14%: under the line
                bar("N", DAY, 50, 52, 49, 50, prev_close=100),  # first trade: listing
            ],
            recent_closes=recent,
            actions_today=[scheme, split],
        )
    )
    drops = checks(report)["unexplained_drops"]
    assert drops.status == QualityStatus.WARN
    assert [i["symbol"] for i in drops.items] == ["H", "D"]
    assert drops.items[0]["actions"] == "CAPITAL REDUCTION"
    assert checks(build_report(clean_day()))["unexplained_drops"].status == QualityStatus.PASS
