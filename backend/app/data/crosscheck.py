"""Compare two sources of raw daily prices, and two sources of corporate actions."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.data.adjust import SHARE_COUNT_ACTIONS, price_factor
from app.data.provider import Bar, CorporateActionRecord

CLOSE_TOLERANCE_PCT = Decimal("0.5")
ACTION_DATE_TOLERANCE_DAYS = 3
ACTION_FACTOR_TOLERANCE = Decimal("0.01")


@dataclass(frozen=True)
class CloseDiff:
    symbol: str
    trade_date: date
    primary: Decimal
    secondary: Decimal
    diff_pct: Decimal


@dataclass
class CloseComparison:
    checked: int = 0
    mismatches: list[CloseDiff] = field(default_factory=list)
    # Symbols the primary source has but the secondary doesn't, for that day.
    missing_in_secondary: list[str] = field(default_factory=list)


def compare_closes(
    primary: Iterable[Bar],
    secondary: Iterable[Bar],
    tolerance_pct: Decimal = CLOSE_TOLERANCE_PCT,
) -> CloseComparison:
    """Compare closes for the same (symbol, date). Only primary rows are checked."""
    other = {(b.symbol, b.trade_date): b.close for b in secondary}
    result = CloseComparison()
    for bar in primary:
        second = other.get((bar.symbol, bar.trade_date))
        if second is None:
            result.missing_in_secondary.append(bar.symbol)
            continue
        result.checked += 1
        diff_pct = (abs(second - bar.close) / bar.close * 100).quantize(Decimal("0.01"))
        if diff_pct > tolerance_pct:
            result.mismatches.append(
                CloseDiff(bar.symbol, bar.trade_date, bar.close, second, diff_pct)
            )
    return result


@dataclass(frozen=True)
class ActionDisagreement:
    symbol: str
    ex_date: date
    description: str


def compare_share_actions(
    nse: Iterable[CorporateActionRecord],
    other: Iterable[CorporateActionRecord],
    start: date,
    end: date,
) -> list[ActionDisagreement]:
    """Splits and bonuses that one source has and the other doesn't (or with a
    different ratio). Dates may differ by a few days between sources."""

    def share_actions(
        actions: Iterable[CorporateActionRecord],
    ) -> list[tuple[CorporateActionRecord, Decimal]]:
        found = []
        for a in actions:
            if a.action_type in SHARE_COUNT_ACTIONS and start <= a.ex_date <= end:
                factor = price_factor(a)
                if factor is not None:
                    found.append((a, factor))
        return found

    def matches(
        a: tuple[CorporateActionRecord, Decimal], b: tuple[CorporateActionRecord, Decimal]
    ) -> bool:
        return (
            a[0].symbol == b[0].symbol
            and abs((a[0].ex_date - b[0].ex_date).days) <= ACTION_DATE_TOLERANCE_DAYS
            and abs(a[1] - b[1]) <= ACTION_FACTOR_TOLERANCE * b[1]
        )

    # NSE sometimes lists a bonus and a split on one day; compare their product.
    def combined(
        items: list[tuple[CorporateActionRecord, Decimal]],
    ) -> list[tuple[CorporateActionRecord, Decimal]]:
        grouped: dict[tuple[str, date], tuple[CorporateActionRecord, Decimal]] = {}
        for action, factor in items:
            key = (action.symbol, action.ex_date)
            if key in grouped:
                grouped[key] = (grouped[key][0], grouped[key][1] * factor)
            else:
                grouped[key] = (action, factor)
        return list(grouped.values())

    left = combined(share_actions(nse))
    right = combined(share_actions(other))
    problems = []
    for item in left:
        if not any(matches(item, r) for r in right):
            problems.append(
                ActionDisagreement(
                    item[0].symbol,
                    item[0].ex_date,
                    f"NSE lists {item[0].raw_text!r} (price factor {item[1]:.4f}); "
                    "the second source has no matching split or bonus",
                )
            )
    for item in right:
        if not any(matches(item, left_item) for left_item in left):
            problems.append(
                ActionDisagreement(
                    item[0].symbol,
                    item[0].ex_date,
                    f"second source lists {item[0].raw_text!r} (price factor {item[1]:.4f}); "
                    "NSE has no matching split or bonus",
                )
            )
    return problems
