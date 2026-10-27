"""What a paper trade knew at its signal, and the entry filters proposed from it
(paper-review-v1, docs/plans/paper-review-v1.md). Pure: no database.

Every closed paper trade carries its signal-day context: the market regime, whether
the regime filter was on, the stock's sector and its tech-v1 score, ATR %, RSI and
volume ratio, the last four in fixed bands. The review groups trades by each of these.
A group that clearly loses becomes a proposal, "skip entries where <group>", which is
the same group as a mask on the market, so the backtester can test it on data the
evidence never saw.

The bands and the proposal rule are fixed here, before any result is seen; changing
them is a new `REVIEW_VERSION`.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import numpy as np

from app.backtest.features import Array
from app.backtest.market import Market, Regime
from app.journal.calc import mean_interval

REVIEW_VERSION = "paper-review-v1"
# A group needs this many closed trades, and so do the trades outside it.
MIN_GROUP_TRADES = 20
# The 10-session move after a signal that the missed-opportunity check measures.
FORWARD_SESSIONS = 10

# (upper edges, labels): a value goes in the first band whose edge is above it.
BANDS: dict[str, tuple[tuple[float, ...], tuple[str, ...]]] = {
    "score_band": (
        (70, 80, 90, 95, math.inf),
        ("below 70", "70-80", "80-90", "90-95", "95+"),
    ),
    "atr_band": (
        (2, 3, 4, 6, math.inf),
        ("ATR below 2%", "ATR 2-3%", "ATR 3-4%", "ATR 4-6%", "ATR 6%+"),
    ),
    "rsi_band": (
        (50, 60, 70, 80, math.inf),
        ("RSI below 50", "RSI 50-60", "RSI 60-70", "RSI 70-80", "RSI 80+"),
    ),
    "volume_band": (
        (1.5, 2, 3, math.inf),
        ("volume below 1.5x", "volume 1.5-2x", "volume 2-3x", "volume 3x+"),
    ),
}

DIMENSIONS: dict[str, str] = {
    "regime": "Market regime",
    "risk_off": "Regime filter",
    "sector": "Sector",
    "score_band": "tech-v1 score",
    "atr_band": "ATR(14) % of price",
    "rsi_band": "RSI(14)",
    "volume_band": "Volume vs 20-day average",
}
RISK_OFF_LABELS = {True: "regime filter on", False: "regime filter off"}
NO_SECTOR = "no sector"


def band(dimension: str, value: float | None) -> str | None:
    if value is None or not math.isfinite(value):
        return None
    edges, labels = BANDS[dimension]
    for edge, label in zip(edges, labels, strict=True):
        if value < edge:
            return label
    return labels[-1]


def _band_array(dimension: str, values: Array, label: str) -> Array:
    edges, labels = BANDS[dimension]
    i = labels.index(label)
    low = -math.inf if i == 0 else edges[i - 1]
    with np.errstate(invalid="ignore"):
        return np.asarray((values >= low) & (values < edges[i]), dtype=bool)


def _f(v: float) -> float | None:
    # Not rounded: the stored value must fall in the same band as the market's.
    v = float(v)
    return v if math.isfinite(v) else None


def signal_context(m: Market, s: int, t: int) -> dict[str, Any]:
    """What was known at stock s's close on day t (its signal day)."""
    close = float(m.close[s, t])
    atr = float(m.atr14[s, t])
    return {
        "score": _f(m.score[s, t]),
        "regime": m.regime[t].value,
        "risk_off": bool(m.risk_off[t]),
        "sector": m.sectors[s],
        "atr_pct": _f(atr / close * 100) if close > 0 else None,
        "rsi": _f(m.rsi14[s, t]),
        "volume_ratio": _f(m.volume_ratio[s, t]),
    }


_CONTEXT_VALUE = {
    "score_band": "score",
    "atr_band": "atr_pct",
    "rsi_band": "rsi",
    "volume_band": "volume_ratio",
}


