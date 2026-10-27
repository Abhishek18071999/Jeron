"""Is a paper strategy still behaving like its backtest? The degradation monitor
(docs/plans/confidence-v1.md, the 2026-10 review's item 4). Pure.

A few losing trades are not evidence that an edge broke, and a few winners are not
evidence that it works. So paper results are placed in the distribution the backtest
gives for that many trades (trades drawn with replacement from the out-of-sample
trades), and read as a percentile:

- fewer than `MIN_TRADES` closed trades: too early to say anything;
- at or above the 20th percentile: on track;
- 5th to 20th: ordinary variance, the kind of stretch the backtest itself has;
- below the 5th with fewer than `DETERIORATING_TRADES`: watch (the 20-trade early
  warning's territory);
- below the 5th with `DETERIORATING_TRADES` or more: deteriorating, unlikely to be
  bad luck alone.

Beside it: signal frequency against the backtest's rate (a strategy that suddenly
trades much more or less is behaving differently, whatever its P&L), the average loss
against the backtest's (gaps through stops, bigger losses), and sector concentration.

Nothing here changes what a strategy does: the weekly revalidation still retires by
spec section 6's rules. `false_retirement` measures how often that 50-trade rule would
retire a strategy that is exactly as good as its backtest.
"""

import math
import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

MIN_TRADES = 10
DETERIORATING_TRADES = 30
ON_TRACK_PCT = 20.0
WARN_PCT = 5.0
SIMULATIONS = 2000
SEED = 11
# Signal frequency outside this range of the backtest's (as a ratio) is flagged, once
# the paper account has run for `MIN_FREQUENCY_SESSIONS`.
FREQUENCY_BAND = (0.5, 2.0)
MIN_FREQUENCY_SESSIONS = 40
# Losses bigger than the backtest's average loss by this much (in R) are flagged.
LOSS_GAP_R = 0.3
SECTOR_SHARE = 0.4  # of the paper trades in one sector
# The revalidation's rolling rule (app/analytics/weekly.py), checked here.
ROLLING_TRADES = 50
HORIZON_TRADES = 200


def percentile_of_mean(
    observed: float, n: int, reference: Sequence[float], simulations: int = SIMULATIONS
) -> float | None:
    """Where the average of `n` trades sits among averages of `n` trades drawn from
    `reference`: the share of draws below `observed` (ties count half), in percent."""
    if not reference or n <= 0:
        return None
    rng = random.Random(SEED)
    below = 0.0
    for _ in range(simulations):
        mean = sum(rng.choices(reference, k=n)) / n
        below += 1.0 if mean < observed - 1e-12 else 0.5 if abs(mean - observed) <= 1e-12 else 0.0
    return below / simulations * 100


def false_retirement(
    reference: Sequence[float],
    rolling: int = ROLLING_TRADES,
    horizon: int = HORIZON_TRADES,
    simulations: int = 1000,
) -> float | None:
    """Share of `horizon`-trade paths drawn from `reference` in which some rolling
    `rolling`-trade average falls below 0: how often the revalidation rule would retire
    a strategy whose true edge is the backtest's."""
    if len(reference) < 2 or horizon < rolling:
        return None
    rng = random.Random(SEED)
    retired = 0
    for _ in range(simulations):
        path = rng.choices(reference, k=horizon)
        window = sum(path[:rolling])
        hit = window < 0
        k = rolling
        while not hit and k < horizon:
            window += path[k] - path[k - rolling]
            hit = window < 0
            k += 1
        retired += hit
    return retired / simulations


@dataclass(frozen=True)
class Flag:
    key: str
    text: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class Health:
    verdict: str  # too early / on track / ordinary variance / watch / deteriorating
    detail: str
    trades: int
    expectancy_r: float | None
    percentile: float | None
    backtest_expectancy_r: float | None
    flags: list[Flag] = field(default_factory=list)
    false_retirement: float | None = None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["flags"] = [f.to_dict() for f in self.flags]
        for k in ("expectancy_r", "percentile", "backtest_expectancy_r", "false_retirement"):
            if out[k] is not None:
                out[k] = round(out[k], 3)
        return out


