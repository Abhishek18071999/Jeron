"""Jobs that move data from the sources into the database and check it.

- `ingest_range`: NSE bhavcopy prices and NSE corporate actions, day by day.
- `crosscheck_range`: the second source (Yahoo) for the liquid stocks.
- `quality_range`: the daily data-quality report.
- `daily_update`: all three for the days since the last run.

Every job is safe to re-run; each day is committed on its own, so an interrupted
backfill continues where it stopped.
"""

import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.calendar.nse import TradingCalendar, UnknownCalendarYearError
from app.data import store
from app.data.crosscheck import CloseComparison, compare_closes, compare_share_actions
from app.data.http import FetchError, NotPublishedError
from app.data.nse import (
    BhavcopyError,
    NseArchive,
    bhavcopy_url,
    parse_bhavcopy,
    parse_pr_corporate_actions,
    pr_url,
)
from app.data.quality import STALE_SESSIONS, DayData, QualityReportData, build_report
from app.data.yahoo import YahooClient
from app.models import DataQualityReport, SourceFile

Log = Callable[[str], None]


def _quiet(_: str) -> None:
    pass


def _days(start: date, end: date) -> Iterator[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _candidate_days(start: date, end: date, calendar: TradingCalendar) -> Iterator[date]:
    """Weekdays, plus weekend days the calendar lists as special sessions."""
    for day in _days(start, end):
        if day.weekday() < 5 or day in calendar.special_sessions:
            yield day


@dataclass
class IngestResult:
    day: date
    status: str
    rows: int = 0
    actions: int = 0


def ingest_day(session: Session, archive: NseArchive, day: date, today: date) -> IngestResult:
    """Download, parse and store one day's bhavcopy and corporate actions."""
    settled = day <= today - timedelta(days=archive.settle_days)
    try:
        content = archive.bhavcopy(day, today)
    except FetchError as exc:
        store.record_source_file(
            session,
            store.NSE_BARS,
            day,
            "not_fetched",
            url=bhavcopy_url(day),
            details={"error": str(exc)},
        )
        return IngestResult(day, "not_fetched")
    if content is None:
        if settled:
            store.record_source_file(
                session, store.NSE_BARS, day, "not_published", url=bhavcopy_url(day)
            )
            store.record_source_file(session, store.NSE_PR, day, "not_published", url=pr_url(day))
        return IngestResult(day, "not_published" if settled else "pending")

    parsed = parse_bhavcopy(content, day)
    store.save_bars(session, store.NSE_BARS, parsed.bars)
    latest = session.scalar(
        select(SourceFile.trade_date)
        .where(SourceFile.source == store.NSE_BARS, SourceFile.status == "ok")
        .order_by(SourceFile.trade_date.desc())
        .limit(1)
    )
    if latest is None or day >= latest:
        store.refresh_instrument_details(session, parsed.bars)
    store.record_source_file(
        session,
        store.NSE_BARS,
        day,
        "ok",
        url=bhavcopy_url(day),
        sha256=hashlib.sha256(content).hexdigest(),
        rows=len(parsed.bars),
        details={"rejected": [list(r) for r in parsed.rejected]},
    )

    actions = 0
    try:
        pr = archive.pr_bundle(day, today)
    except FetchError as exc:
        store.record_source_file(
            session, store.NSE_PR, day, "not_fetched", url=pr_url(day), details={"error": str(exc)}
        )
    else:
        if pr is None:
            store.record_source_file(session, store.NSE_PR, day, "not_published", url=pr_url(day))
        else:
            records = parse_pr_corporate_actions(pr)
            actions = store.save_actions(session, store.NSE_ACTIONS, records)
            store.record_source_file(
                session,
                store.NSE_PR,
                day,
                "ok",
                url=pr_url(day),
                sha256=hashlib.sha256(pr).hexdigest(),
                rows=actions,
            )
    return IngestResult(day, "ok", len(parsed.bars), actions)


def ingest_range(
    session: Session,
    archive: NseArchive,
    calendar: TradingCalendar,
    start: date,
    end: date,
    today: date,
    *,
    force: bool = False,
    log: Log = _quiet,
) -> list[IngestResult]:
    done_bars = store.source_statuses(session, store.NSE_BARS, start, end)
    done_pr = store.source_statuses(session, store.NSE_PR, start, end)
    finished = {"ok", "not_published"}
    results = []
    for day in _candidate_days(start, end, calendar):
        if not force and done_bars.get(day) in finished and done_pr.get(day) in finished:
            continue
        try:
            result = ingest_day(session, archive, day, today)
        except BhavcopyError as exc:
            session.rollback()
            store.record_source_file(
                session,
                store.NSE_BARS,
                day,
                "not_fetched",
                url=bhavcopy_url(day),
                details={"error": str(exc)},
            )
            result = IngestResult(day, "not_fetched")
            log(f"{day}: could not read the bhavcopy: {exc}")
        session.commit()
        results.append(result)
        if result.status == "ok":
            log(f"{day}: {result.rows} stocks, {result.actions} corporate-action rows")
        elif result.status != "pending":
            log(f"{day}: {result.status}")
    return results


def crosscheck_range(
    session: Session,
    yahoo: YahooClient,
    start: date,
    end: date,
    symbols: list[str] | None = None,
    *,
    log: Log = _quiet,
) -> list[str]:
    """Fetch the second source for `symbols` (default: the liquid stocks as of `end`)
    and record, for each NSE trading day in the range, which symbols were checked.
    Returns the symbols the second source doesn't know."""
    if symbols is None:
        symbols = store.liquid_symbols(session, end)
    unknown, failed = [], []
    fetched: dict[date, int] = {}
    for i, symbol in enumerate(symbols, 1):
        try:
            history = yahoo.history(symbol, start, end)
        except NotPublishedError:
            unknown.append(symbol)
            continue
        except (FetchError, ValueError) as exc:
            failed.append(symbol)
            log(f"{symbol}: {exc}")
            continue
        store.save_bars(session, store.YAHOO, history.bars)
        store.save_actions(session, store.YAHOO, history.actions)
        for bar in history.bars:
            fetched[bar.trade_date] = fetched.get(bar.trade_date, 0) + 1
        session.commit()
        if i % 50 == 0:
            log(f"second source: {i} of {len(symbols)} stocks")
    checked = sorted(set(symbols) - set(failed))
    for day in store.ok_dates(session, store.NSE_BARS, start, end):
        store.record_source_file(
            session,
            store.YAHOO,
            day,
            "ok",
            rows=fetched.get(day, 0),
            details={"symbols": checked},
        )
    session.commit()
    if unknown:
        log(f"second source has no data for {len(unknown)} stocks: {', '.join(unknown[:20])}")
    return unknown


def build_day_report(session: Session, calendar: TradingCalendar, day: date) -> QualityReportData:
    nse_file = store.source_file(session, store.NSE_BARS, day)
    try:
        calendar_trading_day: bool | None = calendar.is_trading_day(day)
    except UnknownCalendarYearError:
        calendar_trading_day = None
    if nse_file is None or nse_file.status != "ok":
        return build_report(
            DayData(day, nse_file.status if nse_file else "not_fetched", calendar_trading_day)
        )

    bars = store.day_bars(session, store.NSE_BARS, day)
    previous = session.scalar(
        select(SourceFile.rows)
        .where(
            SourceFile.source == store.NSE_BARS,
            SourceFile.status == "ok",
            SourceFile.trade_date < day,
        )
        .order_by(SourceFile.trade_date.desc())
        .limit(1)
    )
    comparison: CloseComparison | None = None
    disagreements = []
    yahoo_file = store.source_file(session, store.YAHOO, day)
    if yahoo_file is not None:
        checked = set(yahoo_file.details.get("symbols", []))
        primary = [b for b in bars if b.symbol in checked]
        secondary = store.day_bars(session, store.YAHOO, day, checked)
        comparison = compare_closes(primary, secondary)
        window = timedelta(days=5)
        disagreements = [
            d
            for d in compare_share_actions(
                store.actions_between(
                    session, store.NSE_ACTIONS, day - window, day + window, checked
                ),
                store.actions_between(session, store.YAHOO, day - window, day + window, checked),
                day - window,
                day + window,
            )
            if d.ex_date == day
        ]
    return build_report(
        DayData(
            trade_date=day,
            file_status="ok",
            calendar_trading_day=calendar_trading_day,
            bars=bars,
            rejected=[tuple(r) for r in nse_file.details.get("rejected", [])],
            previous_day_rows=previous,
            recent_closes=store.recent_closes(session, store.NSE_BARS, day, STALE_SESSIONS - 1),
            actions_today=store.actions_between(session, store.NSE_ACTIONS, day, day),
            close_comparison=comparison,
            action_disagreements=disagreements,
        )
    )


def save_report(session: Session, report: QualityReportData) -> None:
    stmt = pg_insert(DataQualityReport).values(
        trade_date=report.trade_date, status=report.status, details=report.to_dict()
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["trade_date"],
        set_={"status": stmt.excluded.status, "details": stmt.excluded.details},
    )
    session.execute(stmt)


def quality_range(
    session: Session,
    calendar: TradingCalendar,
    start: date,
    end: date,
    *,
    log: Log = _quiet,
) -> list[QualityReportData]:
    """Build reports for days NSE traded, and for calendar trading days with no data."""
    statuses = store.source_statuses(session, store.NSE_BARS, start, end)
    reports = []
    for day in _candidate_days(start, end, calendar):
        status = statuses.get(day)
        if status != "ok":
            try:
                expected = calendar.is_trading_day(day)
            except UnknownCalendarYearError:
                expected = status == "not_fetched"
            if not expected:
                continue
        report = build_day_report(session, calendar, day)
        save_report(session, report)
        session.commit()
        reports.append(report)
        if report.status.value != "pass":
            log(f"{day}: {report.status.value.upper()}: {'; '.join(report.reasons)}")
    return reports


def daily_update(
    session: Session,
    archive: NseArchive,
    yahoo: YahooClient,
    calendar: TradingCalendar,
    today: date,
    *,
    lookback_days: int = 10,
    log: Log = _quiet,
) -> QualityReportData | None:
    """Bring prices, corporate actions, the cross-check and the quality report up to
    date. Returns the report for the newest trading day."""
    start = today - timedelta(days=lookback_days)
    known = store.ok_dates(session, store.NSE_BARS)
    if known and known[-1] + timedelta(days=1) < start:
        start = known[-1] + timedelta(days=1)
    ingest_range(session, archive, calendar, start, today, today, log=log)
    new_days = store.ok_dates(session, store.NSE_BARS, start, today)
    if not new_days:
        log("No trading days found in the last few days")
        return None
    crosscheck_range(session, yahoo, new_days[0] - timedelta(days=7), today, log=log)
    reports = quality_range(session, calendar, new_days[0], today, log=log)
    return reports[-1] if reports else None
