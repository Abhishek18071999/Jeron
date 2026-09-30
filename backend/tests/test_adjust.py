from datetime import date
from decimal import Decimal

from app.data.adjust import adjust_bars, build_adjustments, price_confirms, price_factor
from app.data.provider import CorporateActionRecord
from app.enums import CorporateActionType
from tests.helpers import bar

D1, D2, D3 = date(2024, 10, 24), date(2024, 10, 25), date(2024, 10, 28)
# RELIANCE around its 1:1 bonus (real closes).
BARS = [
    bar("RELIANCE", D1, 2670.55, 2687.40, 2646.25, 2679.60, 11077967),
    bar("RELIANCE", D2, 2687.00, 2688.70, 2644.00, 2655.70, 9298748),
    bar("RELIANCE", D3, 1337.00, 1353.00, 1322.10, 1334.35, 10824350),
]
BONUS = CorporateActionRecord(
    "RELIANCE", D3, CorporateActionType.BONUS, Decimal(2), Decimal(1), raw_text="BONUS 1:1"
)


def test_price_factors():
    assert price_factor(BONUS) == Decimal("0.5")
    split = CorporateActionRecord("X", D3, CorporateActionType.SPLIT, Decimal(10), Decimal(2))
    assert price_factor(split) == Decimal("0.2")
    dividend = CorporateActionRecord("X", D3, CorporateActionType.DIVIDEND, amount=Decimal(5))
    assert price_factor(dividend, Decimal(100)) is None  # dividends off by default
    assert price_factor(dividend, Decimal(100), include_dividends=True) == Decimal("0.95")
    rights = CorporateActionRecord("X", D3, CorporateActionType.RIGHTS, Decimal(1), Decimal(5))
    assert price_factor(rights) is None


def test_adjusted_series_has_no_gap_and_raw_is_untouched():
    adjusted = adjust_bars(BARS, build_adjustments(BARS, [BONUS]))
    assert [a.close for a in adjusted] == [
        Decimal("1339.8000"),
        Decimal("1327.8500"),
        Decimal("1334.3500"),
    ]
    assert [a.volume for a in adjusted] == [22155934, 18597496, 10824350]
    assert [a.factor for a in adjusted] == [Decimal("0.5"), Decimal("0.5"), Decimal(1)]
    assert adjusted[0].raw.close == Decimal("2679.60")


def test_dividend_adjustment_only_when_asked():
    dividend = CorporateActionRecord(
        "RELIANCE", D2, CorporateActionType.DIVIDEND, amount=Decimal("26.796"), raw_text="DIV"
    )
    assert build_adjustments(BARS, [dividend]) == []
    (adj,) = build_adjustments(BARS, [dividend], include_dividends=True)
    assert adj.factor == Decimal("0.99")  # 1 - 26.796 / 2679.60


def test_revised_ex_date_is_applied_once_on_the_date_the_price_moved():
    wrong = CorporateActionRecord(
        "RELIANCE", D2, CorporateActionType.BONUS, Decimal(2), Decimal(1), raw_text="BONUS 1:1"
    )
    adjustments = build_adjustments(BARS, [wrong, BONUS])
    assert [a.ex_date for a in adjustments] == [D3]


def test_same_action_listed_twice_is_applied_once():
    twin = CorporateActionRecord(
        "RELIANCE", D3, CorporateActionType.BONUS, Decimal(2), Decimal(1), raw_text="BONUS 1:1 "
    )
    assert len(build_adjustments(BARS, [BONUS, twin])) == 1


def test_price_confirms():
    assert price_confirms(BARS, D3, Decimal("0.5")) is True
    assert price_confirms(BARS, D2, Decimal("0.5")) is False
    assert price_confirms(BARS, date(2024, 10, 26), Decimal("0.5")) is None
