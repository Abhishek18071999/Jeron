"""The 2026-10 trading review's research options (docs/plans/review-v1.md), run on
`rs-pullback-v1`, the only live-eligible strategy, against the same strategy without
them. `python -m app.cli research` writes the comparison as Markdown.

Research only, by construction: the options are `PortfolioRules` fields and an entry
filter that default off, the runs are not saved as backtest runs (so no paper account,
signal, gate or comparison changes), and every option was fixed in the plan before
any run. Each run is the full walk-forward: the grid point is picked on training data
with the option on, results are out-of-sample and after costs, and the latest 12
months are the untouched holdout. Five options are five more trials: a better number
here is a reason to register a new strategy version and paper-trade it, not to switch.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from app.backtest.costs import CostModel
from app.backtest.engine import PortfolioRules, Variant, simulate
from app.backtest.job import missing_inputs
from app.backtest.market import (
    CRASH_GUARD_BELOW_SESSIONS,
    CRASH_GUARD_RETURN,
    CRASH_GUARD_RETURN_SESSIONS,
    Market,
)
from app.backtest.stats import (
    daily_rate,
    daily_returns,
    deflated_sharpe,
    effective_trials,
    per_period_sharpe,
)
from app.backtest.strategies import (
    COMBINED_BOOK,
    RS_PULLBACK,
    STRATEGIES,
    Params,
    Strategy,
    params_label,
)
from app.backtest.walkforward import Evaluation, evaluate, make_folds

Log = Callable[[str], None]
# The quality filter: fund-v1 at least this where it is known (no filing yet passes).
QUALITY_MIN_FUND = 50.0


def _quality_filtered(base: Strategy) -> Strategy:
    def condition(m: Market, p: Params) -> Any:
        fund = m.fund_score
        if fund is None:
            raise ValueError("the quality filter needs fundamentals (run fundamentals-import)")
        ok = np.nan_to_num(fund, nan=100.0) >= QUALITY_MIN_FUND
        return base.condition(m, p) & ok

    return replace(
        base,
        key=f"{base.key}+quality",
        version=f"{base.version}+quality",
        name=f"{base.name} + quality filter",
        condition=condition,
    )


@dataclass(frozen=True)
class Option:
    key: str
    item: str  # the review's item number
    label: str
    rule: str
    rules: dict[str, Any]
    filtered: bool = False  # the quality filter on entries


OPTIONS = (
    Option(
        "results-sell",
        "4",
        "Sell before results",
        "Sell the whole position at the open of the session of a results board meeting "
        "(the first session on or after the meeting date).",
        {"results_exit": "sell"},
    ),
    Option(
        "results-half",
        "4",
        "Halve before results",
        "Sell half at the open of the results meeting's session; the rest stays.",
        {"results_exit": "half"},
    ),
    Option(
        "crash-guard",
        "8",
        "Momentum-crash guard",
        f"No new entries while Nifty 500 is up at least {CRASH_GUARD_RETURN:.0%} over "
        f"{CRASH_GUARD_RETURN_SESSIONS} sessions and was below its 200-day EMA at some "
        f"point in the last {CRASH_GUARD_BELOW_SESSIONS} sessions.",
        {"crash_guard": True},
    ),
    Option(
        "no-time-stop",
        "9",
        "No time stop (warn only)",
        "The positional 60-session time stop does not sell; the trailing and initial "
        "stops still do.",
        {"time_stop": False},
    ),
    Option(
        "quality",
        "13",
        "Quality filter",
        f"Enter only when fund-v1 is at least {QUALITY_MIN_FUND:g} where it is known "
        "(a stock with no filing yet passes). The review asked for operating cash flow, "
        "promoter pledge and dilution: quarterly results carry none of them, so fund-v1 "
        "(growth, margins, P/E against its own history, audit opinion) stands in.",
        {},
        filtered=True,
    ),
)
BY_KEY = {o.key: o for o in OPTIONS}


@dataclass
class Row:
    label: str
    item: str
    ev: Evaluation | None
    error: str | None = None


def run_research(
    market: Market,
    keys: list[str] | None = None,
    base: Strategy = RS_PULLBACK,
    rules: PortfolioRules | None = None,
    log: Log = lambda _: None,
) -> list[Row]:
    rules = rules or PortfolioRules()
    rows = [Row(f"{base.version} as it is", "-", evaluate(market, base, rules))]
    log(f"{base.version}: done")
    for key in keys or [o.key for o in OPTIONS]:
        option = BY_KEY[key]
        strategy = _quality_filtered(base) if option.filtered else base
        try:
            ev = evaluate(market, strategy, replace(rules, **option.rules))
        except ValueError as exc:
            rows.append(Row(option.label, option.item, None, str(exc)))
            log(f"{key}: not run, {exc}")
            continue
        rows.append(Row(option.label, option.item, ev))
        log(f"{key}: done")
    return rows


@dataclass(frozen=True)
class TrialView:
    """Item 7: the deflated Sharpe against all the variants tried, counting them as
    independent and as the effective number their correlation says they are worth."""

    trials: int
    effective: float
    mean_correlation: float
    dsr_counted: float  # trials as independent (the reports' "all variants" figure)
    dsr_effective: float


def trial_view(market: Market, base: Evaluation, rules: PortfolioRules | None = None) -> TrialView:
    """Every variant of the strategies counted before the combined book (60), trained
    over the whole pre-holdout period, against `base`'s out-of-sample daily returns."""
    rules = rules or PortfolioRules()
    costs = CostModel()
    folds = make_folds(market.days)
    returns, sharpes = [], []
    for key in COMBINED_BOOK.trial_keys:
        strategy = STRATEGIES[key]
        if missing_inputs(market, strategy):
            continue  # counted only when it can be run (the trial count says how many)
        r = replace(rules, results_blackout=True) if strategy.results_blackout else rules
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
            sharpes.append(per_period_sharpe(sim.equity, r.cash_rate_pct))
            returns.append(daily_returns(sim.equity))
    matrix = np.array(returns)
    live = matrix[np.std(matrix, axis=1) > 0]
    corr = np.corrcoef(live)
    mean_corr = float(corr[np.triu_indices(len(corr), 1)].mean()) if len(corr) > 1 else 1.0
    n_eff = effective_trials(matrix)
    sim = base.sim
    oos = sim.equity[: base.folds.holdout_start - sim.start]
    excess = daily_returns(oos) - daily_rate(rules.cash_rate_pct)
    return TrialView(
        len(sharpes),
        round(n_eff, 1),
        round(mean_corr, 2),
        round(deflated_sharpe(excess, sharpes), 2),
        round(deflated_sharpe(excess, sharpes, n_eff), 2),
    )


