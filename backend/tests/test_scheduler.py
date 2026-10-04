"""The scheduler: jobs at the right IST times, nothing on holidays, weekly after the
last session of the week."""

from datetime import date, datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app.calendar.nse import TradingCalendar
from app.scheduler import build, daily_job, last_session_of_week, preopen_job
from app.signals.build import IST


def test_jobs_run_at_ist_times_on_weekdays():
    scheduler = build(BackgroundScheduler(timezone=IST))
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert set(jobs) == {"preopen", "daily"}
    start = datetime(2025, 3, 14, 12, 0, tzinfo=IST)  # a Friday
    fire = jobs["preopen"].trigger.get_next_fire_time(None, start)
    assert (fire.date(), fire.hour, fire.minute) == (date(2025, 3, 17), 8, 30)  # Monday
    fire = jobs["daily"].trigger.get_next_fire_time(None, start)
    assert (fire.date(), fire.hour, fire.minute) == (date(2025, 3, 14), 19, 0)


def test_holidays_skip_and_weekly_after_the_last_session():
    ran: list[list[str]] = []

    def run(args):
        ran.append(args)
        return 0

    holi = date(2025, 3, 14)  # Holi, a Friday holiday in 2025
    assert daily_job(run, lambda: holi) is None and preopen_job(run, lambda: holi) is None
    assert ran == []
    calendar = TradingCalendar.default()
    assert last_session_of_week(calendar, date(2025, 3, 13))  # Thursday before Holi
    assert daily_job(run, lambda: date(2025, 3, 13)) == 0
    assert ran == [["daily"], ["weekly", "--date", "2025-03-13"]]
    ran.clear()
    daily_job(run, lambda: date(2025, 3, 12))
    assert ran == [["daily"]]
    preopen_job(run, lambda: date(2025, 3, 12))
    assert ran[-1] == ["preopen", "--date", "2025-03-12"]
