"""A few standard indicators for the spot-check page.

M2 adds the full indicator set, checked against a reference library. These follow
the common charting conventions so values can be compared with a broker's chart:
EMA seeded with the simple average of its first `period` values, and RSI and ATR
with Wilder's smoothing. Values before enough history exists are None.
"""

from collections.abc import Sequence


def sma(values: Sequence[float], period: int) -> list[float | None]:
    out: list[float | None] = []
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= period:
            total -= values[i - period]
        out.append(total / period if i >= period - 1 else None)
    return out


def ema(values: Sequence[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def _wilder(values: Sequence[float], period: int, start: int) -> list[float | None]:
    """Wilder smoothing of `values`, first defined at index start + period - 1."""
    out: list[float | None] = [None] * len(values)
    if len(values) < start + period:
        return out
    prev = sum(values[start : start + period]) / period
    out[start + period - 1] = prev
    for i in range(start + period, len(values)):
        prev = (prev * (period - 1) + values[i]) / period
        out[i] = prev
    return out


def rsi(closes: Sequence[float], period: int = 14) -> list[float | None]:
    gains = [0.0] + [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [0.0] + [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    avg_gain = _wilder(gains, period, 1)
    avg_loss = _wilder(losses, period, 1)
    out: list[float | None] = []
    for g, lo in zip(avg_gain, avg_loss, strict=True):
        if g is None or lo is None:
            out.append(None)
        elif lo == 0:
            out.append(100.0)
        else:
            out.append(100 - 100 / (1 + g / lo))
    return out


def atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> list[float | None]:
    true_ranges = [highs[0] - lows[0]] + [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        for i in range(1, len(closes))
    ]
    return _wilder(true_ranges, period, 1)
