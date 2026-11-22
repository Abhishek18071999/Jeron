"""Portable date labels for messages (pure).

glibc's strftime has a flag for the day without a leading zero; Windows' does not and
raises. These helpers put the day in by hand so the same text comes out on both:
"Mon 9 Nov", never "Mon 09 Nov". Use them instead of
that flag.
"""

from __future__ import annotations

from datetime import date, datetime


def day_month(d: date) -> str:
    """ "9 Nov"."""
    return f"{d.day} {d:%b}"


def day_label(d: date) -> str:
    """ "Mon 9 Nov"."""
    return f"{d:%a} {d.day} {d:%b}"


def day_label_year(d: date) -> str:
    """ "9 Nov 2026"."""
    return f"{d.day} {d:%b %Y}"


def weekday_label_year(d: date) -> str:
    """ "Mon 9 Nov 2026"."""
    return f"{d:%a} {d.day} {d:%b %Y}"


def day_time_label(t: datetime) -> str:
    """ "Mon 9 Nov 14:05"."""
    return f"{day_label(t)} {t:%H:%M}"


def weekday_label_year_time(t: datetime) -> str:
    """ "Mon 9 Nov 2026 14:05"."""
    return f"{weekday_label_year(t)} {t:%H:%M}"
