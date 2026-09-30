"""NSE trading calendar.

Trading days are weekdays that are not exchange holidays, plus special weekend
sessions (e.g. Union Budget day). Years not present in the holiday file raise
UnknownCalendarYearError instead of silently treating every weekday as a trading day.
"""

import csv
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

DEFAULT_HOLIDAY_FILE = Path(__file__).with_name("nse_holidays.csv")


class UnknownCalendarYearError(LookupError):
    pass


@dataclass(frozen=True)
class CalendarEntry:
    day: date
    kind: str
    description: str
    verified: bool


def load_entries(path: Path = DEFAULT_HOLIDAY_FILE) -> list[CalendarEntry]:
    with path.open(newline="") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        return [
            CalendarEntry(
                day=date.fromisoformat(r["date"]),
                kind=r["kind"],
                description=r["description"],
                verified=r["verified"].strip().lower() == "yes",
            )
            for r in rows
        ]


class TradingCalendar:
    def __init__(self, entries: Iterable[CalendarEntry]) -> None:
        entries = list(entries)
        self.holidays = {e.day for e in entries if e.kind == "holiday"}
        self.special_sessions = {e.day for e in entries if e.kind == "special_session"}
        self.years = {e.day.year for e in entries}

    @classmethod
    def default(cls) -> "TradingCalendar":
        return cls(load_entries())

    def _check_year(self, day: date) -> None:
        if day.year not in self.years:
            raise UnknownCalendarYearError(
                f"No NSE holiday data for {day.year}; add it to nse_holidays.csv"
            )

    def is_trading_day(self, day: date) -> bool:
        self._check_year(day)
        if day in self.special_sessions:
            return True
        return day.weekday() < 5 and day not in self.holidays

    def trading_days(self, start: date, end: date) -> Iterator[date]:
        """Trading days from start to end, both inclusive."""
        day = start
        while day <= end:
            if self.is_trading_day(day):
                yield day
            day += timedelta(days=1)

    def next_trading_day(self, day: date) -> date:
        day += timedelta(days=1)
        while not self.is_trading_day(day):
            day += timedelta(days=1)
        return day

    def previous_trading_day(self, day: date) -> date:
        day -= timedelta(days=1)
        while not self.is_trading_day(day):
            day -= timedelta(days=1)
        return day
