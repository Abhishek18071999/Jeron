"""The real account's daily equity from the journal, and the same capital in the Nifty
500 beside it (pure).

Each session from the first buy: equity = capital + the gains of every sale up to that
day (lots first in, first out, after charges, as `realised_sales`) + the shares still
held marked at that day's close against their lots' cost (buy charges in the cost). A
stock without a close that day keeps its last one. The peak and the drawdown come from
this curve, so a peak reached only on paper and given back before selling counts.

Nifty 500 is the price index, without dividends, so it errs low by about 1% a year.
Capital is `JERON_CAPITAL` for the whole curve: deposits and withdrawals are not known.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.journal.calc import Fill
from app.portfolio.calc import realised_sales

ZERO = Decimal(0)


@dataclass(frozen=True)
class EquityPoint:
    day: date
    equity: Decimal
    drawdown_pct: Decimal  # below the curve's peak so far
    index: Decimal | None  # the capital put in the Nifty 500 on the first day


@dataclass(frozen=True)
class EquityCurve:
    points: list[EquityPoint]
    peak: Decimal | None
    max_drawdown_pct: Decimal
    return_pct: Decimal | None
    index_return_pct: Decimal | None


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _open_cost(fills: Sequence[Fill], day: date) -> tuple[int, Decimal]:
    """Shares held after `day`'s fills and their cost (first in, first out)."""
    lots: list[list[Decimal | int]] = []
    for f in sorted(fills, key=lambda f: (f.trade_date, f.side != "buy")):
        if f.trade_date > day or f.shares <= 0:
            continue
        if f.side == "buy":
            lots.append([f.shares, f.price + f.charges / f.shares])
            continue
        left = f.shares
        while left and lots:
            n = min(left, int(lots[0][0]))
            lots[0][0] = int(lots[0][0]) - n
            left -= n
            if not lots[0][0]:
                lots.pop(0)
    shares = sum(int(lot[0]) for lot in lots)
    cost = sum((int(lot[0]) * Decimal(lot[1]) for lot in lots), ZERO)
    return shares, cost


def equity_curve(
    capital: Decimal,
    positions: Sequence[tuple[str, Sequence[Fill]]],
    closes: Mapping[str, Mapping[date, Decimal]],
    days: Sequence[date],
    index: Mapping[date, Decimal] | None = None,
) -> EquityCurve:
    """The curve over `days` (sessions, oldest first) from the first buy on."""
    buys = [f.trade_date for _, fills in positions for f in fills if f.side == "buy"]
    if not buys:
        return EquityCurve([], None, ZERO, None, None)
    first = min(buys)
    sessions = [d for d in days if d >= first]
    sales = [s for ticker, fills in positions for s in realised_sales(ticker, fills)]
    index = index or {}
    base = next((index[d] for d in sessions if d in index), None)
    last_close: dict[str, Decimal] = {}
    points = []
    peak = capital
    worst = ZERO
    for day in sessions:
        realised = sum((s.gain for s in sales if s.sell_date <= day), ZERO)
        marks = ZERO
        for ticker, fills in positions:
            close = closes.get(ticker, {}).get(day)
            if close is not None:
                last_close[ticker] = close
            shares, cost = _open_cost(fills, day)
            if shares and ticker in last_close:
                marks += last_close[ticker] * shares - cost
        equity = capital + realised + marks
        peak = max(peak, equity)
        drawdown = (1 - equity / peak) * 100 if peak > 0 else ZERO
        worst = max(worst, drawdown)
        level = index.get(day)
        on_index = None if base is None or level is None else _q(capital * level / base)
        points.append(EquityPoint(day, _q(equity), _q(drawdown), on_index))
    end = points[-1]
    last_index = next((p.index for p in reversed(points) if p.index is not None), None)
    return EquityCurve(
        points=points,
        peak=_q(peak),
        max_drawdown_pct=_q(worst),
        return_pct=_q((end.equity / capital - 1) * 100) if capital > 0 else None,
        index_return_pct=(
            None if last_index is None or capital <= 0 else _q((last_index / capital - 1) * 100)
        ),
    )
