"""Watchlist alert rules and the alert text. Pure."""

from datetime import date
from decimal import Decimal

import pytest

from app.alerts.format import watch_message
from app.watchlist.calc import alert_key, is_hit, pct_to_alert

D = Decimal


def test_hits_use_the_days_high_and_low():
    assert is_hit("above", D("110"), high=D("110"), low=D("100"))
    assert not is_hit("above", D("110.05"), high=D("110"), low=D("100"))
    assert is_hit("below", D("100"), high=D("110"), low=D("99.95"))
    assert not is_hit("below", D("99"), high=D("110"), low=D("99.95"))
    with pytest.raises(ValueError):
        is_hit("sideways", D("1"), D("1"), D("1"))


def test_alert_key_changes_with_the_price():
    assert alert_key(3, "above", D("110.5000")) == "watch:3:above:110.5"
    assert alert_key(3, "above", D("110")) == "watch:3:above:110"
    assert alert_key(3, "above", D("110")) != alert_key(3, "below", D("110"))


def test_pct_to_alert():
    assert pct_to_alert(D("110"), D("100")) == D("10.00")
    assert pct_to_alert(D("95"), D("100")) == D("-5.00")
    assert pct_to_alert(D("95"), D("0")) is None


def test_message():
    text = watch_message(
        "TATASTEEL",
        "below",
        D("140"),
        date(2026, 10, 1),
        D("145"),
        D("139.5"),
        D("141"),
        "buy the dip",
        "http://x/",
    )
    assert text.splitlines()[0] == "WATCHLIST: TATASTEEL reached ₹140.00 (below)"
    assert "low ₹139.50, close ₹141.00" in text and "Note: buy the dip" in text
    assert "http://x/plan/TATASTEEL" in text and "Not a signal" in text
