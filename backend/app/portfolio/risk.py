"""Stress and tail risk of my real open positions (pure).

The open-risk figure on Portfolio assumes every stop fills at its price. This module
asks what the history of the stocks I hold says about the days it doesn't:

- **Beta** to the Nifty 500 (last `BETA_SESSIONS` daily returns), and the book's beta,
  the value-weighted sum.
- **Market shocks**: the Nifty 500 falling 5%, 10% or 20% in a day, each stock moving
  by its beta, before any stop. A first-order estimate: in a crash correlations rise
  and betas with them.
- **Historical one-day VaR and expected shortfall**: today's positions run through each
  of the last `VAR_SESSIONS` sessions' actual returns, all stocks on the same day, so the
  way they move together is the market's, not a model's. "95% VaR ₹X": on 1 day in 20 of
  that history the book would have lost more than ₹X.
- **Gap through the stop**: each stock's worst opening gap down in `VAR_SESSIONS`
  sessions (open against the previous close). Applied to the last close, it says how far
  below the stop a sell would fill if that gap came tomorrow, and what that costs beyond
  the planned loss.
- **Correlation**: the average pairwise correlation of the stocks' daily returns over
  `CORR_SESSIONS` sessions and the pairs above `HIGH_CORR`: two stocks that move together
  are closer to one position than two.

Every input is a stored NSE price, split/bonus-adjusted so a split is no "return". None
of it is a forecast: history includes only the shocks that happened, and 500 sessions
may hold no crash at all. The report says how many sessions each figure stands on.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

BETA_SESSIONS = 250
BETA_MIN = 60
VAR_SESSIONS = 500
VAR_MIN = 100
CORR_SESSIONS = 120
CORR_MIN = 40
HIGH_CORR = 0.7
SHOCKS = (-5.0, -10.0, -20.0)


@dataclass(frozen=True)
class Series:
    """One stock's or the index's adjusted prices, oldest first. `opens` may be empty
    (the index has closes only)."""

    days: list[date]
    closes: list[float]
    opens: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class Position:
    ticker: str
    shares: int
    last_close: float
    stop: float | None


@dataclass(frozen=True)
class StockRisk:
    ticker: str
    value: float
    weight_pct: float  # of the book's value
    beta: float | None
    beta_sessions: int
    volatility_pct: float | None  # annualised, from the same sessions
    worst_gap_pct: float | None  # most negative open / previous close - 1, in %
    worst_gap_day: date | None
    planned_loss: float | None  # last close to the stop, x shares (None without a stop)
    gap_loss: float | None  # last close to the worst-gap open, x shares
    beyond_stop: float | None  # what the gap costs past the planned loss (0 if above it)


@dataclass(frozen=True)
class Shock:
    index_move_pct: float
    loss: float
    loss_pct: float  # of equity


@dataclass(frozen=True)
class Pair:
    a: str
    b: str
    correlation: float


@dataclass(frozen=True)
class RiskReport:
    as_of: date | None
    equity: float
    value: float
    stocks: list[StockRisk]
    book_beta: float | None
    shocks: list[Shock]
    var_sessions: int
    var95: float | None
    var99: float | None
    es97: float | None  # the average loss on the worst 2.5% of days
    worst_day: date | None
    worst_day_loss: float | None
    planned_loss: float  # every stop fills at its price
    gap_loss: float  # every stock opens at its worst gap at once
    avg_correlation: float | None
    corr_sessions: int
    high_pairs: list[Pair]
    notes: list[str]


def daily_returns(s: Series) -> dict[date, float]:
    """Close-to-close returns keyed by the later day."""
    return {
        s.days[i]: s.closes[i] / s.closes[i - 1] - 1
        for i in range(1, len(s.days))
        if s.closes[i - 1] > 0
    }


def _last(rets: Mapping[date, float], n: int) -> dict[date, float]:
    return {d: rets[d] for d in sorted(rets)[-n:]}


def correlation(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def beta(
    stock: Mapping[date, float], index: Mapping[date, float], sessions: int = BETA_SESSIONS
) -> tuple[float | None, int, float | None]:
    """(beta, sessions used, annualised volatility %) over the last `sessions` days both
    have. Beta is None under `BETA_MIN` common sessions."""
    common = sorted(set(stock) & set(index))[-sessions:]
    n = len(common)
    if n < BETA_MIN:
        return None, n, None
    xs = [index[d] for d in common]
    ys = [stock[d] for d in common]
    mx, my = sum(xs) / n, sum(ys) / n
    var_x = sum((x - mx) ** 2 for x in xs) / (n - 1)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / (n - 1)
    var_y = sum((y - my) ** 2 for y in ys) / (n - 1)
    vol = math.sqrt(var_y) * math.sqrt(252) * 100
    return (cov / var_x if var_x > 0 else None), n, vol


def worst_gap(s: Series, sessions: int = VAR_SESSIONS) -> tuple[float, date] | None:
    """The most negative open / previous close - 1 over the last `sessions` sessions."""
    if len(s.opens) != len(s.days) or len(s.days) < 2:
        return None
    start = max(1, len(s.days) - sessions)
    worst: tuple[float, date] | None = None
    for i in range(start, len(s.days)):
        if s.closes[i - 1] <= 0:
            continue
        gap = s.opens[i] / s.closes[i - 1] - 1
        if worst is None or gap < worst[0]:
            worst = (gap, s.days[i])
    return worst


def tail(losses: Sequence[float]) -> tuple[float, float, float]:
    """(95% VaR, 99% VaR, 97.5% expected shortfall) of daily losses (positive = a loss),
    by the historical method: the 95% VaR is the loss exceeded on 5% of the days."""
    desc = sorted(losses, reverse=True)
    n = len(desc)

    def var(level: float) -> float:
        return max(0.0, desc[min(n - 1, int(n * (1 - level)))])

    k = max(1, math.ceil(n * 0.025))
    return var(0.95), var(0.99), max(0.0, sum(desc[:k]) / k)


def risk_report(
    positions: Sequence[Position],
    series: Mapping[str, Series],
    index: Series | None,
    equity: float,
    as_of: date | None = None,
) -> RiskReport:
    notes: list[str] = []
    value = sum(p.shares * p.last_close for p in positions)
    index_rets = daily_returns(index) if index is not None else {}
    rets = {t: daily_returns(s) for t, s in series.items()}
    stocks = []
    for p in positions:
        v = p.shares * p.last_close
        b, n, vol = beta(rets.get(p.ticker, {}), index_rets)
        gap = worst_gap(series[p.ticker]) if p.ticker in series else None
        planned = None if p.stop is None else max(0.0, p.last_close - p.stop) * p.shares
        gap_loss = beyond = None
        if gap is not None:
            gap_open = p.last_close * (1 + min(gap[0], 0.0))
            gap_loss = (p.last_close - gap_open) * p.shares
            if p.stop is not None:
                beyond = max(0.0, p.stop - gap_open) * p.shares if gap_open < p.stop else 0.0
        stocks.append(
            StockRisk(
                p.ticker,
                v,
                v / value * 100 if value else 0.0,
                b,
                n,
                vol,
                None if gap is None else gap[0] * 100,
                None if gap is None else gap[1],
                planned,
                gap_loss,
                beyond,
            )
        )
    no_beta = [s.ticker for s in stocks if s.beta is None]
    if no_beta:
        notes.append(
            f"Beta taken as 1 for {', '.join(no_beta)}: fewer than {BETA_MIN} sessions of "
            "prices beside the Nifty 500."
        )
    beta_value = sum(s.value * (1.0 if s.beta is None else s.beta) for s in stocks)
    book_beta = beta_value / value if value and index_rets else None
    shocks = [
        Shock(move, -beta_value * move / 100, -beta_value * move / equity if equity else 0.0)
        for move in SHOCKS
    ]

    # Historical simulation over the sessions the index (or, without it, the stocks) has.
    calendar = sorted(index_rets) if index_rets else sorted({d for r in rets.values() for d in r})
    days = calendar[-VAR_SESSIONS:]
    var95 = var99 = es = worst_loss = None
    worst_day = None
    if len(days) >= VAR_MIN and stocks:
        losses = []
        for d in days:
            pnl = sum(s.value * rets.get(s.ticker, {}).get(d, 0.0) for s in stocks)
            losses.append(-pnl)
        var95, var99, es = tail(losses)
        i = max(range(len(losses)), key=lambda j: losses[j])
        worst_loss, worst_day = max(0.0, losses[i]), days[i]
        short = [t for t in series if len(set(rets.get(t, {})) & set(days)) < len(days) * 0.9]
        if short:
            notes.append(
                f"{', '.join(sorted(short))}: prices for under 90% of the {len(days)} "
                "sessions; missing days count as unchanged, which understates the risk."
            )
    elif stocks:
        notes.append(f"VaR needs {VAR_MIN} sessions of prices; {len(days)} are loaded.")

    corr_days = calendar[-CORR_SESSIONS:]
    pairs: list[Pair] = []
    values: list[float] = []
    tickers = sorted({s.ticker for s in stocks})
    for i, a in enumerate(tickers):
        for b_ in tickers[i + 1 :]:
            common = [d for d in corr_days if d in rets.get(a, {}) and d in rets.get(b_, {})]
            if len(common) < CORR_MIN:
                continue
            c = correlation([rets[a][d] for d in common], [rets[b_][d] for d in common])
            if c is None:
                continue
            values.append(c)
            if c >= HIGH_CORR:
                pairs.append(Pair(a, b_, c))
    pairs.sort(key=lambda p: -p.correlation)

    planned_total = sum(s.planned_loss or 0.0 for s in stocks)
    gap_total = sum(s.gap_loss or 0.0 for s in stocks)
    without_stop = [p.ticker for p in positions if p.stop is None]
    if without_stop:
        notes.append(
            f"No stop for {', '.join(without_stop)}: its planned loss is unknown and left out."
        )
    return RiskReport(
        as_of=as_of,
        equity=equity,
        value=value,
        stocks=stocks,
        book_beta=book_beta,
        shocks=shocks,
        var_sessions=len(days) if var95 is not None else 0,
        var95=var95,
        var99=var99,
        es97=es,
        worst_day=worst_day,
        worst_day_loss=worst_loss,
        planned_loss=planned_total,
        gap_loss=gap_total,
        avg_correlation=sum(values) / len(values) if values else None,
        corr_sessions=len(corr_days),
        high_pairs=pairs,
        notes=notes,
    )
