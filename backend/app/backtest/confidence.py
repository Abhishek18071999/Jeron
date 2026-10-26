"""How much a backtest's numbers can be trusted: the evidence-strength layer on top of
the seven section 6 gates (docs/plans/confidence-v1.md, decision 0018). Pure.

The gates ask "is the point estimate good enough?". This asks "how sure are we?":

- 95% bootstrap intervals for expectancy, profit factor and win rate (trades drawn
  with replacement), and for the equity curve's max drawdown and CAGR (a block
  bootstrap of daily returns, blocks of `BLOCK_SESSIONS`, so a bad month stays a bad
  month);
- a Monte Carlo of the trade order: the losing streaks and R drawdowns the same trades
  could have produced in another order;
- concentration: the result without its best trades, its best year, its best sector;
- robustness (computed by the walk-forward, `app.backtest.walkforward.robustness`):
  double slippage, charges up by half, entries one session late, and every other grid
  point of the strategy traded alone.

The rating (`evidence`) is separate from the gates and changes nothing a strategy
does: passing the gates lets a strategy paper-trade; only the evidence and the paper
record argue for real capital. Every threshold is fixed here, before any rating was
seen. Bump `CONFIDENCE_VERSION` when a threshold or a check changes.
"""

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from app.backtest.features import Array
from app.backtest.stats import SESSIONS_PER_YEAR, daily_returns, drawdown_series

CONFIDENCE_VERSION = "confidence-v1"
RESAMPLES = 2000
SEED = 18
LEVEL = 0.95
BLOCK_SESSIONS = 20
TOP_TRADES = 5
# The checks' thresholds.
MIN_TRADES_TO_RATE = 30
MIN_TRADES = 100
MIN_HOLDOUT_TRADES = 20
MIN_DEFLATED_SHARPE = 0.95
MIN_GRID_POSITIVE = 2 / 3
MAX_SECTOR_SHARE = 0.5
# Strong: every check passes. Moderate: the expectancy interval and the holdout pass,
# and at most this many of the others fail.
MODERATE_MAX_FAILS = 2


def _clean(v: Any) -> Any:
    if isinstance(v, float | np.floating):
        v = float(v)
        if math.isnan(v):
            return None
        if math.isinf(v):
            return "inf" if v > 0 else "-inf"
        return round(v, 4)
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_clean(x) for x in v]
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


@dataclass(frozen=True)
class Interval:
    estimate: float
    low: float
    high: float

    def to_dict(self) -> dict[str, Any]:
        return {k: _clean(v) for k, v in asdict(self).items()}


def _quantiles(values: Array) -> tuple[float, float]:
    tail = (1 - LEVEL) / 2 * 100
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        return math.nan, math.nan
    lo, hi = np.percentile(finite, [tail, 100 - tail])
    return float(lo), float(hi)


def profit_factor(pnl: Array) -> float:
    gains = float(pnl[pnl > 0].sum())
    losses = float(-pnl[pnl < 0].sum())
    if losses <= 0:
        return math.inf if gains > 0 else 0.0
    return gains / losses


@dataclass(frozen=True)
class TradeIntervals:
    trades: int
    expectancy_r: Interval
    profit_factor: Interval
    win_rate: Interval
    # Share of resamples with expectancy above 0: how often a sample like this one
    # comes out positive (not the probability that the edge is real).
    positive_share: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "trades": self.trades,
            "expectancy_r": self.expectancy_r.to_dict(),
            "profit_factor": self.profit_factor.to_dict(),
            "win_rate": self.win_rate.to_dict(),
            "positive_share": _clean(self.positive_share),
        }


def trade_intervals(
    rs: Sequence[float], pnl: Sequence[float], resamples: int = RESAMPLES, seed: int = SEED
) -> TradeIntervals | None:
    """95% bootstrap intervals of the trades' statistics (percentile method). None
    without at least two trades."""
    r = np.asarray(rs, dtype=float)
    p = np.asarray(pnl, dtype=float)
    n = len(r)
    if n < 2:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(resamples, n))
    means = r[idx].mean(axis=1)
    wins = (r[idx] > 0).mean(axis=1)
    samples = p[idx]
    gains = np.where(samples > 0, samples, 0.0).sum(axis=1)
    losses = -np.where(samples < 0, samples, 0.0).sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        pfs = np.where(losses > 0, gains / losses, np.where(gains > 0, np.inf, 0.0))
    return TradeIntervals(
        trades=n,
        expectancy_r=Interval(float(r.mean()), *_quantiles(means)),
        profit_factor=Interval(profit_factor(p), *_quantiles(pfs)),
        win_rate=Interval(float((r > 0).mean()), *_quantiles(wins)),
        positive_share=float((means > 0).mean()),
    )


