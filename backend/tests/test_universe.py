from decimal import Decimal

import pytest

from app.scan.universe import Candidate, Exclusion, UniverseRules, exclusion

RULES = UniverseRules()
CRORE = Decimal(10_000_000)


def candidate(**overrides):
    values = {
        "symbol": "GOOD",
        "traded": True,
        "series": "EQ",
        "close": Decimal("250"),
        "median_turnover": 12 * CRORE,
    }
    return Candidate(**(values | overrides))


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, None),
        ({"traded": False, "series": None, "close": None}, Exclusion.NOT_TRADED),
        ({"series": "BE"}, Exclusion.NOT_EQ_SERIES),
        ({"series": "BZ"}, Exclusion.NOT_EQ_SERIES),
        ({"close": Decimal("19.95")}, Exclusion.LOW_PRICE),
        ({"close": Decimal("20")}, None),  # the floor itself passes
        ({"median_turnover": Decimal("49999999")}, Exclusion.LOW_TURNOVER),
        ({"median_turnover": 5 * CRORE}, None),
        ({"median_turnover": None}, Exclusion.LOW_TURNOVER),
        ({"symbol": "WATCHED"}, Exclusion.GSM),
        ({"symbol": "HOT"}, Exclusion.ASM),
    ],
)
def test_rules(overrides, expected):
    assert exclusion(candidate(**overrides), RULES, gsm={"WATCHED"}, asm={"HOT"}) == expected


def test_rules_are_configurable():
    cheap = candidate(close=Decimal("15"))
    assert exclusion(cheap, UniverseRules(min_price=Decimal("10")), set(), set()) is None
