"""Walk-forward evaluation of one strategy (spec section 6).

1. The first `WARMUP_SESSIONS` are only used to settle indicators.
2. The latest 12 months are held out as a final test.
3. Before the holdout, yearly test windows start once there are at least two years
   of tradable history before them; each is traded with the grid point that did best
   on everything before it (expanding training window). The holdout is traded with
   the grid point chosen on everything before the holdout.
4. One continuous simulation trades the test windows and the holdout, switching grid
   point at each boundary. Only these out-of-sample results are reported; every grid
   point's training numbers are logged.

Training numbers come from one simulation per grid point over the whole pre-holdout
period. A simulation's equity up to a day uses only data up to that day, so cutting
it at a test window's start leaks nothing from the test window.
"""

import hashlib
import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any

import numpy as np

from app.backtest.costs import CostModel, Realised, TaxRules, estimate_tax
from app.backtest.engine import Book, PortfolioRules, SimResult, Trade, Variant, simulate
from app.backtest.market import Market
from app.backtest.stats import (
    CurveStats,
    GateRules,
    curve_stats,
    daily_rate,
    daily_returns,
    deflated_sharpe,
    drawdown_series,
    gates,
    grouped,
    per_period_sharpe,
    trade_stats,
    yearly_returns,
)
from app.backtest.strategies import Combined, Params, Strategy, params_label

ENGINE_VERSION = "engine-v3"
WARMUP_SESSIONS = 252
MIN_TRAIN_YEARS = 2
HOLDOUT_MONTHS = 12
TEST_MONTHS = 12
MIN_TRAIN_TRADES = 30


def _months_before(day: date, months: int) -> date:
    """The same day of the month `months` earlier (later if negative), clamped to the
    month's last day."""
    total = day.year * 12 + day.month - 1 - months
    year, month = divmod(total, 12)
    for d in range(day.day, 27, -1) if day.day > 28 else [day.day]:
        try:
            return date(year, month + 1, d)
        except ValueError:
            continue
    return date(year, month + 1, 28)


@dataclass(frozen=True)
class Folds:
    first_tradable: int
    test_starts: list[int]  # session index of each test window's first day
    holdout_start: int
    end: int


def make_folds(days: list[date]) -> Folds:
    if len(days) <= WARMUP_SESSIONS + 1:
        raise ValueError("not enough history for a walk-forward test")
    first = WARMUP_SESSIONS
    end = len(days) - 1
    holdout_day = _months_before(days[end], HOLDOUT_MONTHS) + timedelta(days=1)
    idx = np.array(days, dtype="datetime64[D]")
    holdout_start = int(np.searchsorted(idx, np.datetime64(holdout_day)))
    earliest = _months_before(days[first], -12 * MIN_TRAIN_YEARS)
    starts = []
    boundary = holdout_day
    while True:
        boundary = _months_before(boundary, TEST_MONTHS)
        if boundary < earliest:
            break
        starts.append(int(np.searchsorted(idx, np.datetime64(boundary))))
    starts.sort()
    if not starts:
        raise ValueError(
            f"need at least {MIN_TRAIN_YEARS} years of history after warm-up before the "
            f"{HOLDOUT_MONTHS}-month holdout"
        )
    return Folds(first, starts, holdout_start, end)


@dataclass
class VariantLog:
    window: str  # "test 2019-10-01" or "holdout"
    label: str
    params: Params
    train_start: date
    train_end: date
    trades: int
    expectancy_r: float
    sharpe: float
    chosen: bool


@dataclass
class Evaluation:
    strategy: Strategy | Combined
    folds: Folds
    days: list[date]
    sim: SimResult
    schedule: list[tuple[int, str, Params]]
    variant_logs: list[VariantLog]
    oos_trades: list[Trade]
    holdout_trades: list[Trade]
    summary: dict[str, Any]
    equity: list[dict[str, Any]]
    live_eligible: bool
    fingerprint: str
    notes: list[str] = field(default_factory=list)


def market_fingerprint(m: Market) -> str:
    """Hash of the prices, universe and scores a backtest saw, so two runs can be
    shown to use the same data."""
    h = hashlib.sha256()
    h.update("|".join(str(d) for d in m.days).encode())
    h.update("|".join(m.symbols).encode())
    for arr in (m.open, m.high, m.low, m.close, m.universe, m.score):
        h.update(np.ascontiguousarray(np.nan_to_num(arr, nan=-1.0)).tobytes())
    for extra in (m.results_blackout, m.news_score):  # M6 inputs, when loaded
        if extra is not None:
            h.update(np.ascontiguousarray(extra).tobytes())
    return h.hexdigest()[:16]