def _max_dd(curve: Array) -> float:
    return float(np.max(drawdown_series(curve))) if len(curve) else 0.0


def _cagr(curve: Array) -> float:
    years = (len(curve) - 1) / SESSIONS_PER_YEAR
    if years <= 0 or curve[0] <= 0 or curve[-1] <= 0:
        return 0.0
    return float((curve[-1] / curve[0]) ** (1 / years) - 1)


@dataclass(frozen=True)
class CurveIntervals:
    max_drawdown_pct: Interval
    cagr: Interval
    # The drawdown a bad-luck path (95th percentile) reaches: what to be ready for.
    drawdown_95_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_drawdown_pct": self.max_drawdown_pct.to_dict(),
            "cagr": self.cagr.to_dict(),
            "drawdown_95_pct": _clean(self.drawdown_95_pct),
            "block_sessions": BLOCK_SESSIONS,
        }


def curve_intervals(
    curve: Array, resamples: int = RESAMPLES, seed: int = SEED, block: int = BLOCK_SESSIONS
) -> CurveIntervals | None:
    """Moving-block bootstrap of the curve's daily returns: paths of the same length
    built from random runs of `block` consecutive sessions."""
    curve = np.asarray(curve, dtype=float)
    rets = daily_returns(curve)
    n = len(rets)
    if n < 2 * block or curve[0] <= 0:
        return None
    rng = np.random.default_rng(seed)
    blocks = math.ceil(n / block)
    starts = rng.integers(0, n - block + 1, size=(resamples, blocks))
    idx = (starts[:, :, None] + np.arange(block)).reshape(resamples, -1)[:, :n]
    paths = np.cumprod(1 + rets[idx], axis=1)
    paths = np.hstack([np.ones((resamples, 1)), paths])
    peaks = np.maximum.accumulate(paths, axis=1)
    dds = np.max((1 - paths / peaks) * 100, axis=1)
    years = n / SESSIONS_PER_YEAR
    with np.errstate(invalid="ignore"):
        cagrs = np.where(paths[:, -1] > 0, paths[:, -1] ** (1 / years) - 1, -1.0)
    return CurveIntervals(
        max_drawdown_pct=Interval(_max_dd(curve), *_quantiles(dds)),
        cagr=Interval(_cagr(curve), *_quantiles(cagrs)),
        drawdown_95_pct=float(np.percentile(dds, 95)),
    )


@dataclass(frozen=True)
class OrderRisk:
    """What the same trades in another order could have done (Monte Carlo of the order,
    trades drawn with replacement)."""

    losing_streak_median: int
    losing_streak_95: int
    drawdown_r_median: float  # peak-to-trough of the cumulative R
    drawdown_r_95: float

    def to_dict(self) -> dict[str, Any]:
        return {k: _clean(v) for k, v in asdict(self).items()}


def order_risk(
    rs: Sequence[float], resamples: int = RESAMPLES, seed: int = SEED
) -> OrderRisk | None:
    r = np.asarray(rs, dtype=float)
    n = len(r)
    if n < 2:
        return None
    rng = np.random.default_rng(seed)
    paths = r[rng.integers(0, n, size=(resamples, n))]
    cum = np.cumsum(paths, axis=1)
    peaks = np.maximum.accumulate(np.hstack([np.zeros((resamples, 1)), cum]), axis=1)[:, 1:]
    dd = np.max(peaks - cum, axis=1)
    losing = paths <= 0
    streak = np.zeros(resamples, dtype=int)
    run = np.zeros(resamples, dtype=int)
    for k in range(n):
        run = np.where(losing[:, k], run + 1, 0)
        streak = np.maximum(streak, run)
    return OrderRisk(
        losing_streak_median=int(np.median(streak)),
        losing_streak_95=int(np.percentile(streak, 95)),
        drawdown_r_median=float(np.median(dd)),
        drawdown_r_95=float(np.percentile(dd, 95)),
    )


