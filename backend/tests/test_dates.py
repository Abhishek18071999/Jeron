from datetime import date, datetime

from app.dates import (
    day_label,
    day_label_year,
    day_month,
    day_time_label,
    weekday_label_year,
    weekday_label_year_time,
)


def test_single_digit_day_has_no_leading_zero() -> None:
    d = date(2026, 11, 9)
    assert day_month(d) == "9 Nov"
    assert day_label(d) == "Mon 9 Nov"
    assert day_label_year(d) == "9 Nov 2026"
    assert weekday_label_year(d) == "Mon 9 Nov 2026"


def test_two_digit_day() -> None:
    d = date(2026, 11, 23)
    assert day_month(d) == "23 Nov"
    assert day_label(d) == "Mon 23 Nov"
    assert day_label_year(d) == "23 Nov 2026"
    assert weekday_label_year(d) == "Mon 23 Nov 2026"


def test_time_labels_keep_zero_padded_hours() -> None:
    t = datetime(2026, 11, 9, 8, 5)
    assert day_time_label(t) == "Mon 9 Nov 08:05"
    assert weekday_label_year_time(t) == "Mon 9 Nov 2026 08:05"


def test_datetime_gives_same_day_labels_as_date() -> None:
    t = datetime(2026, 1, 1, 19, 45)
    assert day_label(t) == "Thu 1 Jan"
    assert day_label_year(t) == "1 Jan 2026"
