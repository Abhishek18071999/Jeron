"""How a stock's price has done, for Compare (docs/plans/compare-v2.md): returns over set
periods, the year's volatility and worst fall from a high, and the closes rebased to 100
so several stocks and Nifty 500 share one chart. Pure; prices are split/bonus-adjusted
closes, oldest first. Past returns, not a forecast."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

# Sessions in each period (about 21 a month).
PERIODS: tuple[tuple[str, int], ...] = (("1M", 21), ("3M", 63), ("6M", 126), ("1Y", 252))
YEAR = 252

Closes = Sequence[tuple[date, float]]


@dataclass(frozen=True)
class Performance:
    returns: dict[str, float | None]  # % over each period; None without enough history
    volatility: float | None  # % a year, from the last year's daily returns
    max_drawdown: float | None  # % worst fall from a high within the last year
    series: list[tuple[date, float]]  # rebased to 100 at `start`


def returns(closes: Closes) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for name, n in PERIODS:
        if len(closes) > n and closes[-1 - n][1] > 0:
            out[name] = round((closes[-1][1] / closes[-1 - n][1] - 1) * 100, 2)
        else:
            out[name] = None
    return out


def volatility(closes: Closes) -> float | None:
    year = [c for _, c in closes[-(YEAR + 1) :]]
    daily = [b / a - 1 for a, b in zip(year, year[1:], strict=False) if a > 0]
    if len(daily) < 20:
        return None
    mean = sum(daily) / len(daily)
    var = sum((d - mean) ** 2 for d in daily) / (len(daily) - 1)
    return round(math.sqrt(var) * math.sqrt(YEAR) * 100, 2)


def max_drawdown(closes: Closes) -> float | None:
    year = [c for _, c in closes[-(YEAR + 1) :]]
    if len(year) < 2:
        return None
    peak, worst = year[0], 0.0
    for c in year:
        peak = max(peak, c)
        if peak > 0:
            worst = min(worst, c / peak - 1)
    return round(worst * 100, 2)


def window_start(all_closes: Sequence[Closes], sessions: int = YEAR) -> date | None:
    """The first day every series has, within the last `sessions` of each: the chart
    starts there so all lines begin at 100 on the same day."""
    starts = [c[-(sessions + 1) :][0][0] for c in all_closes if c]
    return max(starts) if starts else None


def rebase(closes: Closes, start: date) -> list[tuple[date, float]]:
    shown = [(d, c) for d, c in closes if d >= start]
    if not shown or shown[0][1] <= 0:
        return []
    base = shown[0][1]
    return [(d, round(c / base * 100, 2)) for d, c in shown]


def performance(closes: Closes, start: date | None) -> Performance:
    return Performance(
        returns=returns(closes),
        volatility=volatility(closes),
        max_drawdown=max_drawdown(closes),
        series=[] if start is None else rebase(closes, start),
    )