CAPACITY_SHARES = (0.1, 0.25, 0.5)


def capacity(ev: Evaluation, market: Market, max_volume_pct: float = 1.0) -> dict[float, float]:
    """Item 15: the capital at which this share of the test period's trades would have
    been cut by the 1%-of-average-volume cap. Each trade's position value scales with
    capital (its share of equity at entry stays the same); its cap is 1% of the stock's
    20-day average volume in rupees on the signal day."""
    m, sim = market, ev.sim
    limits = []
    for t in ev.oos_trades:
        equity = float(sim.equity[t.entry_day - sim.start])
        value = t.entry * t.shares
        liquidity = float(m.avg_volume20[t.s, t.signal_day]) * float(m.close[t.s, t.signal_day])
        if equity > 0 and value > 0 and liquidity > 0:
            # Capital at which value * capital / equity reaches max_volume_pct of liquidity.
            limits.append(liquidity * max_volume_pct / 100 / (value / equity))
    if not limits:
        return {}
    ordered = sorted(limits)
    return {q: ordered[max(0, int(q * len(ordered)) - 1)] for q in CAPACITY_SHARES}


def _f(value: Any, fmt: str) -> str:
    return "-" if value is None else format(value, fmt)


def _year(ev: Evaluation, year: str) -> str:
    stats = ev.summary["out_of_sample"]["by_year"].get(year)
    return "-" if stats is None else f"{stats['expectancy_r']:+.2f}R ({stats['trades']})"


def report(
    rows: list[Row],
    data_note: str,
    market: Market | None = None,
    trials: TrialView | None = None,
) -> str:
    """The comparison as Markdown."""
    lines = [
        "| | Item | Trades | Expectancy | Profit factor | Max DD | CAGR | Sharpe | 2022 | "
        "2024 | Holdout | Checks passed |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if r.ev is None:
            lines.append(f"| {r.label} | {r.item} | not run: {r.error} |||||||||| |")
            continue
        s = r.ev.summary
        t, c = s["out_of_sample"]["trades"], s["out_of_sample"]["curve"]
        h = s["holdout"]["trades"]
        passed = sum(g["passed"] for g in s["gates"])
        lines.append(
            f"| {r.label} | {r.item} | {t['trades']} | {t['expectancy_r']:+.3f}R | "
            f"{_f(t['profit_factor'], '.2f')} | {c['max_drawdown_pct']:.1f}% | "
            f"{c['cagr'] * 100:.1f}% | {c['sharpe']:.2f} | {_year(r.ev, '2022')} | "
            f"{_year(r.ev, '2024')} | {h['expectancy_r']:+.3f}R ({h['trades']}) | "
            f"{passed} of {len(s['gates'])} |"
        )
    base = rows[0].ev
    if base is not None:
        missed = base.summary["missed_entries"]
        exits = base.summary["exit_reasons"]
        lines += [
            "",
            f"Missed entries (item 10), test period, {rows[0].label}: "
            f"{missed['missed']} orders opened above the entry zone and were skipped; bought "
            f"at that open anyway they average {_f(missed['missed_avg_r'], '+.3f')}R "
            f"(win rate {_f(missed['missed_win_rate'], '.0%')}), against "
            f"{_f(missed['filled_avg_r'], '+.3f')}R for the {missed['filled']} trades "
            f"taken ({missed['basis']}).",
            f"Exit reasons, {rows[0].label}: "
            + ", ".join(f"{k} {v}" for k, v in exits.items())
            + ".",
        ]
        if market is not None:
            cap = capacity(base, market)
            if cap:
                lines.append(
                    "Capacity (item 15): the 1%-of-volume cap would have cut "
                    + ", ".join(
                        f"{q:.0%} of the trades from ₹{v / 1e7:,.1f} crore" for q, v in cap.items()
                    )
                    + " of capital."
                )
    if trials is not None:
        lines.append(
            f"Deflated Sharpe (item 7), {rows[0].label} against {trials.trials} variants: "
            f"{trials.dsr_counted} counting them as independent, {trials.dsr_effective} "
            f"counting them as the {trials.effective} independent trials their daily "
            f"returns are worth (mean correlation {trials.mean_correlation}); 0.95 is the bar."
        )
    lines += ["", data_note]
    return "\n".join(lines)
