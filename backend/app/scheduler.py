"""Runs Jeron's jobs on time (spec section 10), so nothing has to be started by hand:

- 08:30 IST on trading days: `preopen` (pre-open check of open positions);
- 19:00 IST on weekdays: `daily` (data, quality, scan, news, paper, alerts), then
  `weekly` (summary and revalidation) after the last session of the week, with the
  paper review's proposals and their checks (`end_of_week`);
- 21:30 IST on weekdays: `daily` again, only if the day's data had not arrived at 19:00
  (NSE publishes late some days; the first run told me so, `app/alerts/late.py`);
- 19:45 IST on trading days: the dead-man's switch (`app/alerts/watchdog.py`), one alert
  if the daily summary hasn't gone out;
- every few minutes: the autopilot (app/autopilot.py), which sets up a new install and
  imports files dropped in the imports folder;
- every minute, when Telegram is set up: the buttons pressed under signal alerts.

Every job is safe to re-run, so a missed or repeated run does no harm. Times come from
`JERON_SCHEDULE_PREOPEN`, `JERON_SCHEDULE_DAILY`, `JERON_SCHEDULE_DAILY_RETRY` and
`JERON_SCHEDULE_WATCHDOG` (HH:MM, IST).

Jeron runs on my own computer, which can be asleep or off at those times. A job missed
while the computer slept runs when it wakes (until 15:30 for the pre-open check, until
the next morning for the daily run). On start, `catch_up` runs the daily job if the
latest session's scan is missing and the pre-open check if it is market hours.

    python -m app.scheduler
"""

import logging
import threading
from collections.abc import Callable
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app import autopilot, cli
from app.calendar.nse import TradingCalendar
from app.config import get_settings
from app.exits.job import due_session, is_session, next_session
from app.paper.job import latest_scan_date
from app.signals.build import IST

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = logging.getLogger("jeron.scheduler")
Runner = Callable[[list[str]], int]
# How late a job missed while the computer slept may still run: the pre-open check until
# about 15:30, the daily run until the next morning.
GRACE_SECONDS = {
    "preopen": 7 * 3600,
    "daily": 12 * 3600,
    "daily-retry": 10 * 3600,
    "watchdog": 4 * 3600,
}
MARKET_CLOSE = time(15, 30)
AUTOPILOT_MINUTES = 1
TELEGRAM_MINUTES = 1


def last_session_of_week(calendar: TradingCalendar, day: date) -> bool:
    return next_session(calendar, day).isocalendar()[1] != day.isocalendar()[1]


def _hm(text: str) -> tuple[int, int]:
    hour, minute = text.split(":")
    return int(hour), int(minute)


def _today() -> date:
    return datetime.now(IST).date()


def preopen_job(run: Runner = cli.main, today: Callable[[], date] = _today) -> int | None:
    day = today()
    if not is_session(TradingCalendar.default(), day):
        log.info("%s is not a trading day: no pre-open check", day)
        return None
    return run(["preopen", "--date", day.isoformat()])


def end_of_week(run: Runner, day: date) -> None:
    """The weekly summary, then the paper review: new proposals, their forward checks,
    and backtests of a few waiting ones (docs/plans/paper-review-v1.md)."""
    run(["weekly", "--date", day.isoformat()])
    run(["paper-review"])
    run(["proposal-validate", "--limit", "2"])


def daily_job(run: Runner = cli.main, today: Callable[[], date] = _today) -> int | None:
    day = today()
    calendar = TradingCalendar.default()
    if not is_session(calendar, day):
        log.info("%s is not a trading day: no daily run", day)
        return None
    code = run(["daily"])
    if last_session_of_week(calendar, day):
        end_of_week(run, day)
    return code


def _market_job_running() -> bool:
    return autopilot.market_lock.locked()


def watchdog_job(
    run: Runner = cli.main,
    today: Callable[[], date] = _today,
    running: Callable[[], bool] = _market_job_running,
) -> int | None:
    """The dead-man's switch on trading days: `watchdog` alerts once if the daily
    summary hasn't gone out, saying whether a run is still going."""
    day = today()
    if not is_session(TradingCalendar.default(), day):
        return None
    return run(["watchdog", *(["--running"] if running() else [])])


def _latest_scan() -> date | None:
    from sqlalchemy.orm import Session

    from app.db import get_engine

    with Session(get_engine()) as session:
        return latest_scan_date(session)


