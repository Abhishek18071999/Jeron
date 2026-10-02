"""The technical brain: indicators for one stock and its 0-100 technical score.

Score version `tech-v1`. The points are starting values from the spec's list of
technical conditions, written down here so M3's backtester can test and recalibrate
them; a change of points is a new version. Every result keeps each component's
value and points, so a score can always be explained.

Relative strength is scored by percentile within the day's universe, so it is
computed for every stock first (`snapshot`) and scored afterwards (`score`).
"""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from app import indicators as ind

SCORE_VERSION = "tech-v1"
RS_SHORT_SESSIONS = 63  # about 3 months
RS_LONG_SESSIONS = 126  # about 6 months
HIGH_52W_SESSIONS = 252
PIVOT_STRENGTH = 5


@dataclass(frozen=True)
class PriceHistory:
    """One stock's adjusted daily bars, oldest first, ending on the scan date."""

    dates: Sequence[date]
    highs: Sequence[float]
    lows: Sequence[float]
    closes: Sequence[float]
    volumes: Sequence[float]


@dataclass(frozen=True)
class Snapshot:
    """Indicator values on the scan date."""

    sessions: int
    close: float
    prev_close: float | None
    ema20: float | None
    ema50: float | None
    ema200: float | None
    rsi14: float | None
    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    adx14: float | None
    plus_di: float | None
    minus_di: float | None
    atr14: float | None
    atr_pct: float | None
    volume: float
    avg_volume20: float | None
    volume_ratio: float | None
    high_52w: float
    below_52w_high_pct: float
    return_3m: float | None
    return_6m: float | None
    rs_3m: float | None  # stock return relative to Nifty 500 over the same dates
    rs_6m: float | None
    support: float | None
    resistance: float | None
    last_swing_high: float | None
    last_swing_low: float | None

    def to_dict(self) -> dict[str, Any]:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def _last(series: Sequence[float | None]) -> float | None:
    return series[-1] if series else None


def _relative_strength(
    history: PriceHistory, index_closes: Mapping[date, float], sessions: int
) -> tuple[float | None, float | None]:
    """(stock return, stock return relative to the index) over the last `sessions`
    of the stock's own bars, comparing the index on the same two dates."""
    if len(history.closes) <= sessions:
        return None, None
    start = len(history.closes) - 1 - sessions
    stock = history.closes[-1] / history.closes[start] - 1
    first, last = index_closes.get(history.dates[start]), index_closes.get(history.dates[-1])
    if not first or not last:
        return stock, None
    return stock, (1 + stock) / (last / first) - 1


def snapshot(history: PriceHistory, index_closes: Mapping[date, float]) -> Snapshot:
    h, lo, c, v = history.highs, history.lows, history.closes, history.volumes
    m = ind.macd(c)
    dmi = ind.adx(h, lo, c)
    atr14 = _last(ind.atr(h, lo, c))
    close = c[-1]
    high_52w = max(h[-HIGH_52W_SESSIONS:])
    avg20 = ind.sma(v[:-1], 20)
    ret3, rs3 = _relative_strength(history, index_closes, RS_SHORT_SESSIONS)
    ret6, rs6 = _relative_strength(history, index_closes, RS_LONG_SESSIONS)
    levels = ind.support_resistance(h, lo, close, PIVOT_STRENGTH, HIGH_52W_SESSIONS)
    return Snapshot(
        sessions=len(c),
        close=close,
        prev_close=c[-2] if len(c) > 1 else None,
        ema20=_last(ind.ema(c, 20)),
        ema50=_last(ind.ema(c, 50)),
        ema200=_last(ind.ema(c, 200)),
        rsi14=_last(ind.rsi(c)),
        macd=_last(m.macd),
        macd_signal=_last(m.signal),
        macd_hist=_last(m.histogram),
        adx14=_last(dmi.adx),
        plus_di=_last(dmi.plus_di),
        minus_di=_last(dmi.minus_di),
        atr14=atr14,
        atr_pct=atr14 / close * 100 if atr14 is not None else None,
        volume=v[-1],
        avg_volume20=_last(avg20),
        volume_ratio=_last(ind.volume_ratio(v)),
        high_52w=high_52w,
        below_52w_high_pct=(1 - close / high_52w) * 100,
        return_3m=ret3,
        return_6m=ret6,
        rs_3m=rs3,
        rs_6m=rs6,
        support=levels.support,
        resistance=levels.resistance,
        last_swing_high=levels.last_swing_high,
        last_swing_low=levels.last_swing_low,
    )


