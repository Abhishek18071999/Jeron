"""Jobs that move data from the sources into the database and check it.

- `ingest_range`: NSE bhavcopy prices and NSE corporate actions, day by day.
- `crosscheck_range`: the second source (Yahoo) for the liquid stocks.
- `quality_range`: the daily data-quality report.
- `ingest_lists_range`: NSE index closes and the security list (bands, GSM), per day.
- `refresh_reference_lists`: Nifty 500 constituents, company names, symbol changes.
- `daily_update`: all of these for the days since the last run.

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
from app.data.events import parse_board_meetings_json
from app.data.http import FetchError, NotPublishedError
from app.data.nse import (
    BhavcopyError,
    NseArchive,
    bhavcopy_url,
    index_closes_url,
    parse_bhavcopy,
    parse_pr_corporate_actions,
    pr_url,
    security_list_url,
)
from app.data.nse_lists import (
    EQUITY_LIST_URL,
    NIFTY500_LIST_URL,
    NIFTY_500,
    SYMBOL_CHANGES_URL,
    ListFormatError,
    parse_equity_list,
    parse_index_closes,
    parse_index_constituents,
    parse_security_list,
    parse_symbol_changes,
)
from app.data.nse_site import NseSite
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


# Weekend days NSE is believed to have traded (Budget days, Muhurat sessions, disaster-
# recovery drills). Only used to decide which weekend files to try: a wrong date just
# gets "not published". The trading calendar is not changed by this list.
KNOWN_WEEKEND_SESSIONS = frozenset(
    {
        date(2016, 10, 30),
        date(2019, 10, 27),
        date(2020, 2, 1),
        date(2020, 11, 14),
        date(2023, 11, 12),
        date(2024, 1, 20),
        date(2024, 3, 2),
        date(2024, 5, 18),
        date(2025, 2, 1),
        date(2026, 2, 1),
    }
)


def _candidate_days(start: date, end: date, calendar: TradingCalendar) -> Iterator[date]:
    """Weekdays, plus weekend days that may have had a special session."""
    for day in _days(start, end):
        if day.weekday() < 5 or day in calendar.special_sessions or day in KNOWN_WEEKEND_SESSIONS:
            yield day


@dataclass
class IngestResult:
    day: date
    status: str
    rows: int = 0
    actions: int = 0
    # Set when the prices were stored but the corporate actions file could not be read.
    problem: str | None = None


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
            try:
                records = parse_pr_corporate_actions(pr)
            except BhavcopyError as exc:
                # Keep the day's prices; the bad file is recorded and the day is
                # re-read on the next run (from the cache, so a parser fix applies).
                store.record_source_file(
                    session,
                    store.NSE_PR,
                    day,
                    "unreadable",
                    url=pr_url(day),
                    sha256=hashlib.sha256(pr).hexdigest(),
                    details={"error": str(exc)},
                )
                return IngestResult(day, "ok", len(parsed.bars), problem=str(exc))
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
        except Exception as exc:  # noqa: BLE001 - one bad day must not stop a backfill
            session.rollback()
            store.record_source_file(
                session,
                store.NSE_BARS,
                day,
                "not_fetched",
                url=bhavcopy_url(day),
                details={"error": f"{type(exc).__name__}: {exc}"},
            )
            result = IngestResult(day, "not_fetched")
            log(f"{day}: failed: {type(exc).__name__}: {exc}")
        session.commit()
        results.append(result)
        if result.problem:
            log(f"{day}: {result.rows} stocks; corporate actions file unreadable: {result.problem}")
        elif result.status == "ok":
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


# Sessions on each side of a day used to recognise the second source's scaling.
NEIGHBOUR_SESSIONS = 10


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
        if comparison.mismatches:
            # Is the difference Yahoo's scaling for a later corporate action? Compare
            # with the same stocks' ratios on the surrounding sessions.
            neighbours = store.close_ratios(
                session,
                store.YAHOO,
                day,
                {d.symbol for d in comparison.mismatches},
                NEIGHBOUR_SESSIONS,
            )
            comparison = compare_closes(primary, secondary, neighbours=neighbours)
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
        if status != "ok" and day.weekday() >= 5 and day not in calendar.special_sessions:
            continue
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


# NSE's archive has security lists from 2020; earlier days are not requested.
SECURITY_LIST_START = date(2020, 1, 1)


def _ingest_list_day(
    session: Session,
    archive: NseArchive,
    source: str,
    day: date,
    today: date,
) -> str:
    if source == store.NSE_INDICES:
        url, download = index_closes_url(day), archive.index_closes
    else:
        url, download = security_list_url(day), archive.security_list
    try:
        content = download(day, today)
    except FetchError as exc:
        store.record_source_file(
            session, source, day, "not_fetched", url=url, details={"error": str(exc)}
        )
        return "not_fetched"
    if content is None:
        if day <= today - timedelta(days=archive.settle_days):
            store.record_source_file(session, source, day, "not_published", url=url)
            return "not_published"
        return "pending"
    try:
        if source == store.NSE_INDICES:
            rows = store.save_index_closes(session, parse_index_closes(content, day))
        else:
            rows = store.save_security_status(session, day, parse_security_list(content))
    except (ListFormatError, ValueError, KeyError) as exc:
        session.rollback()
        store.record_source_file(
            session, source, day, "not_fetched", url=url, details={"error": str(exc)}
        )
        return "not_fetched"
    store.record_source_file(
        session, source, day, "ok", url=url, sha256=hashlib.sha256(content).hexdigest(), rows=rows
    )
    return "ok"


def ingest_lists_range(
    session: Session,
    archive: NseArchive,
    start: date,
    end: date,
    today: date,
    *,
    force: bool = False,
    log: Log = _quiet,
) -> dict[str, list[date]]:
    """Index closes and security lists for each day NSE traded (has a bhavcopy).
    Returns the days each source could not be downloaded."""
    failed: dict[str, list[date]] = {store.NSE_INDICES: [], store.NSE_SEC_LIST: []}
    days = store.ok_dates(session, store.NSE_BARS, start, end)
    for source in (store.NSE_INDICES, store.NSE_SEC_LIST):
        done = store.source_statuses(session, source, start, end)
        todo = [
            d
            for d in days
            if (force or done.get(d) not in ("ok", "not_published"))
            and (source != store.NSE_SEC_LIST or d >= SECURITY_LIST_START)
        ]
        for i, day in enumerate(todo, 1):
            status = _ingest_list_day(session, archive, source, day, today)
            session.commit()
            if status == "not_fetched":
                failed[source].append(day)
                log(f"{day}: {source} could not be downloaded")
            elif status == "not_published":
                log(f"{day}: {source} not published")
            if i % 50 == 0:
                log(f"{source}: {i} of {len(todo)} days")
    return failed


def refresh_reference_lists(
    session: Session, archive: NseArchive, today: date, *, log: Log = _quiet
) -> bool:
    """Today's Nifty 500 list, company names and symbol changes. These files have no
    history on NSE's server, so each download is recorded as of `today`. Returns
    False if any could not be downloaded."""
    ok = True
    try:
        members = parse_index_constituents(archive.current_list(NIFTY500_LIST_URL, today))
        joined, left = store.refresh_index_membership(session, NIFTY_500, members, today)
        log(f"Nifty 500: {len(members)} stocks ({joined} joined, {left} left)")
        names = parse_equity_list(archive.current_list(EQUITY_LIST_URL, today))
        store.update_instrument_names(session, names)
        changes = parse_symbol_changes(archive.current_list(SYMBOL_CHANGES_URL, today))
        store.save_symbol_changes(session, changes)
        store.record_source_file(
            session,
            "nse_lists",
            today,
            "ok",
            rows=len(members),
            details={
                "nifty500": len(members),
                "equities": len(names),
                "symbol_changes": len(changes),
            },
        )
    except (FetchError, NotPublishedError, ListFormatError) as exc:
        session.rollback()
        log(f"Reference lists could not be refreshed: {exc}")
        ok = False
    session.commit()
    return ok


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
    ingest_lists_range(session, archive, new_days[0] - timedelta(days=7), today, today, log=log)
    refresh_reference_lists(session, archive, today, log=log)
    crosscheck_range(session, yahoo, new_days[0] - timedelta(days=7), today, log=log)
    reports = quality_range(session, calendar, new_days[0], today, log=log)
    return reports[-1] if reports else None


# --- Board meetings (M6) --------------------------------------------------------------

BOARD_MEETINGS_SOURCE = "nse_board_meetings"
BOARD_MEETINGS_IMPORT = "nse_board_meetings_import"
# Days of meetings asked for in one request.
BOARD_MEETINGS_CHUNK_DAYS = 31


def fetch_board_meetings(
    session: Session,
    site: NseSite,
    start: date,
    end: date,
    today: date,
    log: Callable[[str], None] = _quiet,
) -> tuple[int, int, list[tuple[date, date]]]:
    """Download board meetings with a meeting date from `start` to `end`, a month at a
    time. Returns (meetings seen, new ones stored, ranges that failed). A complete
    download that covers `today` marks the calendar as up to date on `today`."""
    seen = new = 0
    failed: list[tuple[date, date]] = []
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=BOARD_MEETINGS_CHUNK_DAYS - 1), end)
        try:
            meetings = parse_board_meetings_json(site.board_meetings(chunk_start, chunk_end))
        except (FetchError, NotPublishedError, ValueError) as exc:
            log(f"  {chunk_start} to {chunk_end}: not fetched ({exc})")
            failed.append((chunk_start, chunk_end))
        else:
            added = store.save_board_meetings(session, meetings, BOARD_MEETINGS_SOURCE)
            session.commit()
            seen += len(meetings)
            new += added
            log(f"  {chunk_start} to {chunk_end}: {len(meetings)} meetings, {added} new")
        chunk_start = chunk_end + timedelta(days=1)
    if not failed and start <= today <= end:
        store.record_source_file(session, BOARD_MEETINGS_SOURCE, today, "ok", rows=seen)
        session.commit()
    return seen, new, failed