@dataclass(frozen=True)
class Concentration:
    trades: int
    total_r: float
    top_share: float  # share of the total R from the best `TOP_TRADES` trades
    without_top_r: float  # expectancy without them
    best_year: str | None
    without_best_year_r: float | None
    best_sector: str | None  # None: no sector known
    best_sector_share: float | None  # of the positive R summed by sector
    without_best_sector_r: float | None
    sectors_known: float  # share of trades with a sector

    def to_dict(self) -> dict[str, Any]:
        return {k: _clean(v) for k, v in asdict(self).items()}


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def concentration(
    rs: Sequence[float], years: Sequence[str], sectors: Sequence[str | None]
) -> Concentration | None:
    """Does the result rest on a handful of trades, one year or one sector? `years`
    and `sectors` are per trade, in the order of `rs`."""
    n = len(rs)
    if n == 0:
        return None
    total = float(sum(rs))
    ordered = sorted(rs, reverse=True)
    top = ordered[:TOP_TRADES]
    rest = ordered[TOP_TRADES:]
    by_year: dict[str, list[float]] = {}
    for r, y in zip(rs, years, strict=True):
        by_year.setdefault(y, []).append(r)
    best_year = max(by_year, key=lambda y: sum(by_year[y])) if len(by_year) > 1 else None
    by_sector: dict[str, list[float]] = {}
    for r, s in zip(rs, sectors, strict=True):
        if s:
            by_sector.setdefault(s, []).append(r)
    best_sector = max(by_sector, key=lambda s: sum(by_sector[s])) if by_sector else None
    positive = sum(max(sum(v), 0.0) for v in by_sector.values())
    share = (
        max(sum(by_sector[best_sector]), 0.0) / positive
        if best_sector is not None and positive > 0
        else None
    )
    return Concentration(
        trades=n,
        total_r=total,
        top_share=sum(top) / total if total > 0 else math.nan,
        without_top_r=_mean(rest) or 0.0 if rest else math.nan,
        best_year=best_year,
        without_best_year_r=_mean([r for r, y in zip(rs, years, strict=True) if y != best_year])
        if best_year
        else None,
        best_sector=best_sector,
        best_sector_share=share,
        without_best_sector_r=_mean(
            [r for r, s in zip(rs, sectors, strict=True) if s != best_sector]
        )
        if best_sector
        else None,
        sectors_known=sum(1 for s in sectors if s) / n,
    )


@dataclass(frozen=True)
class Scenario:
    key: str
    label: str
    trades: int
    expectancy_r: float
    profit_factor: float

    def to_dict(self) -> dict[str, Any]:
        return {k: _clean(v) for k, v in asdict(self).items()}


@dataclass(frozen=True)
class GridPoint:
    label: str
    trades: int
    expectancy_r: float
    chosen: bool  # traded in the latest window

    def to_dict(self) -> dict[str, Any]:
        return {k: _clean(v) for k, v in asdict(self).items()}


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    value: str
    passed: bool | None  # None: could not be checked

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["passed"] = None if self.passed is None else bool(self.passed)  # not numpy's
        return out


@dataclass
class Evidence:
    rating: str  # "strong" / "moderate" / "weak" / "insufficient"
    checks: list[Check]
    summary: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rating": self.rating,
            "summary": self.summary,
            "checks": [c.to_dict() for c in self.checks],
            "notes": self.notes,
        }


def _r(value: float | None) -> str:
    return "-" if value is None or math.isnan(value) else f"{value:+.3f}R"


