"""Backtest vs paper vs my real results, per strategy (spec section 7). Pure.

Each strategy moves through four stages, each with a gate:
1. backtest: passes section 6 (else its signals are research only);
2. paper: at least 3 months and 30 closed trades, expectancy > 0, and inside the
   backtest's expected range;
3. small real money: my results match paper within reason, over at least 3 months;
4. full capital: only after stage 3 passes.

"Expected range": the 5th to 95th percentile of the average R of n trades drawn (with
replacement) from the reference trades, n being the number of trades compared. A short
paper record gets a wide range, a long one a narrow range.

When my real trades differ from paper, the likely causes are measured from the signals
both traded: entry slippage, late entries, different exits, and skipped signals.
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

PAPER_MIN_DAYS = 91  # 3 months
PAPER_MIN_TRADES = 30
REAL_MIN_DAYS = 91
RANGE_PCT = (5.0, 95.0)
SIMULATIONS = 2000
# Thresholds for naming a cause of divergence.
SLIPPAGE_R = 0.1
LATE_DAYS = 1.0
EXIT_GAP_R = 0.2


@dataclass(frozen=True)
class ClosedTrade:
    r: float
    pnl: float
    sessions: int
    closed: date


@dataclass(frozen=True)
class Record:
    """One column: a strategy's backtest, paper or real trades."""

    trades: int
    win_rate: float | None
    expectancy_r: float | None
    profit_factor: float | None
    avg_sessions: float | None
    max_drawdown: float | None
    drawdown_unit: str  # "%" (equity curve) or "R" (cumulative R of closed trades)
    start: date | None = None
    end: date | None = None


@dataclass(frozen=True)
class Gate:
    name: str
    status: str  # "passed" / "failed" / "not yet"
    detail: str


@dataclass(frozen=True)
class Pair:
    """One signal that both the paper account and I traded."""

    signal_date: date
    ticker: str
    paper_entry: float
    paper_stop: float
    paper_entry_date: date
    paper_r: float | None  # None while open
    my_entry: float
    my_entry_date: date
    my_r: float | None


@dataclass(frozen=True)
class Divergence:
    pairs: int
    slippage_r: float | None  # my average entry above paper's, in paper R
    late_days: float | None  # calendar days between paper's entry and my first buy
    exit_gap_r: float | None  # my R minus paper's, on signals both closed
    skipped: int  # signals I skipped whose paper trade closed
    skipped_r: float  # those paper trades' total R
    skipped_winners: int
    causes: list[str] = field(default_factory=list)


def record(
    trades: Sequence[ClosedTrade], start: date | None = None, end: date | None = None
) -> Record:
    """Stats of closed trades; drawdown in R of the cumulative closed-trade R."""
    n = len(trades)
    if n == 0:
        return Record(0, None, None, None, None, None, "R", start, end)
    rs = [t.r for t in sorted(trades, key=lambda t: t.closed)]
    gains = sum(t.pnl for t in trades if t.pnl > 0)
    losses = -sum(t.pnl for t in trades if t.pnl < 0)
    peak = total = worst = 0.0
    for r in rs:
        total += r
        peak = max(peak, total)
        worst = max(worst, peak - total)
    return Record(
        trades=n,
        win_rate=sum(t.pnl > 0 for t in trades) / n,
        expectancy_r=sum(rs) / n,
        profit_factor=gains / losses if losses else None,
        avg_sessions=sum(t.sessions for t in trades) / n,
        max_drawdown=worst,
        drawdown_unit="R",
        start=start,
        end=end,
    )


def expected_range(
    reference: Sequence[float], n: int, seed: int = 7, simulations: int = SIMULATIONS
) -> tuple[float, float] | None:
    """The range the average R of n trades should fall in, if they behave like the
    reference trades."""
    if not reference or n <= 0:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(reference, k=n)) / n for _ in range(simulations))
    lo = means[int(len(means) * RANGE_PCT[0] / 100)]
    hi = means[min(int(len(means) * RANGE_PCT[1] / 100), len(means) - 1)]
    return lo, hi


def _within(value: float, band: tuple[float, float] | None) -> bool:
    return band is not None and band[0] <= value <= band[1]


def _range_text(band: tuple[float, float] | None) -> str:
    return "no reference trades" if band is None else f"{band[0]:+.2f}R to {band[1]:+.2f}R"