def brains_summary(m: Market, strategy: Strategy) -> dict[str, Any]:
    """Which M6 inputs a run used, and which years they cover."""
    news_years: list[int] = []
    if m.news_score is not None:
        active = np.any(m.news_score != 50.0, axis=0)
        news_years = sorted({m.days[t].year for t in np.flatnonzero(active)})
    blackout_years: list[int] = []
    if m.results_blackout is not None:
        active = np.any(m.results_blackout, axis=0)
        blackout_years = sorted({m.days[t].year for t in np.flatnonzero(active)})
    return {
        "results_blackout": strategy.results_blackout,
        "results_calendar_years": blackout_years,
        "min_news_score": strategy.min_news_score,
        "news_labeller": m.news_labeller,
        "news_years": news_years,
    }


def _choose(
    sims: dict[str, SimResult],
    first: int,
    until: int,
    days: list[date],
    window: str,
    variants: dict[str, Variant],
    default: str,
    risk_free_pct: float,
) -> tuple[str, list[VariantLog]]:
    logs = []
    best_label, best_sharpe = default, -math.inf
    for label, sim in sims.items():
        curve = sim.equity[: until - sim.start]
        closed = [t for t in sim.trades if t.exit_day < until and not t.open_at_end]
        stats = trade_stats(closed)
        sharpe = curve_stats(curve, risk_free_pct).sharpe if len(curve) > 1 else 0.0
        logs.append(
            VariantLog(
                window,
                label,
                variants[label].params,
                days[first],
                days[until - 1],
                stats.trades,
                stats.expectancy_r,
                sharpe,
                False,
            )
        )
        if stats.trades >= MIN_TRAIN_TRADES and sharpe > best_sharpe:
            best_label, best_sharpe = label, sharpe
    for log in logs:
        log.chosen = log.label == best_label
    return best_label, logs


@dataclass
class Selection:
    """A strategy's grid points, their training runs and the grid point chosen for
    each test window and the holdout."""

    strategy: Strategy
    variants: dict[str, Variant]
    training: dict[str, SimResult]
    schedule: list[tuple[int, str, Params]]
    logs: list[VariantLog]

    def traded(self) -> list[tuple[int, Variant]]:
        return [(s, self.variants[label]) for s, label, _ in self.schedule]


def select(
    market: Market,
    strategy: Strategy,
    folds: Folds,
    rules: PortfolioRules,
    costs: CostModel,
) -> Selection:
    """Train every grid point on the history before each window and pick the best."""
    m = market
    variants = {
        params_label(p): Variant(params_label(p), p, strategy.entries(m, p), strategy.exits(m, p))
        for p in strategy.grid
    }
    default = params_label(strategy.default)
    pre_end = folds.holdout_start - 1
    training = {
        label: simulate(
            m,
            strategy.tier,
            [(folds.first_tradable, v)],
            folds.first_tradable,
            pre_end,
            rules,
            costs,
        )
        for label, v in variants.items()
    }
    logs: list[VariantLog] = []
    schedule: list[tuple[int, str, Params]] = []
    for start in [*folds.test_starts, folds.holdout_start]:
        window = "holdout" if start == folds.holdout_start else f"test {m.days[start]}"
        label, window_logs = _choose(
            training,
            folds.first_tradable,
            start,
            m.days,
            window,
            variants,
            default,
            rules.cash_rate_pct,
        )
        logs.extend(window_logs)
        schedule.append((start, label, variants[label].params))
    return Selection(strategy, variants, training, schedule, logs)


def _rules_for(strategy: Strategy, rules: PortfolioRules | None) -> PortfolioRules:
    rules = rules or PortfolioRules()
    return replace(rules, results_blackout=True) if strategy.results_blackout else rules


