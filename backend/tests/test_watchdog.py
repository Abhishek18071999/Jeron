"""The dead-man's switch (docs/runbook.md): a missed daily run is said out loud."""

from datetime import date, datetime

from app.alerts.watchdog import check_tonight, deadman_message, ping_heartbeat
from app.calendar.nse import TradingCalendar
from app.config import Settings
from app.models import Alert
from app.scheduler import watchdog_job
from app.signals.build import IST
from tests.conftest import requires_db
from tests.test_alerts_db import FakeChannel
from tests.test_alerts_db import empty_session as empty_session  # noqa: F401 - the fixture

MONDAY = date(2026, 10, 26)
AT = datetime(2026, 10, 26, 19, 45, tzinfo=IST)


def test_message_says_what_is_known():
    text = deadman_message(MONDAY, AT, False, date(2026, 10, 23), "blocked", ["quality FAIL"])
    assert text.startswith("JERON DID NOT FINISH TONIGHT'S RUN (Mon 26 Oct 2026)")
    assert "19:45 IST" in text
    assert "No run is going" in text
    assert "Newest prices loaded: Fri 23 Oct 2026" in text
    assert "was blocked: quality FAIL" in text
    assert "docs/runbook.md" in text
    still = deadman_message(MONDAY, AT, True, None, None, web_url="http://pc:3000")
    assert "still going" in still and "No prices are loaded" in still
    assert "No scan for Mon 26 Oct 2026" in still
    assert still.endswith("Setup: http://pc:3000/setup")


def test_scheduler_runs_the_watchdog_on_trading_days_only():
    ran: list[list[str]] = []

    def run(args):
        ran.append(args)
        return 0

    assert watchdog_job(run, lambda: date(2026, 10, 2), lambda: False) is None  # Gandhi Jayanti
    assert ran == []
    watchdog_job(run, lambda: MONDAY, lambda: False)
    watchdog_job(run, lambda: MONDAY, lambda: True)
    assert ran == [["watchdog"], ["watchdog", "--running"]]


def test_heartbeat_off_without_a_url_and_never_raises():
    assert ping_heartbeat("") is False
    said: list[str] = []
    assert ping_heartbeat("http://127.0.0.1:9/never", log=said.append) is False
    assert said and "failed" in said[0]


@requires_db
def test_watchdog_alerts_once_when_the_summary_did_not_go_out(empty_session):  # noqa: F811
    s = empty_session
    channel = FakeChannel()
    settings = Settings()
    calendar = TradingCalendar.default()

    def check():
        return check_tonight(s, calendar, now=AT, settings=settings, channels=[channel])

    alert = check()
    assert alert is not None and alert.status == "sent" and alert.key == "deadman:2026-10-26"
    assert channel.sent[0][0] == "JERON DID NOT RUN: 2026-10-26"
    check()  # a second check sends nothing new
    assert len(channel.sent) == 1


@requires_db
def test_watchdog_is_quiet_after_the_summary_or_the_late_alert(empty_session):  # noqa: F811
    s = empty_session
    channel = FakeChannel()
    calendar = TradingCalendar.default()
    for key in ("digest:2026-10-26", "late:2026-10-27"):
        s.add(Alert(key=key, kind=key.split(":")[0], text="-", status="sent", attempts=1))
    s.commit()
    assert check_tonight(s, calendar, now=AT, settings=Settings(), channels=[channel]) is None
    tuesday = datetime(2026, 10, 27, 19, 45, tzinfo=IST)
    assert check_tonight(s, calendar, now=tuesday, settings=Settings(), channels=[channel]) is None
    # Before the daily time the due session is the one before: Monday, told.
    morning = datetime(2026, 10, 27, 9, 0, tzinfo=IST)
    assert check_tonight(s, calendar, now=morning, settings=Settings(), channels=[channel]) is None
    assert channel.sent == []