def paper_gate(
    paper: Record, days: int, backtest_rs: Sequence[float]
) -> tuple[Gate, tuple[float, float] | None]:
    band = expected_range(backtest_rs, paper.trades)
    missing = []
    if days < PAPER_MIN_DAYS:
        missing.append(f"{days} of {PAPER_MIN_DAYS} days")
    if paper.trades < PAPER_MIN_TRADES:
        missing.append(f"{paper.trades} of {PAPER_MIN_TRADES} closed trades")
    exp = paper.expectancy_r
    if missing:
        detail = "Needs " + " and ".join(missing)
        if exp is not None:
            detail += (
                f"; so far {exp:+.2f}R (backtest range for {paper.trades}: {_range_text(band)})"
            )
        return Gate("paper", "not yet", detail), band
    assert exp is not None
    if exp <= 0:
        return Gate("paper", "failed", f"Expectancy {exp:+.2f}R is not above 0 after costs"), band
    if not _within(exp, band):
        return (
            Gate("paper", "failed", f"Expectancy {exp:+.2f}R is outside the backtest's range "
                 f"({_range_text(band)})"),
            band,
        )  # fmt: skip
    return Gate("paper", "passed", f"{exp:+.2f}R over {paper.trades} trades, inside "
                f"{_range_text(band)}"), band  # fmt: skip


def real_gate(
    real: Record, days: int, paper_rs: Sequence[float]
) -> tuple[Gate, tuple[float, float] | None]:
    band = expected_range(paper_rs, real.trades)
    exp = real.expectancy_r
    if real.trades == 0 or exp is None:
        return Gate("small real", "not yet", "No closed real trades yet"), band
    if days < REAL_MIN_DAYS:
        return (
            Gate("small real", "not yet", f"{days} of {REAL_MIN_DAYS} days; so far {exp:+.2f}R "
                 f"(paper range for {real.trades}: {_range_text(band)})"),
            band,
        )  # fmt: skip
    if exp <= 0 or not _within(exp, band):
        return (
            Gate("small real", "failed", f"My {exp:+.2f}R doesn't match paper "
                 f"({_range_text(band)}) or isn't above 0"),
            band,
        )  # fmt: skip
    return Gate("small real", "passed", f"My {exp:+.2f}R matches paper ({_range_text(band)})"), band


def stage(live_eligible: bool, paper: Gate | None, real: Gate | None) -> str:
    if not live_eligible:
        return "research only"
    if paper is None or paper.status != "passed":
        return "paper"
    if real is None or real.status != "passed":
        return "small real"
    return "full capital"


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def divergence(pairs: Sequence[Pair], skipped_paper_rs: Sequence[float]) -> Divergence:
    slips = [
        (p.my_entry - p.paper_entry) / (p.paper_entry - p.paper_stop)
        for p in pairs
        if p.paper_entry > p.paper_stop
    ]
    late = [float((p.my_entry_date - p.paper_entry_date).days) for p in pairs]
    gaps = [p.my_r - p.paper_r for p in pairs if p.my_r is not None and p.paper_r is not None]
    d = Divergence(
        pairs=len(pairs),
        slippage_r=_mean(slips),
        late_days=_mean(late),
        exit_gap_r=_mean(gaps),
        skipped=len(skipped_paper_rs),
        skipped_r=sum(skipped_paper_rs),
        skipped_winners=sum(r > 0 for r in skipped_paper_rs),
    )
    if d.slippage_r is not None and d.slippage_r > SLIPPAGE_R:
        d.causes.append(f"Slippage: my entries average {d.slippage_r:+.2f}R above the paper fills.")
    if d.late_days is not None and d.late_days > LATE_DAYS:
        d.causes.append(f"Late entries: {d.late_days:.1f} days after paper on average.")
    if d.exit_gap_r is not None and d.exit_gap_r < -EXIT_GAP_R:
        d.causes.append(
            f"Exits: {d.exit_gap_r:+.2f}R per trade against paper on the same signals "
            "(early exits or moved stops)."
        )
    if d.skipped_winners:
        d.causes.append(
            f"Skipped signals: {d.skipped} skipped, {d.skipped_winners} of them paper winners, "
            f"{d.skipped_r:+.2f}R in total."
        )
    return d
