"""Board meetings on a real Postgres: storing, renames, the download job, signals."""

import io
import zipfile
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.calendar.nse import TradingCalendar
from app.data import pipeline, store
from app.data.events import BoardMeeting, ResultsDate
from app.data.http import FetchError
from app.enums import Exchange
from app.models import Announcement, Instrument, SignalRecord, SymbolChange
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


def _pr_zip(bm_text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("Bm021025.txt", bm_text)
    return buffer.getvalue()


class FakeArchive:
    def __init__(self, bundles):
        self.bundles = bundles

    def pr_bundle(self, day, today):
        if day == date(2025, 10, 3):
            raise FetchError("HTTP 403")
        return self.bundles.get(day)


BM = """COMPANY NAME    SYMBOL     : BM DATE    : BM PURPOSE
Alpha Limited AAA : 14-Oct-2025 : Financial Results To consider the results
for the quarter ended September 30, 2025
Beta Limited BBB : 20-Oct-2025 : Fund Raising To consider fund raising
"""


def test_board_meetings_from_pr_bundles(empty_session):
    s = empty_session
    archive = FakeArchive({date(2025, 10, 2): _pr_zip(BM)})
    calendar = TradingCalendar.default()
    new, _, missing = pipeline.board_meetings_range(
        s, archive, calendar, date(2025, 10, 1), date(2025, 10, 3), date(2025, 10, 10)
    )
    assert new == 2 and missing == [date(2025, 10, 3)]
    assert store.results_dates(s, ["AAA", "BBB"]) == {
        "AAA": [ResultsDate(date(2025, 10, 14), date(2025, 10, 2))]
    }
    assert store.board_meetings_updated(s, pipeline.BOARD_MEETINGS_SOURCE) == date(2025, 10, 2)
    again, _, _ = pipeline.board_meetings_range(
        s, archive, calendar, date(2025, 10, 2), date(2025, 10, 2), date(2025, 10, 10)
    )
    assert again == 0


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


AN = """COMPANY NAME    SYMBOL    : ANNOUNCEMENTS
Alpha Limited AAA : Credit Rating AAA : Alpha Limited has informed the Exchange about Credit Rating
Alpha Limited AAA : Trading Window AAA : Alpha Limited informed the Exchange about Trading Window
"""


def test_announcements_from_pr_bundles(empty_session):
    s = empty_session
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("Bm021025.txt", BM)
        zf.writestr("An021025.txt", AN)
    archive = FakeArchive({date(2025, 10, 2): buffer.getvalue()})
    calendar = TradingCalendar.default()
    _, items, _ = pipeline.board_meetings_range(
        s, archive, calendar, date(2025, 10, 2), date(2025, 10, 2), date(2025, 10, 10)
    )
    assert items == 1  # the trading-window notice is routine
    (row,) = s.scalars(select(Announcement)).all()
    assert (row.symbol, row.day, row.subject) == ("AAA", date(2025, 10, 2), "Credit Rating")