def group_of(dimension: str, context: Mapping[str, Any]) -> str | None:
    """The trade's group in one dimension; None when unknown (older rows)."""
    if not context:
        return None
    if dimension == "regime":
        return context.get("regime")
    if dimension == "risk_off":
        flag = context.get("risk_off")
        return None if flag is None else RISK_OFF_LABELS[bool(flag)]
    if dimension == "sector":
        return context.get("sector") or NO_SECTOR
    return band(dimension, context.get(_CONTEXT_VALUE[dimension]))


def group_mask(m: Market, dimension: str, value: str) -> Array:
    """Bool (stocks, days): where a signal on that day falls in the group. The same
    rule as `group_of` on `signal_context`."""
    shape = m.close.shape
    if dimension == "regime":
        return np.broadcast_to(m.regime_is(Regime(value)), shape).copy()
    if dimension == "risk_off":
        on = value == RISK_OFF_LABELS[True]
        return np.broadcast_to((m.risk_off == on)[None, :], shape).copy()
    if dimension == "sector":
        rows = np.array([(sec or NO_SECTOR) == value for sec in m.sectors], dtype=bool)
        return np.broadcast_to(rows[:, None], shape).copy()
    if dimension == "score_band":
        return _band_array(dimension, m.score, value)
    if dimension == "atr_band":
        with np.errstate(invalid="ignore", divide="ignore"):
            return _band_array(dimension, m.atr14 / m.close * 100, value)
    if dimension == "rsi_band":
        return _band_array(dimension, m.rsi14, value)
    if dimension == "volume_band":
        return _band_array(dimension, m.volume_ratio, value)
    raise ValueError(f"unknown dimension {dimension}")


def skip_filter(
    condition: Callable[[Market, Any], Array], dimension: str, value: str
) -> Callable[[Market, Any], Array]:
    """A strategy condition that also skips entries in the group."""

    def filtered(m: Market, p: Any) -> Array:
        return np.asarray(condition(m, p) & ~group_mask(m, dimension, value), dtype=bool)

    return filtered


# --- Groups and the proposal rule ------------------------------------------------------


@dataclass(frozen=True)
class Group:
    dimension: str
    value: str
    trades: int
    wins: int
    avg_r: float
    interval: tuple[float, float] | None  # 95% range of the average R
    net_pnl: float
    loss_r: float  # the R lost by its losing trades (a positive number)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "label": DIMENSIONS[self.dimension],
            "value": self.value,
            "trades": self.trades,
            "win_rate": round(self.wins / self.trades, 4) if self.trades else 0.0,
            "avg_r": round(self.avg_r, 4),
            "interval": [round(x, 4) for x in self.interval] if self.interval else None,
            "net_pnl": round(self.net_pnl, 2),
            "loss_r": round(self.loss_r, 4),
        }


@dataclass(frozen=True)
class ClosedTrade:
    r: float
    net_pnl: float
    context: Mapping[str, Any]


def _group(dimension: str, value: str, trades: Sequence[ClosedTrade]) -> Group:
    rs = [t.r for t in trades]
    band_ = mean_interval([Decimal(str(round(r, 6))) for r in rs])
    return Group(
        dimension,
        value,
        len(rs),
        sum(r > 0 for r in rs),
        sum(rs) / len(rs) if rs else 0.0,
        (float(band_[0]), float(band_[1])) if band_ else None,
        sum(t.net_pnl for t in trades),
        -sum(r for r in rs if r < 0),
    )


def groups(trades: Sequence[ClosedTrade]) -> dict[str, list[Group]]:
    """Closed trades grouped in every dimension, worst average R first."""
    out: dict[str, list[Group]] = {}
    for dimension in DIMENSIONS:
        by: dict[str, list[ClosedTrade]] = {}
        for t in trades:
            g = group_of(dimension, t.context)
            if g is not None:
                by.setdefault(g, []).append(t)
        out[dimension] = sorted(
            (_group(dimension, v, ts) for v, ts in by.items()), key=lambda g: (g.avg_r, g.value)
        )
    return out


