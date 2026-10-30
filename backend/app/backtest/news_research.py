"""Does the news brain help? (docs/plans/news-brain-v1.md). `python -m app.cli
news-research` runs each strategy with and without M6's news filter and results
blackout and writes the comparison as Markdown.

Research only, like `research.py`: the arms are the strategy with the two M6 rules
switched on or off, the runs are not saved as backtest runs, and the arms and the
decision rule were fixed in the plan before any run. Each arm is the full walk-forward
(grid point picked on training data with the arm's rules, out-of-sample, after costs,
the latest 12 months held out).

Two more readings, from the run with neither rule:
- its trades grouped by the news score on the signal day, which says whether recent
  bad (or good) news went with worse (or better) trades, apart from how the filter
  changes the rest of the portfolio;
- every arm's trades before and after the labelling model's training cut-off. An LLM
  labelling 2019's announcements may remember what the price did next; a filter that
  only helps before the cut-off is hindsight, not an edge.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date

from app.backtest.engine import PortfolioRules, Trade
from app.backtest.market import Market
from app.backtest.stats import trade_stats
from app.backtest.strategies import (
    MIN_NEWS_SCORE,
    RESULTS_DRIFT,
    RS_PULLBACK,
    STRATEGIES,
    Strategy,
)
from app.backtest.walkforward import Evaluation, evaluate

Log = Callable[[str], None]

# The strategies the plan tests: the live-eligible one and the strongest research one.
DEFAULT_KEYS = (RS_PULLBACK.key, RESULTS_DRIFT.key)
# Above this the score means recent good news (50 = none; one +1 results label is 62.5).
GOOD_NEWS_SCORE = 60.0


@dataclass(frozen=True)
class Arm:
    key: str
    label: str
    news: bool
    blackout: bool


ARMS = (
    Arm("none", "Neither rule", news=False, blackout=False),
    Arm("news", "News filter", news=True, blackout=False),
    Arm("blackout", "Results blackout", news=False, blackout=True),
    Arm("both", "Both", news=True, blackout=True),
)


def arm_strategy(base: Strategy, arm: Arm) -> Strategy:
    """`base` with exactly the arm's M6 rules, whatever the registered version has."""
    return replace(
        base,
        version=f"{base.version}/{arm.key}",
        results_blackout=arm.blackout,
        min_news_score=MIN_NEWS_SCORE if arm.news else None,
    )


def missing(market: Market, arm: Arm) -> str | None:
    """Why the arm can't be run. The engine and `Strategy.entries` skip a rule whose
    input isn't loaded, which here would pass the base run off as the arm."""
    if arm.news and market.news_score is None:
        return "no news labels from the labeller in .env (run news-label)"
    if arm.blackout and market.results_blackout is None:
        return "no results calendar (run the events job)"
    return None


@dataclass
class Row:
    strategy: str
    arm: Arm
    ev: Evaluation | None
    error: str | None = None

    @property
    def trades(self) -> list[Trade]:
        return [] if self.ev is None else [*self.ev.oos_trades, *self.ev.holdout_trades]


def run(
    market: Market,
    keys: Sequence[str] = DEFAULT_KEYS,
    rules: PortfolioRules | None = None,
    log: Log = lambda _: None,
) -> list[Row]:
    rows = []
    for key in keys:
        base = STRATEGIES[key]
        for arm in ARMS:
            why = missing(market, arm)
            if why is None:
                try:
                    ev = evaluate(market, arm_strategy(base, arm), rules, robust=False)
                except ValueError as exc:
                    why = str(exc)
            if why is not None:
                rows.append(Row(base.version, arm, None, why))
                log(f"{base.version} {arm.key}: not run, {why}")
                continue
            rows.append(Row(base.version, arm, ev))
            log(f"{base.version} {arm.key}: done")
    return rows


@dataclass(frozen=True)
class Bucket:
    label: str
    trades: int
    expectancy_r: float
    win_rate: float


def by_news_score(market: Market, trades: Sequence[Trade]) -> list[Bucket]:
    """Trades grouped by the stock's news score at the signal-day close."""
    if market.news_score is None:
        return []
    groups: dict[str, list[Trade]] = {
        f"bad news (below {MIN_NEWS_SCORE:g})": [],
        "no news or mixed": [],
        f"good news (above {GOOD_NEWS_SCORE:g})": [],
    }
    labels = list(groups)
    for t in trades:
        score = float(market.news_score[t.s, t.signal_day])
        k = 0 if score < MIN_NEWS_SCORE else 2 if score > GOOD_NEWS_SCORE else 1
        groups[labels[k]].append(t)
    return [_stats(label, group) for label, group in groups.items()]


def split_at(market: Market, trades: Sequence[Trade], cutoff: date) -> tuple[Bucket, Bucket]:
    """Trades signalled before `cutoff`, and on or after it."""
    before = [t for t in trades if market.days[t.signal_day] < cutoff]
    after = [t for t in trades if market.days[t.signal_day] >= cutoff]
    return _stats("before", before), _stats("after", after)


def _stats(label: str, trades: Sequence[Trade]) -> Bucket:
    s = trade_stats(trades)
    return Bucket(label, s.trades, s.expectancy_r, s.win_rate)


def _f(value: float | None, fmt: str) -> str:
    return "-" if value is None else format(value, fmt)


def _bucket(b: Bucket) -> str:
    return "-" if b.trades == 0 else f"{b.expectancy_r:+.3f}R ({b.trades})"


def report(rows: list[Row], market: Market, data_note: str, cutoff: date | None = None) -> str:
    """The comparison as Markdown."""
    head = (
        "| Strategy | Rules | Trades | Expectancy | Profit factor | Max DD | CAGR | Sharpe | "
        "Holdout | Checks passed |"
    )
    lines = [head, "|---|---|---|---|---|---|---|---|---|---|"]
    if cutoff is not None:
        lines[0] += f" Before {cutoff} | From {cutoff} |"
        lines[1] += "---|---|"
    for r in rows:
        if r.ev is None:
            lines.append(f"| {r.strategy} | {r.arm.label} | not run: {r.error} |")
            continue
        s = r.ev.summary
        t, c = s["out_of_sample"]["trades"], s["out_of_sample"]["curve"]
        h = s["holdout"]["trades"]
        passed = sum(g["passed"] for g in s["gates"])
        line = (
            f"| {r.strategy} | {r.arm.label} | {t['trades']} | {t['expectancy_r']:+.3f}R | "
            f"{_f(t['profit_factor'], '.2f')} | {c['max_drawdown_pct']:.1f}% | "
            f"{c['cagr'] * 100:.1f}% | {c['sharpe']:.2f} | "
            f"{h['expectancy_r']:+.3f}R ({h['trades']}) | {passed} of {len(s['gates'])} |"
        )
        if cutoff is not None:
            before, after = split_at(market, r.trades, cutoff)
            line += f" {_bucket(before)} | {_bucket(after)} |"
        lines.append(line)

    bases = [r for r in rows if r.arm.key == "none" and r.ev is not None]
    if market.news_score is not None and bases:
        lines += [
            "",
            "Trades of the run with neither rule (test period and holdout), by the news score "
            "on the signal day:",
            "",
            "| Strategy | " + " | ".join(b.label for b in by_news_score(market, [])) + " |",
            "|---|---|---|---|",
        ]
        for r in bases:
            cells = [
                f"{_bucket(b)}, {b.win_rate:.0%} won" if b.trades else "-"
                for b in by_news_score(market, r.trades)
            ]
            lines.append(f"| {r.strategy} | " + " | ".join(cells) + " |")
    lines += ["", data_note]
    return "\n".join(lines)
