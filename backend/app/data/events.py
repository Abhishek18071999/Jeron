"""Board meetings and the results blackout (spec sections 2 and 5).

A company's board meeting to approve financial results is announced in advance on NSE.
No new entry may fill from 3 sessions before the results date through the results date
itself; entries resume the session after. A meeting counts only from the day it was
announced, so a backtest never knows a date before the market did.

Pure module: the database layer passes in the meetings and the sessions.
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# Sessions before the results date during which no entry may fill.
BLACKOUT_SESSIONS_BEFORE = 3
# How far ahead a signal's event-risk line looks for the next results date.
EVENT_LOOKAHEAD_DAYS = 30
# Upcoming meetings older than this can't rule out a results date.
STALE_AFTER_DAYS = 7

_RESULTS = re.compile(r"financial\s+result|quarterly\s+result|audited\s+result", re.I)


@dataclass(frozen=True)
class BoardMeeting:
    symbol: str
    meeting_date: date
    purpose: str
    description: str = ""
    # When NSE published the intimation; None if not known.
    announced: datetime | None = None

    @property
    def is_results(self) -> bool:
        return is_results(self.purpose, self.description)


@dataclass(frozen=True)
class ResultsDate:
    meeting_date: date
    known_from: date | None  # the day it was announced; None = treat as always known


def is_results(purpose: str, description: str = "") -> bool:
    return bool(_RESULTS.search(f"{purpose} {description}"))


def _date(text: str) -> date | None:
    text = text.strip()
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _datetime(text: str) -> datetime | None:
    text = text.strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    day = _date(text)
    return datetime(day.year, day.month, day.day) if day else None


def _field(row: Mapping[str, object], *names: str) -> str:
    lowered = {k.strip().lower(): v for k, v in row.items()}
    for name in names:
        value = lowered.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def parse_board_meetings(rows: Iterable[Mapping[str, object]]) -> list[BoardMeeting]:
    """Meetings from NSE's board-meeting list, as JSON objects (the API) or CSV rows
    (the download on NSE's site). Rows without a symbol or a valid date are skipped."""
    meetings: dict[tuple[str, date, str], BoardMeeting] = {}
    for row in rows:
        symbol = _field(row, "bm_symbol", "symbol").upper()
        day = _date(_field(row, "bm_date", "board meeting date", "meeting date", "date"))
        if not symbol or day is None:
            continue
        purpose = _field(row, "bm_purpose", "purpose")
        description = _field(row, "bm_desc", "details", "description")
        announced = _datetime(
            _field(row, "bm_timestamp", "broadcast date/time", "broadcast date", "intimation date")
        )
        meeting = BoardMeeting(symbol, day, purpose, description, announced)
        key = (symbol, day, purpose)
        old = meetings.get(key)
        # Keep the earliest announcement of a meeting NSE lists twice.
        if old is None or (announced and (old.announced is None or announced < old.announced)):
            meetings[key] = meeting
    return sorted(meetings.values(), key=lambda m: (m.meeting_date, m.symbol, m.purpose))


def parse_board_meetings_json(content: bytes) -> list[BoardMeeting]:
    data = json.loads(content)
    if isinstance(data, dict):
        data = data.get("data", [])
    if not isinstance(data, list):
        raise ValueError("NSE board meetings: expected a list")
    return parse_board_meetings(row for row in data if isinstance(row, dict))


def results_dates(meetings: Iterable[BoardMeeting]) -> dict[str, list[ResultsDate]]:
    """Results meetings per symbol, oldest first."""
    found: dict[str, dict[date, date | None]] = {}
    for m in meetings:
        if not m.is_results:
            continue
        known = m.announced.date() if m.announced else None
        dates = found.setdefault(m.symbol, {})
        if m.meeting_date not in dates:
            dates[m.meeting_date] = known
        else:
            old = dates[m.meeting_date]
            dates[m.meeting_date] = None if old is None or known is None else min(old, known)
    return {
        symbol: [ResultsDate(d, k) for d, k in sorted(dates.items())]
        for symbol, dates in found.items()
    }


def _sessions_ahead(days: Sequence[date], extra: int = 10) -> list[date]:
    """The sessions, then `extra` weekdays after the last one (an approximation for the
    days the data doesn't reach yet; holidays there are not known)."""
    out = list(days)
    day = days[-1] if days else date.min
    while len(out) < len(days) + extra:
        day += timedelta(days=1)
        if day.weekday() < 5:
            out.append(day)
    return out


def blackout_signal_days(
    days: Sequence[date],
    results: Sequence[ResultsDate],
    sessions_before: int = BLACKOUT_SESSIONS_BEFORE,
) -> set[int]:
    """Indexes into `days` of the sessions whose signals must be skipped: those whose
    entry (the next session) would fill within `sessions_before` sessions before a
    results date, or on it. A date counts only from the day it was announced."""
    if not days:
        return set()
    sessions = _sessions_ahead(days, extra=sessions_before + 10)
    blocked: set[int] = set()
    for r in results:
        # The first session on or after the meeting date.
        idx = next((i for i, d in enumerate(sessions) if d >= r.meeting_date), None)
        if idx is None:
            continue
        for fill in range(max(idx - sessions_before, 1), idx + 1):
            signal = fill - 1
            if signal >= len(days):
                continue
            if r.known_from is not None and days[signal] < r.known_from:
                continue
            blocked.add(signal)
    return blocked


def next_results(results: Sequence[ResultsDate], day: date) -> ResultsDate | None:
    """The first results date on or after `day` that was known by `day`."""
    for r in results:
        if r.meeting_date >= day and (r.known_from is None or r.known_from <= day):
            return r
    return None


def event_risk(
    results: Sequence[ResultsDate] | None, day: date, updated: date | None = None
) -> str:
    """The signal's event-risk line. `updated` is the last day upcoming meetings were
    downloaded; a calendar older than a week can't rule out a results date."""
    if results is None:
        return "Results calendar not loaded: event risk not checked."
    stale = updated is None or (day - updated).days > STALE_AFTER_DAYS
    upcoming = next_results(results, day)
    if upcoming is None or (upcoming.meeting_date - day).days > EVENT_LOOKAHEAD_DAYS:
        if stale:
            when = f"on {updated:%d %b %Y}" if updated else "never"
            return (
                f"Results calendar last updated {when}: a results date may be missing. "
                "Check the company's announcements before buying."
            )
        return f"No results meeting announced in the next {EVENT_LOOKAHEAD_DAYS} days."
    return (
        f"Results board meeting on {upcoming.meeting_date:%d %b %Y}: no new entry from "
        f"{BLACKOUT_SESSIONS_BEFORE} sessions before it until the session after; expect a "
        "gap on the day after."
    )