@dataclass(frozen=True)
class Candidate:
    group: Group
    rest: Group  # the trades outside the group

    @property
    def text(self) -> str:
        g = self.group
        return (
            f"Skip entries where {DIMENSIONS[g.dimension].lower()} is {g.value}: "
            f"{g.trades} paper trades there averaged {g.avg_r:+.2f}R "
            f"(95% range {g.interval[0]:+.2f}R to {g.interval[1]:+.2f}R), "  # type: ignore[index]
            f"against {self.rest.avg_r:+.2f}R for the other {self.rest.trades}."
        )

    def evidence(self) -> dict[str, Any]:
        return {
            "review_version": REVIEW_VERSION,
            "group": self.group.to_dict(),
            "rest": self.rest.to_dict(),
        }


def candidates(trades: Sequence[ClosedTrade]) -> list[Candidate]:
    """The proposal rule: a group of at least `MIN_GROUP_TRADES` closed trades whose
    average R's 95% range is entirely below zero, while the trades outside it (also at
    least `MIN_GROUP_TRADES`) averaged above zero. A strategy that loses everywhere gets
    no proposal: that is for the weekly revalidation."""
    out = []
    for dimension, gs in groups(trades).items():
        for g in gs:
            if g.trades < MIN_GROUP_TRADES or g.interval is None or g.interval[1] >= 0:
                continue
            rest = [t for t in trades if group_of(dimension, t.context) != g.value]
            if len(rest) < MIN_GROUP_TRADES:
                continue
            other = _group(dimension, "other", rest)
            if other.avg_r > 0:
                out.append(Candidate(g, other))
    return out


# --- Validation ------------------------------------------------------------------------

# The filtered version must keep enough out-of-sample trades (the spec's gate 1) and
# may not deepen the worst drawdown by more than this many points.
MIN_OOS_TRADES = 100
MAX_EXTRA_DRAWDOWN = 2.0


@dataclass(frozen=True)
class Result:
    """One walk-forward run's out-of-sample numbers, as the check compares them."""

    oos_trades: int
    oos_expectancy_r: float
    holdout_trades: int
    holdout_expectancy_r: float
    max_drawdown_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {k: round(v, 4) if isinstance(v, float) else v for k, v in self.__dict__.items()}


def judge(base: Result, filtered: Result) -> tuple[bool, list[str]]:
    """Does the filtered strategy beat the base on data the proposal never saw? Every
    condition must hold; the reasons say which failed."""
    fails = []
    if filtered.oos_trades < MIN_OOS_TRADES:
        fails.append(
            f"{filtered.oos_trades} out-of-sample trades with the filter (needs {MIN_OOS_TRADES})"
        )
    if filtered.oos_expectancy_r <= base.oos_expectancy_r:
        fails.append(
            f"out-of-sample expectancy {filtered.oos_expectancy_r:+.3f}R is not above the "
            f"strategy's {base.oos_expectancy_r:+.3f}R"
        )
    if filtered.holdout_expectancy_r <= 0:
        fails.append(f"holdout expectancy {filtered.holdout_expectancy_r:+.3f}R is not above 0")
    elif filtered.holdout_expectancy_r <= base.holdout_expectancy_r:
        fails.append(
            f"holdout expectancy {filtered.holdout_expectancy_r:+.3f}R is not above the "
            f"strategy's {base.holdout_expectancy_r:+.3f}R"
        )
    if filtered.max_drawdown_pct > base.max_drawdown_pct + MAX_EXTRA_DRAWDOWN:
        fails.append(
            f"max drawdown {filtered.max_drawdown_pct:.1f}% is more than "
            f"{MAX_EXTRA_DRAWDOWN:g} points worse than {base.max_drawdown_pct:.1f}%"
        )
    return not fails, fails


def forward_split(trades: Sequence[ClosedTrade], dimension: str, value: str) -> dict[str, Any]:
    """The trades since a proposal, split into those its filter would have skipped and
    those it would have kept (reporting only)."""
    inside = [t for t in trades if group_of(dimension, t.context) == value]
    kept = [t for t in trades if group_of(dimension, t.context) != value]

    def line(ts: Sequence[ClosedTrade]) -> dict[str, Any]:
        rs = [t.r for t in ts]
        return {
            "trades": len(rs),
            "avg_r": round(sum(rs) / len(rs), 4) if rs else None,
            "net_pnl": round(sum(t.net_pnl for t in ts), 2),
        }

    return {"trades": len(trades), "skipped": line(inside), "kept": line(kept)}
