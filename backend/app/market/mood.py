"""The market mood: one line on how hard to push today, with the numbers behind it.

Inputs are the day's scan universe (adjusted prices, from the scan's stored indicators
plus each stock's 52-week range) and the index closes. Pure: `app.market.service`
loads the inputs from the database.

**Mode rule** (decision 0009). The regime filter is the engine's own (spec section 3,
`app.backtest.market.market_state`): Nifty 50 below its 200-day EMA, or India VIX in the
top decile of its last five years. Breadth is the share of the scan universe closing
above its own 200-day EMA.

- **defend**: the regime filter is on. The engine halves risk per trade (multiplier 0.5).
- **attack**: the regime filter is off AND breadth >= 60% AND new 52-week highs
  outnumber new 52-week lows. Risk per trade as set (multiplier 1.0).
- **normal**: anything else. Risk per trade as set (multiplier 1.0).

The mode never changes position sizes by itself: the multiplier is what the engine (and
so paper trading and the signals) already applies. Attack and normal differ only in what
the owner is told; the engine has no "attack" setting.

A new 52-week high: the day's high is above every high of the previous 251 sessions; a
new low likewise. Stocks with less than 252 sessions of history are not counted.

Sector strength: universe stocks grouped by NSE's industry (an instrument's sector, set
from the Nifty 500 list), with the median 6-month return, the share above their 200-day
EMA and the count, strongest first.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from statistics import median

import numpy as np

from app import indicators as ind
from app.backtest.market import (
    VIX_LOOKBACK_SESSIONS,
    VIX_MIN_SESSIONS,
    Regime,
    _index_series,
    market_state,
)

ATTACK_BREADTH_PCT = 60.0
DEFEND_RISK_MULTIPLIER = 0.5
HIGH_LOW_SESSIONS = 252
VIX_DECILE = 0.9


class Mode(StrEnum):
    ATTACK = "attack"
    NORMAL = "normal"
    DEFEND = "defend"


@dataclass(frozen=True)
class StockMood:
    """One universe stock on the day, on adjusted prices."""

    symbol: str
    sector: str | None
    in_nifty500: bool
    close: float
    ema200: float | None
    return_6m: float | None  # 0.12 = +12%
    high: float  # the day's high
    low: float
    prior_high: float | None  # the highest high of the previous 251 sessions
    prior_low: float | None
    sessions: int  # sessions of history in the 52-week window, the day included

    @property
    def new_high(self) -> bool:
        if self.sessions < HIGH_LOW_SESSIONS or self.prior_high is None:
            return False
        return self.high > self.prior_high

    @property
    def new_low(self) -> bool:
        if self.sessions < HIGH_LOW_SESSIONS or self.prior_low is None:
            return False
        return self.low < self.prior_low


@dataclass(frozen=True)
class RegimeDetail:
    """The engine's regime and regime filter on the day, with the values behind them."""

    day: date
    regime: Regime  # Nifty 500 trend (bull / bear / sideways)
    risk_off: bool  # the engine's regime filter: risk per trade halved
    nifty50: float | None
    nifty50_ema200: float | None
    nifty50_below: bool
    vix: float | None
    vix_top_decile: float | None  # the 90th percentile of the last five years
    vix_high: bool


@dataclass(frozen=True)
class Breadth:
    stocks: int
    above_ema200: int
    pct_above_ema200: float | None
    nifty500_stocks: int
    nifty500_above_ema200: int
    nifty500_pct_above_ema200: float | None
    new_highs: int
    new_lows: int


@dataclass(frozen=True)
class SectorStrength:
    sector: str
    stocks: int
    median_return_6m: float | None  # 0.12 = +12%
    pct_above_ema200: float | None


@dataclass(frozen=True)
class Mood:
    day: date
    mode: Mode
    reason: str
    risk_multiplier: float
    breadth: Breadth
    regime: RegimeDetail | None
    sectors: list[SectorStrength]


def _last_defined(values: Sequence[float | None]) -> float | None:
    return values[-1] if values else None


def regime_detail(
    days: Sequence[date],
    nifty500: Mapping[date, float],
    nifty50: Mapping[date, float],
    vix: Mapping[date, float],
) -> RegimeDetail | None:
    """The engine's regime on the last of `days` (oldest first), with the Nifty 50 and
    VIX numbers behind the regime filter. The verdict is `market_state`'s own."""
    state = market_state(days, nifty500, nifty50, vix)
    if state is None:
        return None
    n50 = _index_series(days, nifty50)
    n50_close = None if np.isnan(n50[-1]) else float(n50[-1])
    n50_ema = None
    defined = np.flatnonzero(~np.isnan(n50))
    if len(defined):
        n50_ema = _last_defined(ind.ema(list(n50[defined[0] :]), 200))
    v = _index_series(days, vix)
    vix_now = None if np.isnan(v[-1]) else float(v[-1])
    threshold = None
    if vix_now is not None:
        window = v[max(0, len(v) - 1 - VIX_LOOKBACK_SESSIONS) : len(v) - 1]
        window = window[~np.isnan(window)]
        if len(window) >= VIX_MIN_SESSIONS:
            threshold = float(np.quantile(window, VIX_DECILE))
    return RegimeDetail(
        day=state.day,
        regime=state.regime,
        risk_off=state.risk_off,
        nifty50=n50_close,
        nifty50_ema200=n50_ema,
        nifty50_below=bool(n50_close is not None and n50_ema is not None and n50_close < n50_ema),
        vix=vix_now,
        vix_top_decile=threshold,
        vix_high=bool(vix_now is not None and threshold is not None and vix_now >= threshold),
    )


