import json
from datetime import date, datetime

from app.data.events import (
    BoardMeeting,
    ResultsDate,
    blackout_signal_days,
    event_risk,
    next_results,
    parse_board_meetings,
    parse_board_meetings_json,
    results_dates,
)

NSE_JSON = [
    {
        "bm_symbol": "RELIANCE",
        "bm_date": "17-Oct-2025",
        "bm_purpose": "Financial Results/Dividend",
        "bm_desc": "To consider and approve the financial results for the period ended "
        "September 30, 2025",
        "sm_name": "Reliance Industries Limited",
        "bm_timestamp": "10-Oct-2025 19:34:12",
    },
    {
        "bm_symbol": "TCS",
        "bm_date": "09-Oct-2025",
        "bm_purpose": "Fund Raising",
        "bm_desc": "To consider raising funds",
        "bm_timestamp": "01-Oct-2025 10:00:00",
    },
    {"bm_symbol": "", "bm_date": "09-Oct-2025", "bm_purpose": "Financial Results"},
    {"bm_symbol": "BAD", "bm_date": "not a date", "bm_purpose": "Financial Results"},
]


def test_parse_nse_json():
    meetings = parse_board_meetings_json(json.dumps(NSE_JSON).encode())
    assert [(m.symbol, m.meeting_date, m.is_results) for m in meetings] == [
        ("TCS", date(2025, 10, 9), False),
        ("RELIANCE", date(2025, 10, 17), True),
    ]
    assert meetings[1].announced == datetime(2025, 10, 10, 19, 34, 12)
    wrapped = parse_board_meetings_json(json.dumps({"data": NSE_JSON}).encode())
    assert len(wrapped) == 2


def test_parse_csv_rows_and_duplicates():
    rows = [
        {
            "SYMBOL": "infy",
            "PURPOSE": "Financial Results",
            "BOARD MEETING DATE": "16-10-2025",
            "BROADCAST DATE/TIME": "09-Oct-2025 18:00:00",
        },
        {
            "SYMBOL": "INFY",
            "PURPOSE": "Financial Results",
            "BOARD MEETING DATE": "16-10-2025",
            "BROADCAST DATE/TIME": "01-Oct-2025 18:00:00",
        },
    ]
    (m,) = parse_board_meetings(rows)
    assert m.symbol == "INFY" and m.is_results
    assert m.announced == datetime(2025, 10, 1, 18, 0)  # the earliest announcement


def test_results_dates_keep_the_earliest_known_day():
    meetings = [
        BoardMeeting("A", date(2025, 1, 20), "Financial Results", announced=datetime(2025, 1, 10)),
        BoardMeeting(
            "A", date(2025, 1, 20), "Financial Results/Dividend", announced=datetime(2025, 1, 8)
        ),
        BoardMeeting("A", date(2025, 2, 1), "Dividend"),
    ]
    assert results_dates(meetings) == {"A": [ResultsDate(date(2025, 1, 20), date(2025, 1, 8))]}


DAYS = [date(2025, 1, d) for d in (13, 14, 15, 16, 17, 20, 21, 22)]  # Mon 13 .. Wed 22


def test_blackout_covers_three_sessions_before_and_the_day():
    # Results on Mon 20 (index 5): fills on 15, 16, 17, 20 are blocked, so signals on
    # 14, 15, 16, 17 (indexes 1-4) are skipped. A signal on the 20th fills on the 21st.
    assert blackout_signal_days(DAYS, [ResultsDate(date(2025, 1, 20), None)]) == {1, 2, 3, 4}
    # Announced on the 16th: signals before it didn't know.
    known = [ResultsDate(date(2025, 1, 20), date(2025, 1, 16))]
    assert blackout_signal_days(DAYS, known) == {3, 4}
    # A meeting on a holiday counts from the next session.
    assert blackout_signal_days(DAYS, [ResultsDate(date(2025, 1, 19), None)]) == {1, 2, 3, 4}


def test_blackout_reaches_past_the_last_day():
    # Results on Fri 24, two sessions after the last one: fills from Tue 21 are blocked.
    future = [ResultsDate(date(2025, 1, 24), None)]
    assert blackout_signal_days(DAYS, future) == {5, 6, 7}


def test_event_risk_lines():
    day = date(2025, 1, 14)
    results = [ResultsDate(date(2025, 1, 20), date(2025, 1, 10))]
    assert event_risk(None, day).startswith("Results calendar not loaded")
    assert "20 Jan 2025" in event_risk(results, day, updated=day)
    assert next_results(results, date(2025, 1, 9)) is None  # not announced yet
    assert event_risk([], day, updated=day).startswith("No results meeting")
    assert "may be missing" in event_risk([], day, updated=date(2025, 1, 1))
    assert "never" in event_risk([], day, updated=None)
