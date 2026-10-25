"""The day's NSE data did not arrive (NSE late or down): tell me once, and say when
Jeron tries again (the scheduler's `daily-retry` job). Nothing is filled in."""

from collections.abc import Callable, Sequence
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.alerts.channels import Channel
from app.alerts.job import send_data_late
from app.calendar.nse import TradingCalendar
from app.config import Settings
from app.data import store
from app.exits.job import due_session
from app.settings_store import effective_settings


def data_late(
    session: Session,
    calendar: TradingCalendar,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
    channels: Sequence[Channel] | None = None,
    log: Callable[[str], None] = lambda _: None,
) -> bool:
    """After the daily update: True (and one alert) when the newest session the daily
    run should have by `now` is not loaded."""
    settings = settings or effective_settings(session)
    now = now or datetime.now(ZoneInfo(settings.timezone))
    due = due_session(calendar, now, time.fromisoformat(settings.schedule_daily))
    days = store.ok_dates(session, store.NSE_BARS)
    newest = days[-1] if days else None
    if newest is not None and newest >= due:
        return False
    retry = time.fromisoformat(settings.schedule_daily_retry)
    local = now.astimezone(ZoneInfo(settings.timezone))
    retry_at = (
        settings.schedule_daily_retry if due == local.date() and local.time() < retry else None
    )
    log(f"NSE data for {due} has not arrived (newest loaded: {newest or 'none'}).")
    alert = send_data_late(
        session, due, newest, retry_at=retry_at, settings=settings, channels=channels, now=now
    )
    if alert is not None:
        log(f"  Alert {alert.status} ({alert.channel}).")
    return True
