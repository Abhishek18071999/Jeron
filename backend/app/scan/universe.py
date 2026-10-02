"""Universe rules (spec section 2), as pure functions.

A stock is in the day's universe when it:
- traded that day (suspended stocks have no bar),
- traded in the EQ series (BE and BZ are trade-for-trade; SME series are never stored),
- closed at or above ₹20,
- had a 20-session median turnover of at least ₹5 crore,
- is not on GSM (NSE's security list) or ASM (imported list),
- has at least 200 sessions of history, enough for the 200-day EMA.

Only data up to the scan date is used, so the same rules give a point-in-time
universe for backtests, with no survivorship bias.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Exclusion(StrEnum):
    NOT_TRADED = "not_traded"
    NOT_EQ_SERIES = "not_eq_series"
    LOW_PRICE = "low_price"
    LOW_TURNOVER = "low_turnover"
    GSM = "gsm"
    ASM = "asm"
    SHORT_HISTORY = "short_history"


EXCLUSION_LABELS = {
    Exclusion.NOT_TRADED: "Did not trade on the day (suspended or no trades)",
    Exclusion.NOT_EQ_SERIES: "Trade-for-trade series (BE/BZ)",
    Exclusion.LOW_PRICE: "Close below ₹20",
    Exclusion.LOW_TURNOVER: "20-day median turnover below ₹5 crore",
    Exclusion.GSM: "On NSE's Graded Surveillance Measure list",
    Exclusion.ASM: "On NSE's Additional Surveillance Measure list",
    Exclusion.SHORT_HISTORY: "Fewer than 200 sessions of history",
}


@dataclass(frozen=True)
class UniverseRules:
    min_price: Decimal = Decimal("20")
    min_median_turnover: Decimal = Decimal("50000000")  # ₹5 crore
    turnover_sessions: int = 20
    min_history: int = 200


@dataclass(frozen=True)
class Candidate:
    symbol: str
    traded: bool
    series: str | None
    close: Decimal | None
    median_turnover: Decimal | None


def exclusion(
    candidate: Candidate,
    rules: UniverseRules,
    gsm: set[str],
    asm: set[str],
) -> Exclusion | None:
    """The first rule the stock fails (history is checked later, once bars are
    loaded), or None if it passes."""
    if not candidate.traded or candidate.close is None:
        return Exclusion.NOT_TRADED
    if candidate.series != "EQ":
        return Exclusion.NOT_EQ_SERIES
    if candidate.close < rules.min_price:
        return Exclusion.LOW_PRICE
    if candidate.median_turnover is None or candidate.median_turnover < rules.min_median_turnover:
        return Exclusion.LOW_TURNOVER
    if candidate.symbol in gsm:
        return Exclusion.GSM
    if candidate.symbol in asm:
        return Exclusion.ASM
    return None
