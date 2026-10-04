"""Runs Jeron's jobs on time (spec section 10), so nothing has to be started by hand:

- 08:30 IST on trading days: `preopen` (pre-open check of open positions);
- 19:00 IST on weekdays: `daily` (data, quality, scan, news, paper, alerts), then
  `weekly` (summary and revalidation) after the last session of the week.

Every job is safe to re-run, so a missed or repeated run does no harm. Times come from
`JERON_SCHEDULE_PREOPEN` and `JERON_SCHEDULE_DAILY` (HH:MM, IST).

    python -m app.scheduler
"""

import logging
from collections.abc import Callable
from datetime import date, datetime

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app import cli
from app.calendar.nse import TradingCalendar
from app.config import get_settings
from app.exits.job import is_session, next_session
from app.signals.build import IST

log = logging.getLogger("jeron.scheduler")
Runner = Callable[[list[str]], int]


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


def daily_job(run: Runner = cli.main, today: Callable[[], date] = _today) -> int | None:
    day = today()
    calendar = TradingCalendar.default()
    if not is_session(calendar, day):
        log.info("%s is not a trading day: no daily run", day)
        return None
    code = run(["daily"])
    if last_session_of_week(calendar, day):
        run(["weekly", "--date", day.isoformat()])
    return code


def _safe(job: Callable[[], int | None], name: str) -> Callable[[], None]:
    def wrapped() -> None:
        try:
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
    ):
        hour, minute = _hm(at)
        scheduler.add_job(
            _safe(job, name),
            CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute, timezone=IST),
            id=name,
            name=name,
            misfire_grace_time=3600,
            coalesce=True,
        )
    return scheduler


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    scheduler = build(BlockingScheduler(timezone=IST))
    for job in scheduler.get_jobs():
        log.info("Scheduled %s: %s", job.name, job.trigger)
    scheduler.start()


if __name__ == "__main__":
    main()
