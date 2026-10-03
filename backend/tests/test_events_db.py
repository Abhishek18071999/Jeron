"""Board meetings on a real Postgres: storing, renames, the download job, signals."""

import json
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.data import pipeline, store
from app.data.events import BoardMeeting, ResultsDate
from app.data.http import FetchError
from app.enums import Exchange
from app.models import Instrument, SignalRecord, SymbolChange
from tests.conftest import requires_db
from tests.test_alerts_db import _signal_day
from tests.test_alerts_db import empty_session as empty_session  # noqa: F401 - the fixture
from tests.test_backtest_db import DAYS
from tests.test_backtest_db import session as session  # noqa: F401 - the fixture

pytestmark = requires_db

RESULTS = "Financial Results"


def test_store_meetings_once_and_follow_renames(empty_session):
    s = empty_session
    s.add(SymbolChange(old_symbol="ZOMATO", new_symbol="ETERNAL", change_date=date(2025, 4, 9)))
    meetings = [
        BoardMeeting("ZOMATO", date(2025, 1, 20), RESULTS, announced=datetime(2025, 1, 6, 18)),
        BoardMeeting("ETERNAL", date(2025, 7, 21), RESULTS),
        BoardMeeting("ETERNAL", date(2025, 8, 1), "Fund Raising"),
    ]
    assert store.save_board_meetings(s, meetings, "test") == 3
    assert store.save_board_meetings(s, meetings, "test") == 0  # never changed or doubled
    s.commit()
    assert store.results_dates(s, ["ETERNAL"]) == {
        "ETERNAL": [
            ResultsDate(date(2025, 1, 20), date(2025, 1, 6)),
            ResultsDate(date(2025, 7, 21), None),
        ]
    }
    assert store.board_meetings_loaded(s)


class FakeSite:
    def __init__(self, fail_from: date | None = None):
        self.fail_from = fail_from
        self.asked: list[tuple[date, date]] = []

    def board_meetings(self, start, end):
        self.asked.append((start, end))
        if self.fail_from and start >= self.fail_from:
            raise FetchError("HTTP 403")
        row = {"bm_symbol": "AAA", "bm_date": f"{start:%d-%b-%Y}", "bm_purpose": RESULTS}
        return json.dumps([row]).encode()


def test_download_job_marks_the_calendar_up_to_date(empty_session):
    s, today = empty_session, date(2026, 10, 3)
    site = FakeSite(fail_from=date(2026, 11, 1))
    seen, new, failed = pipeline.fetch_board_meetings(
        s, site, date(2026, 10, 1), date(2026, 11, 15), today
    )
    assert (seen, new) == (1, 1) and failed == [(date(2026, 11, 1), date(2026, 11, 15))]
    assert site.asked[0] == (date(2026, 10, 1), date(2026, 10, 31))
    # Incomplete: not marked as up to date.
    assert store.board_meetings_updated(s, pipeline.BOARD_MEETINGS_SOURCE) is None
    pipeline.fetch_board_meetings(s, FakeSite(), date(2026, 10, 1), date(2026, 10, 31), today)
    assert store.board_meetings_updated(s, pipeline.BOARD_MEETINGS_SOURCE) == today


def test_signals_name_the_next_results_date(session):
    meeting_day = DAYS[-1] + timedelta(days=10)
    symbols = session.scalars(
        select(Instrument.symbol).where(Instrument.exchange == Exchange.NSE)
    ).all()
    store.save_board_meetings(
        session, [BoardMeeting(sym, meeting_day, RESULTS) for sym in symbols], "test"
    )
    session.commit()
    day = _signal_day(session, live=False)
    payloads = session.scalars(
        select(SignalRecord.payload).where(SignalRecord.signal_date == day)
    ).all()
    assert payloads
    for p in payloads:
        assert f"Results board meeting on {meeting_day:%d %b %Y}" in p["event_risk"]
