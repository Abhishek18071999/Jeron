"""The dead-man's switch: a missed daily run must be said out loud, not noticed by
the absence of a message.

Two halves, because a computer that is off can't report that it is off:

- In-process (`check_tonight`): at JERON_SCHEDULE_WATCHDOG (19:45 IST) on a trading
  day the scheduler checks that the daily summary (or the "data has not arrived" alert)
  went out for the day. If not, one alert says so, whether a run is still going, and
  what is loaded. It catches a run that crashed, hung, or was blocked before the
  summary.
- Outside (`ping_heartbeat`): when the daily run finishes, Jeron calls
  JERON_HEARTBEAT_URL (off when empty). A free monitor such as healthchecks.io, set
  to expect one ping each weekday evening, alerts by Telegram or email when the ping
  doesn't come: the laptop asleep, Docker stopped, the scheduler dead. Signing up for
  one is the owner's choice (spec section 0, rule 6); docs/runbook.md says how.
"""

import urllib.request
from collections.abc import Callable, Sequence
from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.channels import Channel, channels_from
from app.alerts.format import _day
from app.alerts.job import NOT_SET_UP, AlertOutcome, _send
from app.calendar.nse import TradingCalendar
from app.config import Settings
from app.data import store
from app.exits.job import due_session
from app.models import Alert, ScanRun
from app.scan.score import SCORE_VERSION
from app.settings_store import effective_settings
from app.signals.build import IST

Log = Callable[[str], None]
HEARTBEAT_TIMEOUT_SECONDS = 10


def _quiet(_: str) -> None:
    pass


def deadman_message(
    due: date,
    at: datetime,
    running: bool,
    newest: date | None,
    scan: str | None,
    reasons: Sequence[str] = (),
    web_url: str = "",
) -> str:
    """What the owner reads when the daily summary didn't go out. Pure."""
    lines = [
        f"JERON DID NOT FINISH TONIGHT'S RUN ({_day(due)}).",
        f"It is {at.astimezone(IST):%H:%M} IST and the daily summary has not gone out.",
        "- A run is still going: it started late or is stuck."
        if running
        else "- No run is going: it failed or never started.",
        f"- Newest prices loaded: {_day(newest)}." if newest else "- No prices are loaded.",
    ]
    if scan is None:
        lines.append(f"- No scan for {_day(due)}.")
    elif scan != "ok":
        lines.append(f"- The scan for {_day(due)} was {scan}: {'; '.join(reasons) or 'no reason'}.")
    lines += [
        "Until a run finishes there are no signals for the next session: don't act on older ones.",
        'What to do: docs/runbook.md, "No daily summary". To run it now: docker compose '
        "exec backend python -m app.cli daily",
    ]
    if web_url:
        lines.append(f"Setup: {web_url.rstrip('/')}/setup")
    return "\n".join(lines)


def run_told(session: Session, due: date) -> bool:
    """The daily summary, or the alert that the day's data had not arrived, went out."""
    return (
        session.scalar(
            select(Alert.id).where(
                Alert.key.in_([f"digest:{due}", f"late:{due}"]), Alert.status == "sent"
            )
        )
        is not None
    )


def check_tonight(
    session: Session,
    calendar: TradingCalendar,
    *,
    running: bool = False,
    now: datetime | None = None,
    settings: Settings | None = None,
    channels: Sequence[Channel] | None = None,
    log: Log = _quiet,
) -> Alert | None:
    """One "did not finish" alert (key "deadman:<date>") when the session due by `now`
    has had no daily summary; None when it has, or alerts aren't set up."""
    settings = settings or effective_settings(session)
    now = now or datetime.now(IST)
    due = due_session(calendar, now, time.fromisoformat(settings.schedule_daily))
    if run_told(session, due):
        log(f"Watchdog: the daily summary for {due} went out.")
        return None
    channels = channels_from(settings) if channels is None else channels
    if not channels:
        log(f"Watchdog: no daily summary for {due}, and {NOT_SET_UP}")
        return None
    days = store.ok_dates(session, store.NSE_BARS)
    run = session.scalar(
        select(ScanRun).where(ScanRun.trade_date == due, ScanRun.score_version == SCORE_VERSION)
    )
    text = deadman_message(
        due,
        now,
        running,
        days[-1] if days else None,
        None if run is None else run.status,
        [] if run is None else list(run.details.get("reasons", [])),
        settings.web_url,
    )
    log(text)
    return _send(
        session,
        channels,
        f"deadman:{due}",
        "deadman",
        text,
        f"JERON DID NOT RUN: {due}",
        AlertOutcome(due, "ok"),
        now,
        day=due,
    )


def ping_heartbeat(url: str, log: Log = _quiet) -> bool:
    """Tell the outside monitor the daily run finished. Never raises: a monitor that
    is down must not fail the run (it will alert on its own)."""
    if not url:
        return False
    try:
        with urllib.request.urlopen(url, timeout=HEARTBEAT_TIMEOUT_SECONDS) as response:  # noqa: S310
            ok = bool(200 <= response.status < 300)
    except OSError as exc:
        log(f"Heartbeat to the outside monitor failed: {exc}")
        return False
    log("Heartbeat sent to the outside monitor." if ok else "Heartbeat refused by the monitor.")
    return ok