def evaluate(
    market: Market,
    strategy: Strategy,
    rules: PortfolioRules | None = None,
    costs: CostModel | None = None,
    gate_rules: GateRules | None = None,
    tax_rules: TaxRules | None = None,
) -> Evaluation:
    rules = _rules_for(strategy, rules)
    costs = costs or CostModel()
    folds = make_folds(market.days)
    sel = select(market, strategy, folds, rules, costs)
    oos_start = folds.test_starts[0]
    sim = simulate(market, strategy.tier, sel.traded(), oos_start, folds.end, rules, costs)
    trial_sharpes = [
        per_period_sharpe(s.equity, rules.cash_rate_pct) for s in sel.training.values()
    ]
    return _report(
        market,
        strategy,
        folds,
        sim,
        rules,
        costs,
        gate_rules,
        tax_rules,
        trial_sharpes=trial_sharpes,
        brains=brains_summary(market, strategy),
        rules_text=strategy.rules(sel.variants[sel.schedule[-1][1]].params),
        schedule=sel.schedule,
        schedule_json=[
            {"from": str(market.days[s]), "variant": label, "params": params}
            for s, label, params in sel.schedule
        ],
        variant_logs=sel.logs,
        extra={},
    )


def evaluate_combined(
    market: Market,
    book: Combined,
    rules: PortfolioRules | None = None,
    costs: CostModel | None = None,
    gate_rules: GateRules | None = None,
    tax_rules: TaxRules | None = None,
    all_trial_sharpes: Sequence[float] | None = None,
) -> Evaluation:
    """Walk-forward test of a combined book (docs/plans/combined-book-v1.md). Each
    member picks its grid points exactly as its own `evaluate` does; nothing new is
    chosen. One simulation then trades every member in one account over the same test
    windows and holdout. `all_trial_sharpes` (every variant of every strategy tried
    before, training Sharpe) gives a second deflated Sharpe with this book added as
    one more trial."""
    rules = rules or PortfolioRules()
    if any(s.results_blackout for s in book.members):
        raise ValueError(f"{book.key}: members with a results blackout are not supported")
    costs = costs or CostModel()
    m = market
    folds = make_folds(m.days)
    selections = [select(m, s, folds, rules, costs) for s in book.members]
    books = []
    for sel in selections:
        name = sel.strategy.version
        books.append(
            Book(
                name,
                [(s, replace(v, label=f"{name}: {v.label}")) for s, v in sel.traded()],
            )
        )
    oos_start = folds.test_starts[0]
    sim = simulate(m, book.tier, books, oos_start, folds.end, rules, costs)
    own = [
        per_period_sharpe(t.equity, rules.cash_rate_pct)
        for sel in selections
        for t in sel.training.values()
    ]
    starts = sorted({s for sel in selections for s, _, _ in sel.schedule})
    schedule: list[tuple[int, str, Params]] = []
    schedule_json: list[dict[str, Any]] = []
    for start in starts:
        for sel in selections:
            label, params = next((lab, p) for s, lab, p in reversed(sel.schedule) if s <= start)
            name = f"{sel.strategy.version}: {label}"
            schedule.append((start, name, params))
            schedule_json.append({"from": str(m.days[start]), "variant": name, "params": params})
    logs = [
        replace(log, label=f"{sel.strategy.version}: {log.label}")
        for sel in selections
        for log in sel.logs
    ]
    last = {sel.strategy.key: sel.variants[sel.schedule[-1][1]].params for sel in selections}
    split = folds.holdout_start - oos_start
    extra: dict[str, Any] = {
        "members": [s.version for s in book.members],
        "by_strategy": {
            sel.strategy.version: {
                "out_of_sample": trade_stats(
                    [
                        t
                        for t in sim.trades
                        if t.book == sel.strategy.version and t.signal_day < folds.holdout_start
                    ]
                ).to_dict(),
                "holdout": trade_stats(
                    [
                        t
                        for t in sim.trades
                        if t.book == sel.strategy.version and t.signal_day >= folds.holdout_start
                    ]
                ).to_dict(),
            }
            for sel in selections
        },
    }
    if all_trial_sharpes is not None:
        oos_curve = sim.equity[:split]
        trials = [*all_trial_sharpes, per_period_sharpe(oos_curve, rules.cash_rate_pct)]
        excess = daily_returns(oos_curve) - daily_rate(rules.cash_rate_pct)
        extra["deflated_sharpe_all"] = round(deflated_sharpe(excess, trials), 4)
        extra["trials_all"] = len(trials)
    notes = [
        "Both strategies' holdout results were seen before this book's rules were fixed, "
        "so the holdout is not a clean test: paper trading decides.",
        "The 30% sector cap and the correlation check are not simulated (no point-in-time "
        "sectors); paper trading applies them.",
    ]
    return _report(
        m,
        book,
        folds,
        sim,
        rules,
        costs,
        gate_rules,
        tax_rules,
        trial_sharpes=own,
        brains={
            "results_blackout": False,
            "results_calendar_years": brains_summary(m, book.members[0])["results_calendar_years"],
            "min_news_score": None,
            "news_labeller": m.news_labeller,
            "news_years": [],
        },
        rules_text=book.rules(last),
        schedule=schedule,
        schedule_json=schedule_json,
        variant_logs=logs,
        extra={"combined": extra},
        first_notes=notes,
    )