@dataclass(frozen=True)
class Component:
    key: str
    label: str
    value: float | None
    points: float
    max_points: float

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if isinstance(self.value, float):
            d["value"] = round(self.value, 4)
        return d


MAX_POINTS = {
    "trend_200": 15.0,
    "ema_stack": 10.0,
    "rsi": 10.0,
    "macd": 10.0,
    "adx": 10.0,
    "volume": 10.0,
    "near_high": 10.0,
    "atr": 5.0,
    "rs_3m": 7.5,
    "rs_6m": 7.5,
    "breakout": 5.0,
}
assert sum(MAX_POINTS.values()) == 100


def percentile_ranks(values: Mapping[str, float | None]) -> dict[str, float]:
    """Each defined value's percentile (0 = lowest, 1 = highest; ties share the
    average rank). A single value gets 0.5."""
    defined = sorted((v, k) for k, v in values.items() if v is not None)
    n = len(defined)
    if n == 0:
        return {}
    if n == 1:
        return {defined[0][1]: 0.5}
    out: dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and defined[j + 1][0] == defined[i][0]:
            j += 1
        rank = (i + j) / 2 / (n - 1)
        for k in range(i, j + 1):
            out[defined[k][1]] = rank
        i = j + 1
    return out


def _above(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and a > b


def score(s: Snapshot, rs_3m_pct: float | None, rs_6m_pct: float | None) -> list[Component]:
    """The tech-v1 components for one stock. `rs_*_pct` are its relative-strength
    percentiles within the day's universe (None if not computable)."""
    p = MAX_POINTS
    out = []

    def add(key: str, label: str, value: float | None, points: float) -> None:
        out.append(Component(key, label, value, points, p[key]))

    add(
        "trend_200", "Close above 200-day EMA", s.ema200, p["trend_200"] * _above(s.close, s.ema200)
    )
    add(
        "ema_stack",
        "20-day EMA above 50-day EMA",
        s.ema20,
        p["ema_stack"] * _above(s.ema20, s.ema50),
    )

    rsi_points = 0.0
    if s.rsi14 is not None:
        if 50 <= s.rsi14 <= 70:
            rsi_points = p["rsi"]
        elif 40 <= s.rsi14 < 50 or 70 < s.rsi14 <= 80:
            rsi_points = p["rsi"] / 2
    add("rsi", "RSI(14) between 50 and 70", s.rsi14, rsi_points)

    macd_points = p["macd"] / 2 * _above(s.macd, s.macd_signal) + p["macd"] / 2 * _above(
        s.macd, 0.0
    )
    add("macd", "MACD above its signal line and above zero", s.macd_hist, macd_points)

    trending = s.adx14 is not None and s.adx14 > 20 and _above(s.plus_di, s.minus_di)
    add("adx", "ADX(14) above 20 with +DI above -DI", s.adx14, p["adx"] * trending)

    volume_breakout = (
        s.volume_ratio is not None and s.volume_ratio >= 1.5 and _above(s.close, s.prev_close)
    )
    add(
        "volume",
        "Up day on volume at least 1.5x the 20-day average",
        s.volume_ratio,
        p["volume"] * volume_breakout,
    )

    near = s.below_52w_high_pct
    near_points = p["near_high"] if near <= 5 else p["near_high"] / 2 if near <= 15 else 0.0
    add("near_high", "Within 5% of the 52-week high (half within 15%)", near, near_points)

    atr_ok = s.atr_pct is not None and 1 <= s.atr_pct <= 6
    add("atr", "ATR(14) between 1% and 6% of price", s.atr_pct, p["atr"] * atr_ok)

    add(
        "rs_3m",
        "3-month strength vs Nifty 500 (percentile)",
        s.rs_3m,
        p["rs_3m"] * (rs_3m_pct or 0.0),
    )
    add(
        "rs_6m",
        "6-month strength vs Nifty 500 (percentile)",
        s.rs_6m,
        p["rs_6m"] * (rs_6m_pct or 0.0),
    )

    add(
        "breakout",
        "Close above the latest swing high",
        s.last_swing_high,
        p["breakout"] * _above(s.close, s.last_swing_high),
    )
    return out


def total(components: Sequence[Component]) -> float:
    return round(sum(c.points for c in components), 1)
