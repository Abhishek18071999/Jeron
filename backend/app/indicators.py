"""Technical indicators, as plain functions over price lists (oldest first).

The conventions follow common broker charts and TA-Lib, so values can be compared:
EMA is seeded with the simple average of its first `period` values; RSI, ATR and ADX
use Wilder's smoothing. Each function returns one value per input bar, None until
enough history exists. `tests/test_indicators_reference.py` checks every indicator
TA-Lib also has against TA-Lib.

These are computed on adjusted prices (splits and bonuses), never raw ones, so a
split doesn't look like a crash.
"""

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass

Series = list[float | None]


def sma(values: Sequence[float], period: int) -> Series:
    out: Series = []
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= period:
            total -= values[i - period]
        out.append(total / period if i >= period - 1 else None)
    return out


def _ema_from(values: Sequence[float | None], period: int) -> Series:
    """EMA of a series whose leading values may be None; seeded with the simple
    average of the first `period` defined values."""
    out: Series = [None] * len(values)
    start = next((i for i, v in enumerate(values) if v is not None), len(values))
    if len(values) - start < period:
        return out
    k = 2 / (period + 1)
    seed = values[start : start + period]
    prev = sum(v for v in seed if v is not None) / period
    out[start + period - 1] = prev
    for i in range(start + period, len(values)):
        v = values[i]
        if v is None:
            raise ValueError("EMA input has a gap")
        prev = v * k + prev * (1 - k)
        out[i] = prev
    return out


def ema(values: Sequence[float], period: int) -> Series:
    return _ema_from(values, period)


def _wilder(values: Sequence[float], period: int, start: int) -> Series:
    """Wilder smoothing of `values`, first defined at index start + period - 1."""
    out: Series = [None] * len(values)
    if len(values) < start + period:
        return out
    prev = sum(values[start : start + period]) / period
    out[start + period - 1] = prev
    for i in range(start + period, len(values)):
        prev = (prev * (period - 1) + values[i]) / period
        out[i] = prev
    return out


