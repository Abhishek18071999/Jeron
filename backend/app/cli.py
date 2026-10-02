"""Command-line jobs for market data. Run from backend/ (or inside the container):

python -m app.cli backfill --start 2016-01-01   # history, resumable
python -m app.cli crosscheck --start 2016-01-01 # second source for liquid stocks
python -m app.cli quality --start 2016-01-01    # data-quality reports
python -m app.cli lists --start 2016-01-01      # index closes, bands/GSM, Nifty 500 list
python -m app.cli scan                          # the daily scan for the newest day
python -m app.cli asm-import asm.csv            # load NSE's ASM list (saved from nseindia.com)
python -m app.cli daily                         # everything since the last run, then the scan
python -m app.cli holidays --year 2025          # holidays as NSE's files show them
"""

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.calendar.nse import TradingCalendar
from app.config import get_settings
from app.data import pipeline, store
from app.data.http import Fetcher
from app.data.nse import NseArchive
from app.data.yahoo import YahooClient
from app.db import get_engine
from app.enums import QualityStatus
from app.scan.job import ASM, run_scan
from app.scan.surveillance import read_asm_csv


def _log(message: str) -> None:
    print(message, flush=True)


def _today() -> date:
    return datetime.now(ZoneInfo(get_settings().timezone)).date()


def _archive() -> NseArchive:
    settings = get_settings()
    return NseArchive(Fetcher(min_interval=settings.nse_request_interval), Path(settings.data_dir))


def _yahoo() -> YahooClient:
    return YahooClient(Fetcher(min_interval=get_settings().yahoo_request_interval))


def _date(value: str) -> date:
    return date.fromisoformat(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("backfill", help="download and store NSE prices and corporate actions")
    p.add_argument("--start", type=_date, default=date(2016, 1, 1))
    p.add_argument("--end", type=_date)
    p.add_argument("--force", action="store_true", help="re-read days already stored")

    p = sub.add_parser("crosscheck", help="fetch the second source (Yahoo) for liquid stocks")
    p.add_argument("--start", type=_date, default=date(2016, 1, 1))
    p.add_argument("--end", type=_date)
    p.add_argument("--symbols", help="comma-separated NSE symbols (default: liquid stocks)")

    p = sub.add_parser("quality", help="build data-quality reports")
    p.add_argument("--start", type=_date)
    p.add_argument("--end", type=_date)

    p = sub.add_parser(
        "lists", help="download index closes, security lists and the reference lists"
    )
    p.add_argument("--start", type=_date, default=date(2016, 1, 1))
    p.add_argument("--end", type=_date)
    p.add_argument("--force", action="store_true", help="re-read days already stored")

    p = sub.add_parser("scan", help="run the daily scan (default: newest trading day)")
    p.add_argument("--date", type=_date)

    p = sub.add_parser("asm-import", help="load the ASM list from a CSV saved from NSE's site")
    p.add_argument("file", type=Path)
    p.add_argument("--date", type=_date, help="date the list applies from (default: today)")

    sub.add_parser(
        "daily", help="update everything since the last run, then scan (run after 7 pm IST)"
    )

    p = sub.add_parser(
        "holidays", help="print weekday holidays and weekend sessions seen in NSE files"
    )
    p.add_argument("--year", type=int, required=True)

    args = parser.parse_args(argv)
    calendar = TradingCalendar.default()
    today = _today()

    with Session(get_engine()) as session:
        if args.command == "backfill":
            end = args.end or today
            results = pipeline.ingest_range(
                session, _archive(), calendar, args.start, end, today, force=args.force, log=_log
            )
            failed = [r.day for r in results if r.status == "not_fetched"]
            unreadable = [r.day for r in results if r.problem]
            _log(f"Done: {sum(r.status == 'ok' for r in results)} trading days stored.")
            if unreadable:
                days = ", ".join(str(d) for d in unreadable[:10])
                more = f" and {len(unreadable) - 10} more" if len(unreadable) > 10 else ""
                _log(
                    f"{len(unreadable)} days' corporate actions files could not be read "
                    f"({days}{more}); their prices are stored. Please report this."
                )
            list_failures = pipeline.ingest_lists_range(
                session, _archive(), args.start, end, today, force=args.force, log=_log
            )
            failed += [d for days in list_failures.values() for d in days]
            if failed:
                _log(f"{len(failed)} days could not be downloaded; run the same command again.")
                return 1
            return 1 if unreadable else 0

        if args.command == "crosscheck":
            end = args.end or today
            symbols = args.symbols.split(",") if args.symbols else None
            pipeline.crosscheck_range(session, _yahoo(), args.start, end, symbols, log=_log)
            return 0

        if args.command == "quality":
            dates = store.ok_dates(session, store.NSE_BARS)
            if not dates:
                _log("No prices stored yet; run backfill first.")
                return 1
            reports = pipeline.quality_range(
                session, calendar, args.start or dates[0], args.end or dates[-1], log=_log
            )
            counts = {s: sum(r.status == s for r in reports) for s in QualityStatus}
            _log(
                f"{len(reports)} reports: {counts[QualityStatus.PASS]} pass, "
                f"{counts[QualityStatus.WARN]} warn, {counts[QualityStatus.FAIL]} fail"
            )
            return 0

        if args.command == "lists":
            archive = _archive()
            failures = pipeline.ingest_lists_range(
                session, archive, args.start, args.end or today, today, force=args.force, log=_log
            )
            lists_ok = pipeline.refresh_reference_lists(session, archive, today, log=_log)
            missing = sum(len(days) for days in failures.values())
            if missing:
                _log(f"{missing} files could not be downloaded; run the same command again.")
            return 0 if lists_ok and not missing else 1

        if args.command == "scan":
            outcome = run_scan(session, args.date, log=_log)
            return 0 if outcome.status == "ok" else 1

        if args.command == "asm-import":
            symbols = read_asm_csv(args.file.read_bytes())
            as_of = args.date or today
            added, removed = store.replace_surveillance(session, ASM, symbols, as_of, "manual")
            store.record_source_file(session, store.ASM_IMPORT, as_of, "ok", rows=len(symbols))
            session.commit()
            _log(
                f"ASM list as of {as_of}: {len(symbols)} stocks ({added} added, {removed} removed)"
            )
            return 0

        if args.command == "daily":
            report = pipeline.daily_update(session, _archive(), _yahoo(), calendar, today, log=_log)
            if report is None:
                return 1
            _log(f"{report.trade_date}: data quality {report.status.value.upper()}")
            for reason in report.reasons:
                _log(f"  - {reason}")
            outcome = run_scan(session, report.trade_date, log=_log)
            if report.status == QualityStatus.FAIL or outcome.status != "ok":
                return 1
            return 0

        if args.command == "holidays":
            start, end = date(args.year, 1, 1), date(args.year, 12, 31)
            statuses = store.source_statuses(session, store.NSE_BARS, start, end)
            day = start
            while day <= end:
                status = statuses.get(day)
                if day.weekday() < 5 and status == "not_published":
                    print(f"{day},holiday,No NSE bhavcopy,yes")
                elif day.weekday() >= 5 and status == "ok":
                    print(f"{day},special_session,NSE bhavcopy on a weekend,yes")
                elif day.weekday() < 5 and status != "ok":
                    print(f"# {day}: unknown ({status or 'not downloaded'})", file=sys.stderr)
                day += timedelta(days=1)
            return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
