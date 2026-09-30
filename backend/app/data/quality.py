"""The daily data-quality report.

Each trading day gets a report with a list of checks. A check that FAILs means the
day's data can't be trusted, so the scan (M2) must not run on it; WARN lists things
worth a look (single stocks) without blocking everything.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.data.adjust import price_factor
from app.data.crosscheck import ActionDisagreement, CloseComparison
from app.data.provider import Bar, CorporateActionRecord
from app.enums import CorporateActionType, QualityStatus

BIG_MOVE_PCT = Decimal("20")
MIN_ROW_RATIO = Decimal("0.8")
STALE_SESSIONS = 5
CROSSCHECK_FAIL_RATE = Decimal("0.05")
CROSSCHECK_MISSING_WARN_RATE = Decimal("0.2")
MAX_ITEMS = 200

_ORDER = {QualityStatus.PASS: 0, QualityStatus.WARN: 1, QualityStatus.FAIL: 2}


@dataclass
class Check:
    name: str
    status: QualityStatus
    message: str
    items: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "items": self.items[:MAX_ITEMS],
            "item_count": len(self.items),
        }


@dataclass
class QualityReportData:
    trade_date: date
    checks: list[Check]

    @property
    def status(self) -> QualityStatus:
        return max(
            (c.status for c in self.checks), key=_ORDER.__getitem__, default=QualityStatus.PASS
        )

    @property
    def reasons(self) -> list[str]:
        return [c.message for c in self.checks if c.status != QualityStatus.PASS]

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date.isoformat(),
            "status": self.status.value,
            "reasons": self.reasons,
            "checks": [c.to_dict() for c in self.checks],
        }


@dataclass
class DayData:
    trade_date: date
    # "ok", "not_published" (NSE has no file) or "not_fetched" (download failed).
    file_status: str
    # True/False from the trading calendar, None if the calendar doesn't cover the year.
    calendar_trading_day: bool | None
    bars: Sequence[Bar] = ()
    rejected: Sequence[tuple[str, str]] = ()
    previous_day_rows: int | None = None
    # Each symbol's closes for the sessions before this day, oldest first.
    recent_closes: dict[str, list[Decimal]] = field(default_factory=dict)
    actions_today: Sequence[CorporateActionRecord] = ()
    close_comparison: CloseComparison | None = None
    action_disagreements: Sequence[ActionDisagreement] = ()


def _pct(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.1'))}%"


def build_report(day: DayData) -> QualityReportData:
    checks: list[Check] = []
    checks.append(_check_file(day))
    if day.file_status != "ok":
        return QualityReportData(day.trade_date, checks)
    checks.append(_check_row_count(day))
    checks.append(_check_rejected(day))
    checks.append(_check_zero_volume(day))
    checks.append(_check_big_moves(day))
    checks.append(_check_stale(day))
    checks.append(_check_crosscheck(day))
    checks.append(_check_actions(day))
    return QualityReportData(day.trade_date, checks)


def _check_file(day: DayData) -> Check:
    if day.file_status == "ok":
        if day.calendar_trading_day is False:
            return Check(
                "trading_day",
                QualityStatus.WARN,
                "NSE published a bhavcopy on a day the calendar marks as a holiday; "
                "the holiday list needs fixing",
            )
        return Check("trading_day", QualityStatus.PASS, "Bhavcopy downloaded")
    if day.file_status == "not_fetched":
        return Check(
            "trading_day",
            QualityStatus.FAIL,
            "The bhavcopy could not be downloaded, so this day has no prices",
        )
    if day.calendar_trading_day:
        return Check(
            "trading_day",
            QualityStatus.FAIL,
            "The calendar says this is a trading day but NSE has published no bhavcopy",
        )
    return Check("trading_day", QualityStatus.PASS, "Holiday: no bhavcopy published")


def _check_row_count(day: DayData) -> Check:
    rows = len(day.bars)
    prev = day.previous_day_rows
    if prev and rows < prev * MIN_ROW_RATIO:
        return Check(
            "row_count",
            QualityStatus.FAIL,
            f"Only {rows} stocks today against {prev} on the previous day; "
            "the file looks incomplete",
        )
    return Check("row_count", QualityStatus.PASS, f"{rows} stocks")


def _check_rejected(day: DayData) -> Check:
    if not day.rejected:
        return Check("invalid_rows", QualityStatus.PASS, "Every row passed the price checks")
    return Check(
        "invalid_rows",
        QualityStatus.WARN,
        f"{len(day.rejected)} rows had impossible prices and were not stored",
        [{"symbol": s, "reason": r} for s, r in day.rejected],
    )


def _check_zero_volume(day: DayData) -> Check:
    items = [{"symbol": b.symbol, "series": b.series} for b in day.bars if b.volume == 0]
    if not items:
        return Check("zero_volume", QualityStatus.PASS, "No zero-volume rows")
    return Check("zero_volume", QualityStatus.WARN, f"{len(items)} stocks show zero volume", items)


def _check_big_moves(day: DayData) -> Check:
    by_symbol: dict[str, list[CorporateActionRecord]] = {}
    for action in day.actions_today:
        by_symbol.setdefault(action.symbol, []).append(action)
    unexplained, unadjusted, first_trades = [], [], []
    for bar in day.bars:
        base = bar.prev_close
        if base is None and day.recent_closes.get(bar.symbol):
            base = day.recent_closes[bar.symbol][-1]
        if not base:
            continue
        actions = by_symbol.get(bar.symbol, [])
        for action in actions:
            factor = price_factor(action)
            if factor is not None:
                base *= factor
        move = (bar.close / base - 1) * 100
        if abs(move) <= BIG_MOVE_PCT:
            continue
        item = {
            "symbol": bar.symbol,
            "prev_close": str(bar.prev_close),
            "close": str(bar.close),
            "move_pct": str(move.quantize(Decimal("0.01"))),
        }
        unapplied = [
            a.raw_text
            for a in actions
            if a.action_type in (CorporateActionType.RIGHTS, CorporateActionType.OTHER)
        ]
        if unapplied:
            item["actions"] = ", ".join(t or "" for t in unapplied)
            unadjusted.append(item)
        elif day.recent_closes and bar.symbol not in day.recent_closes:
            # Listing day (previous close is the issue price) or back from suspension.
            item["note"] = "first trade in recent sessions: listing or relisting"
            first_trades.append(item)
        else:
            unexplained.append(item)
    if not unexplained and not unadjusted and not first_trades:
        return Check("big_moves", QualityStatus.PASS, f"No move over {BIG_MOVE_PCT}% unexplained")
    parts = []
    if unexplained:
        parts.append(
            f"{len(unexplained)} stocks moved more than {BIG_MOVE_PCT}% with no corporate action"
        )
    if unadjusted:
        parts.append(
            f"{len(unadjusted)} moved more than {BIG_MOVE_PCT}% on a rights issue or scheme "
            "that Jeron does not adjust for"
        )
    if first_trades:
        parts.append(
            f"{len(first_trades)} moved more than {BIG_MOVE_PCT}% on their first trade "
            "(listing or relisting)"
        )
    return Check(
        "big_moves", QualityStatus.WARN, "; ".join(parts), unexplained + unadjusted + first_trades
    )


def _check_stale(day: DayData) -> Check:
    items = []
    for bar in day.bars:
        history = day.recent_closes.get(bar.symbol, [])[-(STALE_SESSIONS - 1) :]
        if len(history) == STALE_SESSIONS - 1 and all(c == bar.close for c in history):
            items.append({"symbol": bar.symbol, "close": str(bar.close)})
    if not items:
        return Check("stale_prices", QualityStatus.PASS, "No stale prices")
    return Check(
        "stale_prices",
        QualityStatus.WARN,
        f"{len(items)} stocks have had the same close for {STALE_SESSIONS} sessions",
        items,
    )


def _check_crosscheck(day: DayData) -> Check:
    comparison = day.close_comparison
    if comparison is None:
        return Check(
            "cross_check",
            QualityStatus.WARN,
            "Closes were not cross-checked against a second source for this day",
        )
    expected = comparison.checked + len(comparison.missing_in_secondary)
    if comparison.checked == 0:
        return Check(
            "cross_check",
            QualityStatus.WARN,
            "The second source returned no prices for this day",
        )
    items: list[dict[str, Any]] = [
        {
            "symbol": d.symbol,
            "nse_close": str(d.primary),
            "second_source_close": str(d.secondary),
            "diff_pct": str(d.diff_pct),
        }
        for d in comparison.mismatches
    ]
    rate = Decimal(len(comparison.mismatches)) / comparison.checked
    missing_rate = Decimal(len(comparison.missing_in_secondary)) / expected
    notes = []
    status = QualityStatus.PASS
    if comparison.mismatches:
        status = QualityStatus.FAIL if rate > CROSSCHECK_FAIL_RATE else QualityStatus.WARN
        notes.append(
            f"{len(comparison.mismatches)} of {comparison.checked} closes differ from the "
            f"second source by more than 0.5% ({_pct(rate * 100)})"
        )
    if missing_rate > CROSSCHECK_MISSING_WARN_RATE:
        status = max(status, QualityStatus.WARN, key=_ORDER.__getitem__)
        notes.append(
            f"the second source had no price for {len(comparison.missing_in_secondary)} "
            f"of {expected} stocks"
        )
    if not notes:
        return Check(
            "cross_check",
            QualityStatus.PASS,
            f"All {comparison.checked} checked closes agree within 0.5%",
        )
    message = "; ".join(notes)
    return Check("cross_check", status, message[0].upper() + message[1:], items)


def _check_actions(day: DayData) -> Check:
    if not day.action_disagreements:
        return Check(
            "corporate_actions", QualityStatus.PASS, "Splits and bonuses agree across sources"
        )
    return Check(
        "corporate_actions",
        QualityStatus.WARN,
        f"{len(day.action_disagreements)} splits or bonuses disagree between sources",
        [
            {"symbol": d.symbol, "ex_date": d.ex_date.isoformat(), "detail": d.description}
            for d in day.action_disagreements
        ],
    )