def _pct(part: int, whole: int) -> float | None:
    return round(part / whole * 100, 1) if whole else None


def breadth(stocks: Sequence[StockMood]) -> Breadth:
    with_ema = [s for s in stocks if s.ema200 is not None]
    above = [s for s in with_ema if s.ema200 is not None and s.close > s.ema200]
    n500 = [s for s in with_ema if s.in_nifty500]
    n500_above = [s for s in n500 if s.ema200 is not None and s.close > s.ema200]
    return Breadth(
        stocks=len(with_ema),
        above_ema200=len(above),
        pct_above_ema200=_pct(len(above), len(with_ema)),
        nifty500_stocks=len(n500),
        nifty500_above_ema200=len(n500_above),
        nifty500_pct_above_ema200=_pct(len(n500_above), len(n500)),
        new_highs=sum(s.new_high for s in stocks),
        new_lows=sum(s.new_low for s in stocks),
    )


def sector_strength(stocks: Sequence[StockMood]) -> list[SectorStrength]:
    """Stocks with an industry, by industry, strongest median 6-month return first."""
    groups: dict[str, list[StockMood]] = {}
    for s in stocks:
        if s.sector:
            groups.setdefault(s.sector, []).append(s)
    out = []
    for sector, members in groups.items():
        returns = [s.return_6m for s in members if s.return_6m is not None]
        with_ema = [s for s in members if s.ema200 is not None]
        above = sum(1 for s in with_ema if s.ema200 is not None and s.close > s.ema200)
        out.append(
            SectorStrength(
                sector=sector,
                stocks=len(members),
                median_return_6m=round(median(returns), 4) if returns else None,
                pct_above_ema200=_pct(above, len(with_ema)),
            )
        )
    return sorted(
        out,
        key=lambda x: (
            x.median_return_6m is None,
            -(x.median_return_6m or 0.0),
            x.sector,
        ),
    )


def _regime_reason(r: RegimeDetail) -> str:
    parts = []
    if r.nifty50_below and r.nifty50 is not None and r.nifty50_ema200:
        gap = (r.nifty50 / r.nifty50_ema200 - 1) * 100
        parts.append(f"Nifty 50 is {abs(gap):.1f}% below its 200-day EMA")
    if r.vix_high and r.vix is not None and r.vix_top_decile is not None:
        parts.append(
            f"India VIX {r.vix:.1f} is in its top 10% of five years (from {r.vix_top_decile:.1f})"
        )
    return " and ".join(parts) if parts else "The regime filter is on"


def mode_for(regime: RegimeDetail | None, b: Breadth) -> tuple[Mode, str, float]:
    """(mode, one-line reason, risk multiplier) by the rule in the module docstring."""
    if regime is not None and regime.risk_off:
        return (
            Mode.DEFEND,
            f"{_regime_reason(regime)}: the engine halves risk per trade.",
            DEFEND_RISK_MULTIPLIER,
        )
    pct = b.pct_above_ema200
    if regime is None:
        return Mode.NORMAL, "Index closes are not loaded, so the regime is unknown.", 1.0
    if pct is None:
        return Mode.NORMAL, "No breadth: the scan universe is empty.", 1.0
    healthy = pct >= ATTACK_BREADTH_PCT
    leading = b.new_highs > b.new_lows
    if healthy and leading:
        return (
            Mode.ATTACK,
            f"Nifty 50 above its 200-day EMA, {pct:.0f}% of stocks above theirs and "
            f"{b.new_highs} new highs vs {b.new_lows} new lows: take every valid signal.",
            1.0,
        )
    why = []
    if not healthy:
        why.append(
            f"only {pct:.0f}% of stocks are above their 200-day EMA (attack needs "
            f"{ATTACK_BREADTH_PCT:.0f}%)"
        )
    if not leading:
        why.append(f"new lows ({b.new_lows}) are not fewer than new highs ({b.new_highs})")
    return (
        Mode.NORMAL,
        "Regime filter off, but " + " and ".join(why) + ": be selective.",
        1.0,
    )


def market_mood(day: date, stocks: Sequence[StockMood], regime: RegimeDetail | None) -> Mood:
    b = breadth(stocks)
    mode, reason, multiplier = mode_for(regime, b)
    return Mood(
        day=day,
        mode=mode,
        reason=reason,
        risk_multiplier=multiplier,
        breadth=b,
        regime=regime,
        sectors=sector_strength(stocks),
    )
