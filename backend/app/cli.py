"""Command-line jobs for market data. Run from backend/ (or inside the container):

python -m app.cli backfill --start 2016-01-01   # history, resumable
python -m app.cli crosscheck --start 2016-01-01 # second source for liquid stocks
python -m app.cli quality --start 2016-01-01    # data-quality reports
python -m app.cli lists --start 2016-01-01      # index closes, bands/GSM, Nifty 500 list
python -m app.cli scan                          # the daily scan for the newest day
python -m app.cli asm-import asm.csv            # load NSE's ASM list (saved from nseindia.com)
python -m app.cli events --start 2016-01-01     # board meetings (results dates), history
python -m app.cli events-import meetings.csv    # board meetings saved from nseindia.com
python -m app.cli news-label --limit 100        # label announcements (Claude; needs a key)
python -m app.cli news-testset                  # write headlines for you to label by hand
python -m app.cli news-eval testset.csv         # Claude's accuracy on your labels
python -m app.cli backtest                      # walk-forward test of every strategy
python -m app.cli paper                         # signals and paper trades for the newest scan
python -m app.cli alerts                        # send the newest day's signals and summary
python -m app.cli telegram --setup              # find your chat id after messaging the bot
python -m app.cli daily                         # update, scan, paper-trade, send alerts
python -m app.cli holidays --year 2025          # holidays as NSE's files show them
"""