def catch_up(
    run: Runner = cli.main,
    now: Callable[[], datetime] = lambda: datetime.now(IST),
    latest_scan: Callable[[], date | None] = _latest_scan,
) -> list[str]:
    """Runs what was missed while the computer was off: the daily job (it updates
    everything since the last run) if the latest session whose daily time has passed
    has no scan, with the weekly job if that session ended the week; and the pre-open
    check if today trades and the market is open or about to. Returns the jobs run.
    Before the first scan nothing is caught up: the autopilot downloads the history."""
    settings = get_settings()
    calendar = TradingCalendar.default()
    at = now().astimezone(IST)
    today, clock = at.date(), at.time()
    daily_at, preopen_at = (
        time(*_hm(settings.schedule_daily)),
        time(*_hm(settings.schedule_preopen)),
    )
    ran = []
    last = due_session(calendar, at, daily_at)
    scanned = latest_scan()
    if scanned is None:
        # A new install: app/autopilot.py downloads the history, then runs `daily`.
        log.info("No scan yet: nothing to catch up")
    elif scanned < last:
        log.info("Catching up: no scan for %s yet", last)
        run(["daily"])
        ran.append("daily")
        if last_session_of_week(calendar, last):
            end_of_week(run, last)
            ran.append("weekly")
    if is_session(calendar, today) and preopen_at <= clock < MARKET_CLOSE:
        run(["preopen", "--date", today.isoformat()])  # sent once a day, so re-runs are quiet
        ran.append("preopen")
    return ran


def retry_job(
    run: Runner = cli.main,
    now: Callable[[], datetime] = lambda: datetime.now(IST),
    latest_scan: Callable[[], date | None] = _latest_scan,
) -> int | None:
    """The daily run again when the session it should have scanned has no scan yet
    (the day's data was late at the first run). Otherwise nothing."""
    at = now().astimezone(IST)
    due = due_session(TradingCalendar.default(), at, time(*_hm(get_settings().schedule_daily)))
    scanned = latest_scan()
    if scanned is None or scanned >= due:
        return None
    log.info("No scan for %s yet: running the daily job again", due)
    return run(["daily"])


def _safe(job: Callable[[], int | None], name: str, lock: bool = True) -> Callable[[], None]:
    def wrapped() -> None:
        try:
            if lock:
                # One job at a time writes prices (app/autopilot.py's market lane).
                with autopilot.market_lock:
                    code = job()
            else:
                code = job()
            log.info("%s finished (exit code %s)", name, code)
        except Exception:  # a failed run must not stop the scheduler
            log.exception("%s failed", name)

    return wrapped


def build(scheduler: BaseScheduler) -> BaseScheduler:
    settings = get_settings()
    for name, job, at in (
        ("preopen", preopen_job, settings.schedule_preopen),
        ("daily", daily_job, settings.schedule_daily),
        ("daily-retry", retry_job, settings.schedule_daily_retry),
        ("watchdog", watchdog_job, settings.schedule_watchdog),
    ):
        hour, minute = _hm(at)
        scheduler.add_job(
            # The watchdog must run while the daily job holds the lock.
            _safe(job, name, lock=name != "watchdog"),
            CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute, timezone=IST),
            id=name,
            name=name,
            misfire_grace_time=GRACE_SECONDS[name],
            coalesce=True,
        )
    scheduler.add_job(
        _safe(_autopilot_tick, "autopilot", lock=False),
        IntervalTrigger(minutes=AUTOPILOT_MINUTES, timezone=IST),
        id="autopilot",
        name="autopilot",
        max_instances=1,
        coalesce=True,
    )
    if settings.telegram_ready:
        # Buttons pressed under signal alerts (app/alerts/bot.py).
        scheduler.add_job(
            _safe(_telegram_tick, "telegram buttons", lock=False),
            IntervalTrigger(minutes=TELEGRAM_MINUTES, timezone=IST),
            id="telegram",
            name="telegram buttons",
            max_instances=1,
            coalesce=True,
        )
    return scheduler


def _session() -> "Session":
    from sqlalchemy.orm import Session

    from app.db import get_engine

    return Session(get_engine())


def _autopilot_tick() -> None:
    autopilot.tick(_session)


def _telegram_tick() -> None:
    from app.alerts.bot import poll

    with _session() as session:
        poll(session, log=log.info)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    scheduler = build(BlockingScheduler(timezone=IST))
    autopilot.start()
    _safe(lambda: len(catch_up()), "catch-up")()
    # Setup steps (a new install's history, imports, backtests) run in the background.
    threading.Thread(target=_safe(_autopilot_tick, "autopilot", lock=False), daemon=True).start()
    for job in scheduler.get_jobs():
        log.info("Scheduled %s: %s", job.name, job.trigger)
    scheduler.start()


if __name__ == "__main__":
    main()
