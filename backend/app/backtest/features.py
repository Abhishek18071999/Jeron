"""Indicator and score series for the backtester.

The daily scan computes indicators for one day (`app.scan.score.snapshot`). A
backtest needs them for every day, so this module computes the same quantities as
whole series in one pass, using the same indicator functions. On any day, the values
here equal what `snapshot` and `score` give for a history ending that day (checked
in `tests/test_backtest_features.py`).

Everything uses only bars up to the day in question: rolling windows look back, and
a swing pivot counts only once the `PIVOT_STRENGTH` bars after it exist.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from app import indicators as ind
from app.scan.score import (
    HIGH_52W_SESSIONS,
    MAX_POINTS,
    PIVOT_STRENGTH,
    RS_LONG_SESSIONS,
    RS_SHORT_SESSIONS,
)

Array = np.ndarray
Floats = Sequence[float] | Array
NAN = float("nan")


def _arr(series: Sequence[float | None]) -> Array:
    return np.array([NAN if v is None else v for v in series], dtype=float)


@dataclass
class StockFeatures:
    """One stock's indicator series on its own sessions (oldest first)."""

    ema20: Array
    ema50: Array
    ema200: Array
    rsi14: Array
    macd: Array
    macd_signal: Array
    adx14: Array
    plus_di: Array
    minus_di: Array
    atr14: Array
    volume_ratio: Array
    avg_volume20: Array  # average of the 20 sessions before each day
    high_52w: Array  # highest high of the last 252 sessions, today included
    prior_high_52w: Array  # the same, today excluded
    rs_3m: Array
    rs_6m: Array
    last_swing_high: Array
    last_swing_low: Array
    base_points: Array  # tech-v1 points from every component except relative strength


def _relative_strength(
    dates: Sequence[date], closes: Array, index_closes: Mapping[date, float], sessions: int
) -> Array:
    out = np.full(len(closes), NAN)
    for t in range(sessions, len(closes)):
        first = index_closes.get(dates[t - sessions])
        last = index_closes.get(dates[t])
        if first and last:
            stock = closes[t] / closes[t - sessions] - 1
            out[t] = (1 + stock) / (last / first) - 1
    return out


def _last_pivot(pivots: list[ind.Pivot], n: int) -> Array:
    """For each day t, the price of the latest pivot that `support_resistance` with a
    252-session lookback would report as of t: index in [start + strength, t - strength]
    where start = max(0, t + 1 - 252)."""
    out = np.full(n, NAN)
    j = -1  # index into pivots of the latest pivot with index <= t - strength
    for t in range(n):
        while j + 1 < len(pivots) and pivots[j + 1].index <= t - PIVOT_STRENGTH:
            j += 1
        if j >= 0:
            start = max(0, t + 1 - HIGH_52W_SESSIONS)
            if pivots[j].index >= start + PIVOT_STRENGTH:
                out[t] = pivots[j].price
    return out


def stock_features(
    dates: Sequence[date],
    highs: Floats,
    lows: Floats,
    closes: Floats,
    volumes: Floats,
    index_closes: Mapping[date, float],
) -> StockFeatures:
    """Adjusted bars (oldest first) -> indicator series, one value per bar."""
    h = list(highs)
    lo = list(lows)
    c = list(closes)
    v = list(volumes)
    n = len(c)
    close = np.array(c, dtype=float)
    m = ind.macd(c)
    dmi = ind.adx(h, lo, c)
    ema20, ema50, ema200 = _arr(ind.ema(c, 20)), _arr(ind.ema(c, 50)), _arr(ind.ema(c, 200))
    rsi14 = _arr(ind.rsi(c))
    macd_line, macd_signal = _arr(m.macd), _arr(m.signal)
    adx14, plus_di, minus_di = _arr(dmi.adx), _arr(dmi.plus_di), _arr(dmi.minus_di)
    atr14 = _arr(ind.atr(h, lo, c))
    vol_ratio = _arr(ind.volume_ratio(v))
    sma20 = _arr(ind.sma(v, 20))
    avg_volume20 = np.concatenate([[NAN], sma20[:-1]]) if n else sma20
    high_52w = _arr(ind.rolling_max(h, HIGH_52W_SESSIONS))
    prior = np.full(n, NAN)
    if n > 1:
        prior[1:] = _arr(ind.rolling_max(h[:-1], HIGH_52W_SESSIONS))
    rs3 = _relative_strength(dates, close, index_closes, RS_SHORT_SESSIONS)
    rs6 = _relative_strength(dates, close, index_closes, RS_LONG_SESSIONS)
    pivots = ind.swing_pivots(h, lo, PIVOT_STRENGTH)
    last_high = _last_pivot(pivots.highs, n)
    last_low = _last_pivot(pivots.lows, n)

    prev_close = np.concatenate([[NAN], close[:-1]]) if n else close
    p = MAX_POINTS
    with np.errstate(invalid="ignore"):
        points = p["trend_200"] * (close > ema200)
        points = points + p["ema_stack"] * (ema20 > ema50)
        rsi_full = (rsi14 >= 50) & (rsi14 <= 70)
        rsi_half = ((rsi14 >= 40) & (rsi14 < 50)) | ((rsi14 > 70) & (rsi14 <= 80))
        points = points + p["rsi"] * rsi_full + p["rsi"] / 2 * rsi_half
        points = (
            points + p["macd"] / 2 * (macd_line > macd_signal) + p["macd"] / 2 * (macd_line > 0)
        )
        points = points + p["adx"] * ((adx14 > 20) & (plus_di > minus_di))
        points = points + p["volume"] * ((vol_ratio >= 1.5) & (close > prev_close))
        below = (1 - close / high_52w) * 100
        points = points + np.where(
            below <= 5, p["near_high"], np.where(below <= 15, p["near_high"] / 2, 0.0)
        )
        atr_pct = atr14 / close * 100
        points = points + p["atr"] * ((atr_pct >= 1) & (atr_pct <= 6))
        points = points + p["breakout"] * (close > last_high)
    return StockFeatures(
        ema20=ema20,
        ema50=ema50,
        ema200=ema200,
        rsi14=rsi14,
        macd=macd_line,
        macd_signal=macd_signal,
        adx14=adx14,
        plus_di=plus_di,
        minus_di=minus_di,
        atr14=atr14,
        volume_ratio=vol_ratio,
        avg_volume20=avg_volume20,
        high_52w=high_52w,
        prior_high_52w=prior,
        rs_3m=rs3,
        rs_6m=rs6,
        last_swing_high=last_high,
        last_swing_low=last_low,
        base_points=points.astype(float),
    )


def percentile_ranks(values: Array) -> Array:
    """Vector version of `app.scan.score.percentile_ranks`: each defined value's
    percentile among the defined values (0 lowest, 1 highest, ties share the
    average rank, a single value gets 0.5). NaN stays NaN."""
    out = np.full(len(values), NAN)
    defined = np.flatnonzero(~np.isnan(values))
    n = len(defined)
    if n == 0:
        return out
    if n == 1:
        out[defined[0]] = 0.5
        return out
    vals = values[defined]
    order = np.argsort(vals, kind="mergesort")
    sorted_vals = vals[order]
    # Average position of each run of equal values.
    _, first, counts = np.unique(sorted_vals, return_index=True, return_counts=True)
    avg_pos = first + (counts - 1) / 2
    run = np.repeat(np.arange(len(first)), counts)
    ranks = np.empty(n)
    ranks[order] = avg_pos[run] / (n - 1)
    out[defined] = ranks
    return out
