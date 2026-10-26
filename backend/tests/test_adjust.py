from datetime import date
from decimal import Decimal

from app.data.adjust import (
    adjust_bars,
    build_adjustments,
    price_confirms,
    price_factor,
    rights_issue_price,
)
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
    assert price_factor(rights) is None  # no price in the text, no previous close


def test_rights_issue_uses_the_theoretical_ex_rights_price():
    # 119 new for 758 held at a premium of ₹218, previous close 300. With a face value of
    # ₹1 the issue price is 219, factor 0.963379; with ₹10 it is 228, factor 0.967420;
    # 0.4% apart, so the midpoint, 0.965399.
    rights = CorporateActionRecord(
        "X",
        D3,
        CorporateActionType.RIGHTS,
        Decimal(119),
        Decimal(758),
        raw_text="RGHTS 119:758 PRM RS 218",
    )
    assert price_factor(rights, Decimal(300)) == Decimal("0.965399")
    premium = CorporateActionRecord(
        "X",
        D3,
        CorporateActionType.RIGHTS,
        Decimal(1),
        Decimal(6),
        raw_text="Rights 1:6 @ Premium Rs 1,201/-",
    )
    assert rights_issue_price(premium) == (Decimal(1202), Decimal(1211))
    assert price_factor(premium, Decimal(1500)) == Decimal("0.972048")
    assert rights_issue_price(
        CorporateActionRecord("X", D3, CorporateActionType.RIGHTS, raw_text="RIGHTS 1:5 @ RS 50")
    ) == (Decimal(50), Decimal(50))
    # A low-priced stock: the face value is most of the issue price (Vodafone Idea, 2019:
    # premium ₹2.50 on a ₹10 face value). ₹3.50 or ₹12.50 is too wide to guess.
    idea = CorporateActionRecord(
        "IDEA",
        D3,
        CorporateActionType.RIGHTS,
        Decimal(87),
        Decimal(38),
        raw_text="RIGHTS 87:38 @PRM RS 2.50",
    )
    assert price_factor(idea, Decimal(18)) is None
    # Priced at or above the market: nobody takes it up, nothing to adjust.
    assert price_factor(rights, Decimal(200)) is None
    # No ratio.
    loose = CorporateActionRecord("X", D3, CorporateActionType.RIGHTS, raw_text="RIGHTS PRM RS 5")
    assert price_factor(loose, Decimal(100)) is None


def test_demerger_uses_the_ex_date_open():
    demerger = CorporateActionRecord("X", D3, CorporateActionType.OTHER, raw_text="DEMERGER")
    assert price_factor(demerger, Decimal(1000), ex_open=Decimal(640)) == Decimal("0.64")
    assert price_factor(demerger, Decimal(1000)) is None  # no ex-date bar
    assert price_factor(demerger, Decimal(1000), ex_open=Decimal(990)) is None  # under 2%
    assert price_factor(demerger, Decimal(1000), ex_open=Decimal(1100)) is None  # a rise
    assert price_factor(demerger, Decimal(1000), ex_open=Decimal(50)) is None  # bad data
    scheme = CorporateActionRecord(
        "X", D3, CorporateActionType.OTHER, raw_text="SCHEME OF ARRANGEMENT"
    )
    assert price_factor(scheme, Decimal(1000), ex_open=Decimal(640)) is None


def test_demerger_adjusts_the_series_from_the_bars():
    bars = [
        bar("ITC", D1, 470, 475, 465, 472, 1000),
        bar("ITC", D2, 472, 474, 466, 470, 1000),
        bar("ITC", D3, 423, 430, 420, 428, 1000),  # hotels demerged: special pre-open 423
    ]
    demerger = CorporateActionRecord("ITC", D3, CorporateActionType.OTHER, raw_text="DEMERGER")
    (adj,) = build_adjustments(bars, [demerger])
    assert adj.factor == Decimal("0.9")  # 423 / 470
    adjusted = adjust_bars(bars, [adj])
    assert adjusted[1].close == Decimal("423.0000")  # no gap into the ex-date


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
