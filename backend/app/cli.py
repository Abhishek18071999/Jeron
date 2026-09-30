"""Command-line jobs for market data. Run from backend/ (or inside the container):

python -m app.cli backfill --start 2016-01-01   # history, resumable
python -m app.cli crosscheck --start 2016-01-01 # second source for liquid stocks
python -m app.cli quality --start 2016-01-01    # data-quality reports
python -m app.cli daily                         # everything since the last run
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

    sub.add_parser("daily", help="update everything since the last run (run after 7 pm IST)")

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
            _log(f"Done: {sum(r.status == 'ok' for r in results)} trading days stored.")
            if failed:
                _log(f"{len(failed)} days could not be downloaded; run the same command again.")
                return 1
            return 0

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

        if args.command == "daily":
            report = pipeline.daily_update(session, _archive(), _yahoo(), calendar, today, log=_log)
            if report is None:
                return 1
            _log(f"{report.trade_date}: data quality {report.status.value.upper()}")
            for reason in report.reasons:
                _log(f"  - {reason}")
            return 1 if report.status == QualityStatus.FAIL else 0

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
