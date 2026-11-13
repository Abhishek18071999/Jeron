"""The scheduler: jobs at the right IST times, nothing on holidays, weekly after the
last session of the week."""

from datetime import date, datetime, time

from apscheduler.schedulers.background import BackgroundScheduler

from app.calendar.nse import TradingCalendar
from app.exits.job import due_session
from app.scheduler import (
    build,
    catch_up,
    daily_job,
    last_session_of_week,
    preopen_job,
    retry_job,
)
from app.signals.build import IST


def test_jobs_run_at_ist_times_on_weekdays():
    scheduler = build(BackgroundScheduler(timezone=IST))
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert set(jobs) == {"preopen", "daily", "daily-retry", "watchdog", "autopilot"}
    start = datetime(2025, 3, 14, 12, 0, tzinfo=IST)  # a Friday
    fire = jobs["preopen"].trigger.get_next_fire_time(None, start)
    assert (fire.date(), fire.hour, fire.minute) == (date(2025, 3, 17), 8, 30)  # Monday
    fire = jobs["daily"].trigger.get_next_fire_time(None, start)
    assert (fire.date(), fire.hour, fire.minute) == (date(2025, 3, 14), 19, 0)
    fire = jobs["daily-retry"].trigger.get_next_fire_time(None, start)
    assert (fire.date(), fire.hour, fire.minute) == (date(2025, 3, 14), 21, 30)


def test_holidays_skip_and_weekly_after_the_last_session():
    ran: list[list[str]] = []

    def run(args):
        ran.append(args)
        return 0

    def seven(day):
        return lambda: datetime(day.year, day.month, day.day, 19, 0, tzinfo=IST)

    holi = date(2025, 3, 14)  # Holi, a Friday holiday in 2025
    thursday = date(2025, 3, 13)
    # Holi evening: Thursday, the newest session, was scanned on Thursday evening.
    assert daily_job(run, seven(holi), lambda: thursday) is None
    assert preopen_job(run, lambda: holi) is None
    assert ran == []
    calendar = TradingCalendar.default()
    assert last_session_of_week(calendar, thursday)  # Thursday before Holi
    assert daily_job(run, seven(thursday), lambda: date(2025, 3, 12)) == 0
    assert ran == [
        ["daily", "--date", "2025-03-13"],
        ["weekly", "--date", "2025-03-13"],
        ["paper-review"],
        ["proposal-validate", "--limit", "2"],
    ]
    ran.clear()
    daily_job(run, seven(date(2025, 3, 12)), lambda: date(2025, 3, 11))
    assert ran == [["daily", "--date", "2025-03-12"]]
    preopen_job(run, lambda: date(2025, 3, 12))
    assert ran[-1] == ["preopen", "--date", "2025-03-12"]


def test_a_late_daily_run_is_for_the_evening_it_missed():
    """13 Nov 2026: the computer slept through Thursday's 19:00 run and woke at 03:25 on
    Friday, inside the job's grace. The run is Thursday's: Friday hasn't traded, and a
    run for it stored a FAIL report, a blocked scan and a summary before the open, and
    sent the weekly summary a session early."""
    ran: list[list[str]] = []

    def run(args):
        ran.append(args)
        return 0

    woke = lambda: datetime(2026, 11, 13, 3, 25, tzinfo=IST)  # noqa: E731 - a Friday
    assert daily_job(run, woke, lambda: date(2026, 11, 11)) == 0
    assert ran == [["daily", "--date", "2026-11-12"]]  # Thursday, and no weekly yet

    # Friday evening on time: Friday's run, then the weekly one.
    ran.clear()
    friday = lambda: datetime(2026, 11, 13, 19, 0, tzinfo=IST)  # noqa: E731
    assert daily_job(run, friday, lambda: date(2026, 11, 12)) == 0
    assert ran[0] == ["daily", "--date", "2026-11-13"]
    assert ran[1] == ["weekly", "--date", "2026-11-13"]

    # Friday already scanned by hand before 19:00: no second run, but still the weekly.
    ran.clear()
    assert daily_job(run, friday, lambda: date(2026, 11, 13)) is None
    assert ran[0] == ["weekly", "--date", "2026-11-13"]

    # Slept through Friday evening, woke on Saturday morning: still Friday's run.
    ran.clear()
    saturday = lambda: datetime(2026, 11, 14, 6, 0, tzinfo=IST)  # noqa: E731
    assert daily_job(run, saturday, lambda: date(2026, 11, 12)) == 0
    assert ran[0] == ["daily", "--date", "2026-11-13"]
    assert ran[1] == ["weekly", "--date", "2026-11-13"]


def test_catch_up_after_the_computer_was_off():
    ran: list[list[str]] = []

    def run(args):
        ran.append(args)
        return 0

    def at(day, hour, minute=0):
        return lambda: datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)

    # Off over Monday evening (19 Oct 2026); on at 08:45 Wednesday, Dussehra was Tuesday.
    wed = date(2026, 10, 21)
    done = catch_up(run, at(wed, 8, 45), lambda: date(2026, 10, 16))
    assert done == ["daily", "preopen"]
    assert ran == [["daily", "--date", "2026-10-19"], ["preopen", "--date", "2026-10-21"]]

    # On at 03:25 on a Friday with Thursday unscanned: Thursday's run, not Friday's.
    ran.clear()
    assert catch_up(run, at(date(2026, 11, 13), 3, 25), lambda: date(2026, 11, 11)) == ["daily"]
    assert ran == [["daily", "--date", "2026-11-12"]]

    # Monday's scan exists, and it is evening before the daily time: nothing to do.
    ran.clear()
    assert catch_up(run, at(wed, 18, 0), lambda: date(2026, 10, 19)) == []

    # Off on Friday evening, on Saturday: the daily run and the weekly one for Friday.
    ran.clear()
    assert catch_up(run, at(date(2026, 10, 24), 10), lambda: date(2026, 10, 22)) == [
        "daily",
        "weekly",
    ]
    assert ran[-3:] == [
        ["weekly", "--date", "2026-10-23"],
        ["paper-review"],
        ["proposal-validate", "--limit", "2"],
    ]

    # A new install with no scan yet waits for the backfill.
    assert catch_up(run, at(date(2026, 10, 24), 10), lambda: None) == []


def test_due_session():
    calendar = TradingCalendar.default()
    seven = time(19, 0)

    def at(day, hour, minute=0):
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)

    mon = date(2026, 10, 19)
    assert due_session(calendar, at(mon, 19, 0), seven) == mon
    assert due_session(calendar, at(mon, 18, 59), seven) == date(2026, 10, 16)  # Friday
    # Tuesday 20 Oct 2026 is Dussehra: Monday is still the newest session that evening.
    assert due_session(calendar, at(date(2026, 10, 20), 21), seven) == mon
    assert due_session(calendar, at(date(2026, 10, 25), 10), seven) == date(2026, 10, 23)


def test_retry_only_when_the_scan_is_missing():
    ran: list[list[str]] = []

    def run(args):
        ran.append(args)
        return 0

    evening = lambda: datetime(2026, 10, 23, 21, 30, tzinfo=IST)  # noqa: E731 - a Friday
    assert retry_job(run, evening, lambda: date(2026, 10, 23)) is None  # scanned at 19:00
    assert retry_job(run, evening, lambda: None) is None  # a new install: the autopilot
    assert ran == []
    assert retry_job(run, evening, lambda: date(2026, 10, 22)) == 0  # Friday's data was late
    assert ran == [["daily", "--date", "2026-10-23"]]
