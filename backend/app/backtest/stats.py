"""Backtest statistics, the section 6 gates, and the deflated Sharpe ratio."""

import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from statistics import NormalDist
from typing import Any

import numpy as np

from app.backtest.engine import Trade
from app.backtest.features import Array

SESSIONS_PER_YEAR = 252
EULER_GAMMA = 0.5772156649


@dataclass(frozen=True)
class TradeStats:
    trades: int
    wins: int
    win_rate: float
    avg_r: float
    expectancy_r: float
    profit_factor: float
    net_pnl: float
    avg_win_r: float
    avg_loss_r: float
    avg_sessions: float

    def to_dict(self) -> dict[str, Any]:
        return {k: _clean(v) for k, v in asdict(self).items()}


def _clean(v: Any) -> Any:
    if isinstance(v, np.bool_ | bool):
        return bool(v)
    if isinstance(v, float):
        v = float(v)
        if math.isinf(v):
            return "inf" if v > 0 else "-inf"
        if math.isnan(v):
            return None
        return round(v, 4)
    return v


def trade_stats(trades: Sequence[Trade]) -> TradeStats:
    n = len(trades)
    if n == 0:
        return TradeStats(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    rs = [t.r_multiple for t in trades]
    pnl = [t.net_pnl for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gains = sum(p for p in pnl if p > 0)
    lost = -sum(p for p in pnl if p < 0)
    pf = gains / lost if lost > 0 else (math.inf if gains > 0 else 0.0)
    return TradeStats(
        trades=n,
        wins=len(wins),
        win_rate=len(wins) / n,
        avg_r=sum(rs) / n,
        expectancy_r=sum(rs) / n,
        profit_factor=pf,
        net_pnl=sum(pnl),
        avg_win_r=sum(wins) / len(wins) if wins else 0.0,
        avg_loss_r=sum(losses) / len(losses) if losses else 0.0,
        avg_sessions=sum(max(t.exit_day - t.entry_day, 0) for t in trades) / n,
    )


@dataclass(frozen=True)
class CurveStats:
    start_value: float
    end_value: float
    total_return: float
    cagr: float
    max_drawdown_pct: float
    sharpe: float  # annualised, daily returns, no risk-free rate
    volatility: float  # annualised
    sessions: int

    def to_dict(self) -> dict[str, Any]:
        return {k: _clean(v) for k, v in asdict(self).items()}


def daily_returns(curve: Array) -> Array:
    curve = np.asarray(curve, dtype=float)
    if len(curve) < 2:
        return np.zeros(0)
    return np.asarray(curve[1:] / curve[:-1] - 1)


def drawdown_series(curve: Array) -> Array:
    curve = np.asarray(curve, dtype=float)
    peaks = np.maximum.accumulate(curve)
    return np.asarray((1 - curve / peaks) * 100)


def curve_stats(curve: Array) -> CurveStats:
    curve = np.asarray(curve, dtype=float)
    n = len(curve)
    if n == 0 or curve[0] <= 0:
        return CurveStats(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, n)
    rets = daily_returns(curve)
    sd = float(np.std(rets, ddof=1)) if len(rets) > 1 else 0.0
    mean = float(np.mean(rets)) if len(rets) else 0.0
    years = (n - 1) / SESSIONS_PER_YEAR
    total = curve[-1] / curve[0] - 1
    cagr = (curve[-1] / curve[0]) ** (1 / years) - 1 if years > 0 and curve[-1] > 0 else 0.0
    return CurveStats(
        start_value=float(curve[0]),
        end_value=float(curve[-1]),
        total_return=float(total),
        cagr=float(cagr),
        max_drawdown_pct=float(np.max(drawdown_series(curve))),
        sharpe=mean / sd * math.sqrt(SESSIONS_PER_YEAR) if sd > 0 else 0.0,
        volatility=sd * math.sqrt(SESSIONS_PER_YEAR),
        sessions=n,
    )


def grouped(trades: Sequence[Trade], key: Callable[[Trade], str]) -> dict[str, TradeStats]:
    groups: dict[str, list[Trade]] = {}
    for t in trades:
        groups.setdefault(key(t), []).append(t)
    return {k: trade_stats(v) for k, v in sorted(groups.items())}


def yearly_returns(days: Sequence[date], curve: Array) -> dict[str, float]:
    """Calendar-year return of an equity curve (first year from its start)."""
    out: dict[str, float] = {}
    start_value = curve[0] if len(curve) else 0.0
    for i, d in enumerate(days):
        last_of_year = i == len(days) - 1 or days[i + 1].year != d.year
        if last_of_year:
            out[str(d.year)] = float(curve[i] / start_value - 1) if start_value else 0.0
            start_value = curve[i]
    return out


# --- Deflated Sharpe ratio (Bailey and Lopez de Prado, 2014) ---------------------------


def expected_max_sharpe(trial_sharpes: Sequence[float]) -> float:
    """Expected maximum of N per-period Sharpe ratios under the null of no skill,
    given the variance of the trials' Sharpe ratios."""
    n = len(trial_sharpes)
    if n < 2:
        return 0.0
    var = float(np.var(trial_sharpes, ddof=1))
    norm = NormalDist()
    return math.sqrt(var) * (
        (1 - EULER_GAMMA) * norm.inv_cdf(1 - 1 / n)
        + EULER_GAMMA * norm.inv_cdf(1 - 1 / (n * math.e))
    )


def deflated_sharpe(returns: Array, trial_sharpes: Sequence[float]) -> float:
    """Probability that the true (per-period) Sharpe ratio of `returns` is above the
    best one would expect by luck from that many trials. 0.95 or more is the usual
    bar. `trial_sharpes` are per-period Sharpe ratios of every variant tried."""
    r = np.asarray(returns, dtype=float)
    t = len(r)
    if t < 3:
        return 0.0
    sd = float(np.std(r, ddof=1))
    if sd == 0:
        return 0.0
    sr = float(np.mean(r)) / sd
    z = (r - np.mean(r)) / np.std(r)
    skew = float(np.mean(z**3))
    kurt = float(np.mean(z**4))
    sr0 = expected_max_sharpe(trial_sharpes)
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    if denom <= 0:
        return 0.0
    return NormalDist().cdf((sr - sr0) * math.sqrt(t - 1) / math.sqrt(denom))


def per_period_sharpe(curve: Array) -> float:
    r = daily_returns(curve)
    if len(r) < 2:
        return 0.0
    sd = float(np.std(r, ddof=1))
    return float(np.mean(r)) / sd if sd > 0 else 0.0


# --- Section 6 gates -------------------------------------------------------------------


@dataclass(frozen=True)
class Gate:
    key: str
    label: str
    value: str
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {k: _clean(v) for k, v in asdict(self).items()}


@dataclass(frozen=True)
class GateRules:
    min_expectancy_r: float = 0.15
    min_profit_factor: float = 1.3
    max_drawdown_pct: float = 20.0
    min_trades: int = 100
    min_positive_regimes: int = 2


def gates(
    stats: TradeStats,
    curve: CurveStats,
    by_regime: dict[str, TradeStats],
    benchmark: CurveStats,
    holdout: TradeStats | None,
    rules: GateRules | None = None,
) -> list[Gate]:
    rules = rules or GateRules()
    positive = [k for k, v in by_regime.items() if v.trades and v.expectancy_r > 0]
    out = [
        Gate(
            "expectancy",
            f"Expectancy above {rules.min_expectancy_r}R",
            f"{stats.expectancy_r:.3f}R",
            stats.expectancy_r > rules.min_expectancy_r,
        ),
        Gate(
            "profit_factor",
            f"Profit factor at least {rules.min_profit_factor}",
            f"{stats.profit_factor:.2f}",
            stats.profit_factor >= rules.min_profit_factor,
        ),
        Gate(
            "drawdown",
            f"Max drawdown at most {rules.max_drawdown_pct:g}%",
            f"{curve.max_drawdown_pct:.1f}%",
            curve.max_drawdown_pct <= rules.max_drawdown_pct,
        ),
        Gate(
            "trades",
            f"At least {rules.min_trades} trades",
            str(stats.trades),
            stats.trades >= rules.min_trades,
        ),
        Gate(
            "regimes",
            f"Positive in at least {rules.min_positive_regimes} of 3 regimes",
            ", ".join(positive) or "none",
            len(positive) >= rules.min_positive_regimes,
        ),
        Gate(
            "benchmark",
            "Better risk-adjusted return (Sharpe) than buy-and-hold Nifty 500",
            f"{curve.sharpe:.2f} vs {benchmark.sharpe:.2f}",
            curve.sharpe > benchmark.sharpe,
        ),
    ]
    if holdout is not None:
        out.append(
            Gate(
                "holdout",
                "Final 12-month holdout has positive expectancy",
                f"{holdout.expectancy_r:.3f}R over {holdout.trades} trades",
                holdout.trades > 0 and holdout.expectancy_r > 0,
            )
        )
    return out