def evidence(
    oos: TradeIntervals | None,
    holdout_trades: int,
    holdout_expectancy_r: float,
    holdout_profit_factor: float,
    deflated_sharpe: float,
    scenarios: Sequence[Scenario],
    grid: Sequence[GridPoint],
    conc: Concentration | None,
) -> Evidence:
    """The evidence-strength rating and the checks behind it."""
    trades = oos.trades if oos else 0
    checks: list[Check] = []
    if oos is None or trades < MIN_TRADES_TO_RATE:
        return Evidence(
            "insufficient",
            [Check("trades", f"At least {MIN_TRADES_TO_RATE} trades to rate", str(trades), False)],
            f"{trades} out-of-sample trades: too few to say anything about an edge.",
        )
    e = oos.expectancy_r
    checks.append(
        Check("sample", f"At least {MIN_TRADES} out-of-sample trades", str(trades),
              trades >= MIN_TRADES)
    )  # fmt: skip
    checks.append(
        Check(
            "expectancy_ci",
            "95% interval of expectancy above 0R",
            f"{e.low:+.3f}R to {e.high:+.3f}R",
            e.low > 0,
        )
    )
    pf = oos.profit_factor
    checks.append(
        Check(
            "profit_factor_ci",
            "95% interval of profit factor above 1",
            f"{pf.low:.2f} to {pf.high:.2f}",
            pf.low > 1,
        )
    )
    checks.append(
        Check(
            "holdout",
            f"Holdout: at least {MIN_HOLDOUT_TRADES} trades, expectancy above 0, "
            "profit factor above 1",
            f"{holdout_expectancy_r:+.3f}R, profit factor {holdout_profit_factor:.2f} "
            f"over {holdout_trades} trades",
            holdout_trades >= MIN_HOLDOUT_TRADES
            and holdout_expectancy_r > 0
            and holdout_profit_factor > 1,
        )
    )
    checks.append(
        Check(
            "deflated_sharpe",
            f"Deflated Sharpe at least {MIN_DEFLATED_SHARPE} (luck from the variants tried "
            "ruled out)",
            f"{deflated_sharpe:.2f}",
            deflated_sharpe >= MIN_DEFLATED_SHARPE,
        )
    )
    for s in scenarios:
        checks.append(
            Check(
                f"scenario:{s.key}",
                f"Still positive with {s.label}",
                f"{s.expectancy_r:+.3f}R over {s.trades} trades",
                s.trades > 0 and s.expectancy_r > 0,
            )
        )
    if len(grid) > 1:
        positive = sum(1 for g in grid if g.trades and g.expectancy_r > 0)
        checks.append(
            Check(
                "grid",
                f"At least {MIN_GRID_POSITIVE:.0%} of the parameter grid positive on its own",
                f"{positive} of {len(grid)}",
                positive / len(grid) >= MIN_GRID_POSITIVE,
            )
        )
    if conc is not None:
        checks.append(
            Check(
                "without_top",
                f"Still positive without its {TOP_TRADES} best trades",
                _r(conc.without_top_r),
                not math.isnan(conc.without_top_r) and conc.without_top_r > 0,
            )
        )
        if conc.best_year is not None and conc.without_best_year_r is not None:
            checks.append(
                Check(
                    "without_best_year",
                    "Still positive without its best year",
                    f"{_r(conc.without_best_year_r)} without {conc.best_year}",
                    conc.without_best_year_r > 0,
                )
            )
        if conc.best_sector is not None and conc.best_sector_share is not None:
            checks.append(
                Check(
                    "sector",
                    f"No sector more than {MAX_SECTOR_SHARE:.0%} of the gains",
                    f"{conc.best_sector} {conc.best_sector_share:.0%}",
                    conc.best_sector_share <= MAX_SECTOR_SHARE,
                )
            )
    by_key = {c.key: c for c in checks}
    failed = [c for c in checks if c.passed is False]
    core = by_key["expectancy_ci"].passed and by_key["holdout"].passed
    if not failed:
        rating = "strong"
    elif core and len(failed) <= MODERATE_MAX_FAILS:
        rating = "moderate"
    else:
        rating = "weak"
    lines = {
        "strong": "Every check passes: the edge holds up under resampling, higher costs, "
        "late entries and nearby parameters.",
        "moderate": "The edge is positive with 95% confidence and in the holdout, but "
        f"{len(failed)} check{'s' if len(failed) != 1 else ''} failed.",
        "weak": f"{len(failed)} of {len(checks)} checks failed: the evidence does not "
        "show an edge that would survive real trading.",
    }
    return Evidence(
        rating,
        checks,
        lines[rating],
        notes=[
            "Evidence strength is separate from the section 6 gates. Passing the gates "
            "lets a strategy paper-trade; it never promotes it to real money.",
        ],
    )


def report(
    rs: Sequence[float],
    pnl: Sequence[float],
    years: Sequence[str],
    sectors: Sequence[str | None],
    curve: Array,
    holdout_rs: Sequence[float],
    holdout_pnl: Sequence[float],
    deflated_sharpe: float,
    scenarios: Sequence[Scenario] = (),
    grid: Sequence[GridPoint] = (),
) -> dict[str, Any]:
    """The `confidence` block of a backtest summary."""
    oos = trade_intervals(rs, pnl)
    hold = trade_intervals(holdout_rs, holdout_pnl)
    conc = concentration(rs, years, sectors)
    h_pnl = np.asarray(holdout_pnl, dtype=float)
    ev = evidence(
        oos,
        len(holdout_rs),
        float(np.mean(holdout_rs)) if len(holdout_rs) else 0.0,
        profit_factor(h_pnl) if len(h_pnl) else 0.0,
        deflated_sharpe,
        scenarios,
        grid,
        conc,
    )
    curve_iv = curve_intervals(curve)
    order = order_risk(rs)
    notes = list(ev.notes)
    if conc is not None and conc.sectors_known < 1:
        notes.append(
            f"Sectors are today's, not point in time, and known for {conc.sectors_known:.0%} "
            "of the trades."
        )
    return {
        "version": CONFIDENCE_VERSION,
        "level": LEVEL,
        "resamples": RESAMPLES,
        "out_of_sample": oos.to_dict() if oos else None,
        "holdout": hold.to_dict() if hold else None,
        "curve": curve_iv.to_dict() if curve_iv else None,
        "order": order.to_dict() if order else None,
        "concentration": conc.to_dict() if conc else None,
        "scenarios": [s.to_dict() for s in scenarios],
        "grid": [g.to_dict() for g in grid],
        "evidence": ev.to_dict() | {"notes": notes},
    }
