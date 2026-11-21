"""The daily run's closing line (app/cli.py): how long each step took."""

from app.cli import duration, timings_line


def test_durations_read_plainly():
    assert duration(0.4) == "0s"
    assert duration(8.2) == "8s"
    assert duration(185) == "3m 05s"
    assert duration(3599.6) == "1h 00m"
    assert duration(3725) == "1h 02m"


def test_the_daily_line_names_where_the_time_went():
    steps = [("prices, cross-check and quality", 760.0), ("scan", 8.0), ("paper", 25.0)]
    assert timings_line(steps) == (
        "Took 13m 13s: prices, cross-check and quality 12m 40s, scan 8s, paper 25s."
    )
    assert timings_line([]) == "Took 0s."
