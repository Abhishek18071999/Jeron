from datetime import date

import pytest

from app.calendar.nse import (
    CalendarEntry,
    TradingCalendar,
    UnknownCalendarYearError,
    load_entries,
)


@pytest.fixture
def cal() -> TradingCalendar:
    return TradingCalendar(
        [
            CalendarEntry(date(2025, 8, 15), "holiday", "Independence Day", True),
            CalendarEntry(date(2025, 2, 1), "special_session", "Budget", True),
        ]
    )


def test_weekday_is_trading_day(cal):
    assert cal.is_trading_day(date(2025, 8, 14))


def test_weekend_is_not_trading_day(cal):
    assert not cal.is_trading_day(date(2025, 8, 16))
    assert not cal.is_trading_day(date(2025, 8, 17))


def test_holiday_is_not_trading_day(cal):
    assert not cal.is_trading_day(date(2025, 8, 15))


def test_special_weekend_session_is_trading_day(cal):
    assert cal.is_trading_day(date(2025, 2, 1))


def test_next_and_previous_skip_holiday_and_weekend(cal):
    assert cal.next_trading_day(date(2025, 8, 14)) == date(2025, 8, 18)
    assert cal.previous_trading_day(date(2025, 8, 18)) == date(2025, 8, 14)


def test_trading_days_range_is_inclusive(cal):
    days = list(cal.trading_days(date(2025, 8, 11), date(2025, 8, 18)))
    assert days == [
        date(2025, 8, 11),
        date(2025, 8, 12),
        date(2025, 8, 13),
        date(2025, 8, 14),
        date(2025, 8, 18),
    ]


def test_unknown_year_raises(cal):
    with pytest.raises(UnknownCalendarYearError):
        cal.is_trading_day(date(2030, 1, 1))


def test_bundled_holiday_file_is_valid():
    entries = load_entries()
    assert entries
    assert {e.kind for e in entries} <= {"holiday", "special_session"}
    for e in entries:
        if e.kind == "holiday":
            assert e.day.weekday() < 5, f"{e.day} holiday falls on a weekend"
        else:
            assert e.day.weekday() >= 5, f"{e.day} special session falls on a weekday"
    TradingCalendar.default()