def rsi(closes: Sequence[float], period: int = 14) -> Series:
    gains = [0.0] + [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [0.0] + [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    avg_gain = _wilder(gains, period, 1)
    avg_loss = _wilder(losses, period, 1)
    out: Series = []
    for g, lo in zip(avg_gain, avg_loss, strict=True):
        if g is None or lo is None:
            out.append(None)
        elif lo == 0:
            out.append(100.0)
        else:
            out.append(100 - 100 / (1 + g / lo))
    return out


def true_range(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]
) -> list[float]:
    if not closes:
        return []
    return [highs[0] - lows[0]] + [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        for i in range(1, len(closes))
    ]


def atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> Series:
    return _wilder(true_range(highs, lows, closes), period, 1)


@dataclass(frozen=True)
class Macd:
    macd: Series
    signal: Series
    histogram: Series


def macd(closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Macd:
    fast_ema, slow_ema = ema(closes, fast), ema(closes, slow)
    line: Series = [
        None if f is None or s is None else f - s for f, s in zip(fast_ema, slow_ema, strict=True)
    ]
    sig = _ema_from(line, signal)
    hist: Series = [
        None if m is None or s is None else m - s for m, s in zip(line, sig, strict=True)
    ]
    return Macd(line, sig, hist)


@dataclass(frozen=True)
class Adx:
    adx: Series
    plus_di: Series
    minus_di: Series


def adx(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> Adx:
    """Wilder's Average Directional Index with the two directional indicators.

    +DI/-DI are first defined at index `period`, ADX at `2 * period - 1`.
    """
    n = len(closes)
    plus_dm, minus_dm = [0.0] * n, [0.0] * n
    for i in range(1, n):
        up, down = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
        if up > down and up > 0:
            plus_dm[i] = up
        elif down > up and down > 0:
            minus_dm[i] = down
    tr = _wilder(true_range(highs, lows, closes), period, 1)
    pdm, mdm = _wilder(plus_dm, period, 1), _wilder(minus_dm, period, 1)
    plus_di: Series = [None] * n
    minus_di: Series = [None] * n
    dx: list[float] = []
    dx_start = None
    for i in range(n):
        t, p, m = tr[i], pdm[i], mdm[i]
        if t is None or p is None or m is None:
            continue
        plus_di[i] = 100 * p / t if t else 0.0
        minus_di[i] = 100 * m / t if t else 0.0
        total = (plus_di[i] or 0.0) + (minus_di[i] or 0.0)
        dx.append(100 * abs((plus_di[i] or 0.0) - (minus_di[i] or 0.0)) / total if total else 0.0)
        if dx_start is None:
            dx_start = i
    adx_out: Series = [None] * n
    if dx_start is not None:
        for j, v in enumerate(_wilder(dx, period, 0)):
            adx_out[dx_start + j] = v
    return Adx(adx_out, plus_di, minus_di)


def rolling_max(values: Sequence[float], period: int) -> Series:
    """Highest value of the last `period` values (fewer at the start, never None)."""
    out: Series = []
    window: deque[int] = deque()
    for i, v in enumerate(values):
        while window and values[window[-1]] <= v:
            window.pop()
        window.append(i)
        if window[0] <= i - period:
            window.popleft()
        out.append(values[window[0]])
    return out


def volume_ratio(volumes: Sequence[float], period: int = 20) -> Series:
    """Each day's volume divided by the average of the `period` days before it."""
    avg = sma(volumes, period)
    return [
        None if i == 0 or avg[i - 1] in (None, 0) else volumes[i] / avg[i - 1]  # type: ignore[operator]
        for i in range(len(volumes))
    ]


def pct_change(values: Sequence[float], periods: int) -> Series:
    return [
        values[i] / values[i - periods] - 1 if i >= periods and values[i - periods] else None
        for i in range(len(values))
    ]


@dataclass(frozen=True)
class Pivot:
    index: int
    price: float


@dataclass(frozen=True)
class Pivots:
    highs: list[Pivot]
    lows: list[Pivot]


def swing_pivots(highs: Sequence[float], lows: Sequence[float], strength: int = 5) -> Pivots:
    """Swing highs and lows: a bar whose high is above the `strength` bars before it and
    not below the `strength` bars after it (lows mirrored). A pivot is only known
    `strength` bars later, so the last `strength` bars never contain one: this keeps
    the result free of look-ahead when the series ends on the scan date."""
    n = len(highs)
    ph, pl = [], []
    for i in range(strength, n - strength):
        before_h, after_h = highs[i - strength : i], highs[i + 1 : i + strength + 1]
        if highs[i] > max(before_h) and highs[i] >= max(after_h):
            ph.append(Pivot(i, highs[i]))
        before_l, after_l = lows[i - strength : i], lows[i + 1 : i + strength + 1]
        if lows[i] < min(before_l) and lows[i] <= min(after_l):
            pl.append(Pivot(i, lows[i]))
    return Pivots(ph, pl)


@dataclass(frozen=True)
class Levels:
    support: float | None  # highest swing low below the close
    resistance: float | None  # lowest swing high above the close
    last_swing_high: float | None  # most recent confirmed swing high
    last_swing_low: float | None


def support_resistance(
    highs: Sequence[float],
    lows: Sequence[float],
    close: float,
    strength: int = 5,
    lookback: int = 250,
) -> Levels:
    """Support and resistance from swing pivots over the last `lookback` bars."""
    start = max(0, len(highs) - lookback)
    pivots = swing_pivots(highs[start:], lows[start:], strength)
    below = [p.price for p in pivots.lows if p.price < close]
    above = [p.price for p in pivots.highs if p.price > close]
    return Levels(
        support=max(below) if below else None,
        resistance=min(above) if above else None,
        last_swing_high=pivots.highs[-1].price if pivots.highs else None,
        last_swing_low=pivots.lows[-1].price if pivots.lows else None,
    )