def _verdict(n: int, pct: float | None) -> str:
    if n < MIN_TRADES or pct is None:
        return "too early"
    if pct >= ON_TRACK_PCT:
        return "on track"
    if pct >= WARN_PCT:
        return "ordinary variance"
    return "deteriorating" if n >= DETERIORATING_TRADES else "watch"


def assess(
    paper_rs: Sequence[float],
    backtest_rs: Sequence[float],
    *,
    paper_entries: int,
    paper_sessions: int,
    backtest_trades_per_session: float | None,
    paper_sectors: Sequence[str | None] = (),
) -> Health:
    """`paper_rs` are closed paper trades' R; `paper_entries` the trades opened (closed
    or not) over `paper_sessions` sessions."""
    n = len(paper_rs)
    mean = sum(paper_rs) / n if n else None
    bt_mean = sum(backtest_rs) / len(backtest_rs) if backtest_rs else None
    pct = percentile_of_mean(mean, n, backtest_rs) if mean is not None else None
    verdict = _verdict(n, pct)
    if verdict == "too early":
        detail = f"{n} closed paper trade{'s' if n != 1 else ''}: {MIN_TRADES} needed to compare."
    else:
        assert mean is not None and pct is not None
        detail = (
            f"{n} paper trades average {mean:+.2f}R: the {pct:.0f}th percentile of what "
            f"{n} backtest trades give"
            + (f" (backtest average {bt_mean:+.2f}R)." if bt_mean is not None else ".")
        )
        if verdict == "ordinary variance":
            detail += " A stretch like this happens in the backtest too; no change needed."
        elif verdict == "watch":
            detail += " Unusually weak, but too few trades to call it a broken edge."
        elif verdict == "deteriorating":
            detail += " Unlikely to be bad luck alone: re-check the strategy before more money."
    flags: list[Flag] = []
    if bt_mean is not None and bt_mean <= 0:
        flags.append(
            Flag(
                "backtest",
                f"The backtest itself averages {bt_mean:+.2f}R a trade: matching it is no edge.",
            )
        )
    if backtest_trades_per_session and paper_sessions >= MIN_FREQUENCY_SESSIONS:
        expected = backtest_trades_per_session * paper_sessions
        ratio = paper_entries / expected if expected > 0 else math.nan
        lo, hi = FREQUENCY_BAND
        if not math.isnan(ratio) and not lo <= ratio <= hi:
            flags.append(
                Flag(
                    "frequency",
                    f"{paper_entries} entries in {paper_sessions} sessions against about "
                    f"{expected:.0f} expected from the backtest: the strategy is trading "
                    f"{'less' if ratio < lo else 'more'} often than it did.",
                )
            )
    losses = [r for r in paper_rs if r <= 0]
    bt_losses = [r for r in backtest_rs if r <= 0]
    if len(losses) >= MIN_TRADES // 2 and bt_losses:
        avg, bt_avg = sum(losses) / len(losses), sum(bt_losses) / len(bt_losses)
        if avg < bt_avg - LOSS_GAP_R:
            flags.append(
                Flag(
                    "losses",
                    f"Average loss {avg:+.2f}R against {bt_avg:+.2f}R in the backtest: "
                    "stops are filling worse (gaps, circuits) than assumed.",
                )
            )
    known = [s for s in paper_sectors if s]
    if len(known) >= MIN_TRADES:
        sector, count = Counter(known).most_common(1)[0]
        if count / len(known) > SECTOR_SHARE:
            flags.append(
                Flag(
                    "sector",
                    f"{count} of {len(known)} paper trades in {sector}: the results lean on "
                    "one sector.",
                )
            )
    return Health(
        verdict,
        detail,
        n,
        mean,
        pct,
        bt_mean,
        flags,
        false_retirement(backtest_rs),
    )