import argparse
import csv
import io
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.alerts.channels import AlertError, TelegramChannel
from app.alerts.job import NOT_SET_UP, run_alerts, send_test
from app.backtest.job import run_backtests
from app.backtest.strategies import STRATEGIES
from app.calendar.nse import TradingCalendar
from app.config import get_settings
from app.data import pipeline, store
from app.data.events import parse_board_meetings, parse_board_meetings_json
from app.data.http import Fetcher
from app.data.nse import NseArchive
from app.data.yahoo import YahooClient
from app.db import get_engine
from app.enums import QualityStatus
from app.news.claude import ClaudeLabeller
from app.news.job import evaluate_test_set, export_test_set, run_daily_news, run_news
from app.paper.job import run_paper
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

    p = sub.add_parser("backtest", help="walk-forward backtest of the strategies, saved as runs")
    p.add_argument(
        "--strategy",
        choices=sorted(STRATEGIES),
        action="append",
        help="strategy to test (repeatable; default: all)",
    )
    p.add_argument("--start", type=_date, help="first price date to use (default: all)")
    p.add_argument("--end", type=_date, help="last price date to use (default: newest)")

    p = sub.add_parser(
        "paper", help="paper-trade every strategy to the newest scanned day; record signals"
    )
    p.add_argument("--date", type=_date, help="day to update to (default: newest scan)")
    p.add_argument(
        "--strategy",
        choices=sorted(STRATEGIES),
        action="append",
        help="strategy to update (repeatable; default: all)",
    )
    p.add_argument(
        "--restart",
        action="store_true",
        help="close the active accounts and open new ones from this day",
    )

    p = sub.add_parser("alerts", help="send due signal alerts and the daily summary")
    p.add_argument("--date", type=_date, help="day to send for (default: newest scan)")

    p = sub.add_parser("telegram", help="set up or test Telegram alerts")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--setup", action="store_true", help="list chats that messaged the bot (your chat id)"
    )
    group.add_argument("--test", action="store_true", help="send a test message")

    sub.add_parser(
        "daily",
        help="update everything since the last run, scan, paper-trade, send alerts "
        "(run after 7 pm IST)",
    )

    p = sub.add_parser(
        "events", help="board meetings and announcements from NSE's daily files, for history"
    )
    p.add_argument("--start", type=_date, required=True)
    p.add_argument("--end", type=_date)

    p = sub.add_parser(
        "events-import", help="load board meetings from a CSV saved from NSE's website"
    )
    p.add_argument("file", type=Path)

    p = sub.add_parser(
        "news-label",
        help="label announcements: event type by subject (free), then Claude (needs a key)",
    )
    p.add_argument("--start", type=_date, help="first announcement day (default: all)")
    p.add_argument("--end", type=_date)
    p.add_argument("--limit", type=int, help="label at most this many (newest first)")
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--batch", action="store_true", help="send as a batch: half price, back within a day"
    )
    group.add_argument("--collect", action="store_true", help="only collect finished batches")

    p = sub.add_parser("news-testset", help="write ~100 announcements for you to label by hand")
    p.add_argument("--out", type=Path, default=Path("news-testset.csv"))
    p.add_argument("--size", type=int, default=100)

    p = sub.add_parser("news-eval", help="compare Claude's labels with your hand labels")
    p.add_argument("file", type=Path)
    p.add_argument("--model", help="Claude model to test (default: JERON_NEWS_MODEL)")

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

        if args.command == "events":
            end = args.end or today
            _log(f"Board meetings and announcements, {args.start} to {end}:")
            stored, items, unread = pipeline.board_meetings_range(
                session, _archive(), calendar, args.start, end, today, log=_log
            )
            _log(f"Done: {stored} new meetings, {items} new announcements.")
            if unread:
                _log(f"{len(unread)} days could not be read; run the same command again.")
                return 1
            return 0

        if args.command == "events-import":
            content = args.file.read_bytes()
            meetings = (
                parse_board_meetings_json(content)
                if content.lstrip()[:1] in (b"[", b"{")
                else parse_board_meetings(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
            )
            stored = store.save_board_meetings(session, meetings, pipeline.BOARD_MEETINGS_IMPORT)
            session.commit()
            for_results = sum(m.is_results for m in meetings)
            _log(f"{len(meetings)} meetings read ({for_results} for results), {stored} new.")
            return 0 if meetings else 1

        if args.command == "backtest":
            run_backtests(session, args.strategy, args.start, args.end, log=_log)
            return 0

        if args.command == "paper":
            paper = run_paper(session, args.date, args.strategy, restart=args.restart, log=_log)
            return 0 if paper.status == "ok" else 1

        if args.command == "alerts":
            sent = run_alerts(session, args.date, log=_log)
            return 0 if sent.status == "ok" and not sent.failed else 1

        if args.command == "telegram":
            settings = get_settings()
            if args.setup:
                if not settings.telegram_bot_token:
                    _log("Set JERON_TELEGRAM_BOT_TOKEN in .env first (from @BotFather).")
                    return 1
                try:
                    chats = TelegramChannel(settings.telegram_bot_token, "").chats()
                except AlertError as e:
                    _log(f"Telegram: {e}")
                    return 1
                if not chats:
                    _log("No messages yet: send your bot any message in Telegram, then rerun.")
                    return 1
                for chat_id, name in chats:
                    _log(f"chat id {chat_id} ({name}): set JERON_TELEGRAM_CHAT_ID={chat_id}")
                return 0
            alert = send_test(session)
            if alert is None:
                _log(NOT_SET_UP)
                return 1
            _log(
                f"Test message sent by {alert.channel}."
                if alert.status == "sent"
                else f"Test message failed: {alert.error}"
            )
            return 0 if alert.status == "sent" else 1

        if args.command == "daily":
            report = pipeline.daily_update(session, _archive(), _yahoo(), calendar, today, log=_log)
            if report is None:
                return 1
            _log(f"{report.trade_date}: data quality {report.status.value.upper()}")
            for reason in report.reasons:
                _log(f"  - {reason}")
            outcome = run_scan(session, report.trade_date, log=_log)
            ok = report.status != QualityStatus.FAIL and outcome.status == "ok"
            settings = get_settings()
            run_daily_news(
                session, settings.anthropic_api_key, settings.news_model, report.trade_date, _log
            )
            if ok:
                ok = run_paper(session, report.trade_date, log=_log).status == "ok"
            # The summary goes out even when the day was blocked, saying why.
            sent = run_alerts(session, report.trade_date, log=_log)
            return 0 if ok and not sent.failed else 1

        if args.command == "news-label":
            settings = get_settings()
            return run_news(
                session,
                settings.anthropic_api_key,
                settings.news_model,
                args.start,
                args.end,
                limit=0 if args.collect else args.limit,
                batch=args.batch,
                log=_log,
            )

        if args.command == "news-testset":
            count = export_test_set(session, args.out, size=args.size)
            _log(
                f"Wrote {count} announcements to {args.out}. Fill in event_type and sentiment "
                "(-2 to +2) for each, then run news-eval on the file."
            )
            return 0 if count else 1

        if args.command == "news-eval":
            settings = get_settings()
            if not settings.news_ready:
                _log("No JERON_ANTHROPIC_API_KEY in .env: Claude can't label the test set.")
                return 1
            labeller = ClaudeLabeller(settings.anthropic_api_key, args.model or settings.news_model)
            result = evaluate_test_set(session, args.file, labeller, log=_log)
            cost = labeller.usage.cost(labeller.name)
            if cost:
                _log(f"Labelling the test set with {labeller.name} cost about US${cost:.2f}.")
            for name, acc in (("Claude", result.llm), ("Subject rules", result.rules)):
                _log(
                    f"{name}: event type right {acc.type_correct}/{acc.count} "
                    f"({acc.type_accuracy:.0%}), good/bad/neutral right {acc.direction_correct}/"
                    f"{acc.count} ({acc.direction_accuracy:.0%}), sentiment off by "
                    f"{acc.sentiment_error:.2f} on average"
                )
            for kind, (right, total) in result.llm.per_type.items():
                _log(f"  {kind}: {right}/{total}")
            for problem in result.problems:
                _log(f"  ! {problem}")
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
