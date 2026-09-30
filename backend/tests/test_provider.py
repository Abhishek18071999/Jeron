from datetime import date
from decimal import Decimal

import pytest

from app.data.memory import InMemoryProvider
from app.data.provider import Bar, BarValidationError, DataProvider, validate_bar


def bar(symbol="INFY", day=date(2025, 8, 14), o="100", h="105", lo="99", c="104", v=1000):
    return Bar(symbol, day, Decimal(o), Decimal(h), Decimal(lo), Decimal(c), v)


def test_valid_bar_passes():
    validate_bar(bar())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"lo": "0"},
        {"h": "103"},  # high below close
        {"lo": "101"},  # low above open
        {"v": -1},
    ],
)
def test_impossible_bars_are_rejected(kwargs):
    with pytest.raises(BarValidationError):
        validate_bar(bar(**kwargs))


def test_in_memory_provider_satisfies_protocol():
    assert isinstance(InMemoryProvider(), DataProvider)


def test_in_memory_provider_queries():
    d1, d2 = date(2025, 8, 13), date(2025, 8, 14)
    provider = InMemoryProvider(
        [bar("TCS", d2), bar("INFY", d2), bar("INFY", d1)],
    )
    assert [b.symbol for b in provider.daily_bars(d2)] == ["INFY", "TCS"]
    assert [b.trade_date for b in provider.history("INFY", d1, d2)] == [d1, d2]
    assert provider.history("INFY", d2, d2) == [bar("INFY", d2)]


def test_in_memory_provider_rejects_bad_bar():
    with pytest.raises(BarValidationError):
        InMemoryProvider([bar(h="1")])