def all_trial_sharpes(
    market: Market,
    strategies: Iterable[Strategy],
    rules: PortfolioRules | None = None,
    costs: CostModel | None = None,
) -> list[float]:
    """Every grid point's per-period Sharpe over the whole pre-holdout period, the
    trial set of the reports' "all variants" deflated Sharpe."""
    costs = costs or CostModel()
    folds = make_folds(market.days)
    out = []
    for strategy in strategies:
        r = _rules_for(strategy, rules)
        for p in strategy.grid:
            v = Variant(params_label(p), p, strategy.entries(market, p), strategy.exits(market, p))
            sim = simulate(
                market,
                strategy.tier,
                [(folds.first_tradable, v)],
                folds.first_tradable,
                folds.holdout_start - 1,
                r,
                costs,
            )
            out.append(per_period_sharpe(sim.equity, r.cash_rate_pct))
    return out


def _report(
    m: Market,
    strategy: Strategy | Combined,
    folds: Folds,
    sim: SimResult,
    rules: PortfolioRules,
    costs: CostModel,
    gate_rules: GateRules | None,
    tax_rules: TaxRules | None,
    *,
    trial_sharpes: list[float],
    brains: dict[str, Any],
    rules_text: list[str],
    schedule: list[tuple[int, str, Params]],
    schedule_json: list[dict[str, Any]],
    variant_logs: list[VariantLog],
    extra: dict[str, Any],
    first_notes: Sequence[str] = (),
) -> Evaluation:
    days = m.days
    oos_start = folds.test_starts[0]
    oos_trades = [t for t in sim.trades if t.signal_day < folds.holdout_start]
    holdout_trades = [t for t in sim.trades if t.signal_day >= folds.holdout_start]
    split = folds.holdout_start - oos_start
    oos_curve = sim.equity[:split]
    holdout_curve = sim.equity[split - 1 :]
    oos_days = days[oos_start : folds.holdout_start]

    def bench(a: int, b: int) -> CurveStats:
        return curve_stats(m.nifty500[a : b + 1], rules.cash_rate_pct)

    oos_stats = trade_stats(oos_trades)
    oos_curve_stats = curve_stats(oos_curve, rules.cash_rate_pct)
    holdout_stats = trade_stats(holdout_trades)
    by_regime = grouped(oos_trades, lambda t: t.regime.value)
    benchmark = bench(oos_start, folds.holdout_start - 1)
    gate_list = gates(oos_stats, oos_curve_stats, by_regime, benchmark, holdout_stats, gate_rules)
    excess = daily_returns(oos_curve) - daily_rate(rules.cash_rate_pct)
    dsr = deflated_sharpe(excess, trial_sharpes)

    def tax_view(trades: list[Trade], first: int, last: int) -> dict[str, Any]:
        sales = [
            Realised(
                days[t.exit_day],
                t.net_pnl - t.dividends,
                (days[t.exit_day] - days[t.entry_day]).days,
            )
            for t in trades
        ]
        divs = [(days[t.exit_day], t.dividends) for t in trades if t.dividends]
        interest = [(days[t], a) for t, a in sim.interest if first <= t <= last]
        estimate = estimate_tax(sales, divs, tax_rules, interest)
        earned = sum(a for _, a in interest)
        pre_tax = sum(t.net_pnl for t in trades) + earned
        return {
            "pre_tax_pnl": round(pre_tax, 2),
            "interest": round(earned, 2),
            "estimated_tax": round(estimate.total, 2),
            "post_tax_pnl": round(pre_tax - estimate.total, 2),
            "years": [
                {
                    "fy": f"FY{y.year}-{(y.year + 1) % 100:02d}",
                    "stcg": round(y.stcg, 2),
                    "ltcg": round(y.ltcg, 2),
                    "dividends": round(y.dividends, 2),
                    "interest": round(y.interest, 2),
                    "tax": round(y.tax, 2),
                    "loss_carried": round(y.loss_carried, 2),
                }
                for y in estimate.years
            ],
        }

    skip_counts = Counter(s.reason for s in sim.skipped)
    exit_counts = Counter(t.exit_reason.split(" (")[0] for t in sim.trades)
    notes = list(first_notes)
    if not m.security_list_known[oos_start:].all():
        known = int(np.argmax(m.security_list_known)) if m.security_list_known.any() else None
        notes.append(
            "GSM exclusion only applies from the first NSE security list "
            f"({days[known] if known is not None else 'none loaded'}); before that GSM "
            "stocks could be traded."
        )
    notes.append("ASM exclusion uses the manually imported lists only, so it is not point in time.")
    stopped = [t for t in sim.trades if t.exit_reason.startswith("stopped trading")]
    if stopped:
        notes.append(
            f"{len(stopped)} trades were in stocks that stopped trading; they are valued at "
            "the last close, which can flatter the result."
        )
    fail_days = int(np.sum(m.quality_fail[oos_start:]))
    if fail_days:
        notes.append(f"No new entries on {fail_days} days whose data-quality report failed.")
    notes.append(
        "Benchmark is the Nifty 500 price index (dividends not included). Idle cash "
        f"earns {rules.cash_rate_pct:g}% a year (a liquid fund), taxed at the 30% slab "
        "in the tax estimate; Sharpe ratios, for the strategy and the benchmark, "
        "count only returns above that rate."
    )

    summary: dict[str, Any] = {
        "engine_version": ENGINE_VERSION,
        "brains": brains,
        "periods": {
            "data": [str(days[0]), str(days[-1])],
            "first_tradable": str(days[folds.first_tradable]),
            "out_of_sample": [str(days[oos_start]), str(days[folds.holdout_start - 1])],
            "holdout": [str(days[folds.holdout_start]), str(days[folds.end])],
        },
        "out_of_sample": {
            "trades": oos_stats.to_dict(),
            "curve": oos_curve_stats.to_dict(),
            "benchmark": benchmark.to_dict(),
            "by_year": {
                k: v.to_dict()
                for k, v in grouped(oos_trades, lambda t: str(days[t.entry_day].year)).items()
            },
            "by_regime": {k: v.to_dict() for k, v in by_regime.items()},
            "yearly_returns": yearly_returns(oos_days, oos_curve),
            "benchmark_yearly_returns": yearly_returns(
                oos_days, m.nifty500[oos_start : folds.holdout_start]
            ),
            "deflated_sharpe": round(dsr, 4),
            "variants_tried": len(trial_sharpes),
            "tax": tax_view(oos_trades, oos_start, folds.holdout_start - 1),
        },
        "holdout": {
            "trades": holdout_stats.to_dict(),
            "curve": curve_stats(holdout_curve, rules.cash_rate_pct).to_dict(),
            "benchmark": bench(folds.holdout_start - 1, folds.end).to_dict(),
        },
        "gates": [g.to_dict() for g in gate_list],
        "schedule": schedule_json,
        "skipped_entries": dict(skip_counts.most_common()),
        "exit_reasons": dict(exit_counts.most_common()),
        "brake_events": [{"date": str(days[t]), "event": e} for t, e in sim.brake_events],
        "rules": rules_text,
        "settings": {
            "portfolio": rules.__dict__,
            "costs": {k: v for k, v in costs.__dict__.items() if k != "slippage_buckets"}
            | {"slippage_buckets": [list(b) for b in costs.slippage_buckets]},
        },
        "notes": notes,
        **extra,
    }
    live = all(g.passed for g in gate_list)
    summary["live_eligible"] = live
    dd = drawdown_series(sim.equity)
    bench_curve = m.nifty500[oos_start : folds.end + 1]
    base = bench_curve[0] if len(bench_curve) and bench_curve[0] else 1.0
    equity = [
        {
            "date": str(days[oos_start + i]),
            "equity": round(float(v), 2),
            "drawdown_pct": round(float(dd[i]), 3),
            "benchmark": round(float(bench_curve[i] / base * sim.equity[0]), 2)
            if not math.isnan(bench_curve[i])
            else None,
        }
        for i, v in enumerate(sim.equity)
    ]
    return Evaluation(
        strategy=strategy,
        folds=folds,
        days=days,
        sim=sim,
        schedule=schedule,
        variant_logs=variant_logs,
        oos_trades=oos_trades,
        holdout_trades=holdout_trades,
        summary=summary,
        equity=equity,
        live_eligible=live,
        fingerprint=market_fingerprint(m),
        notes=notes,
    )
