"""Journal maths (spec section 8): a position from my fills, and stats per strategy.
Pure functions; prices are raw rupees per share.

A few trades say little: each strategy's average R comes with a 95% range (Student's t
on the closed trades' R), and fewer than `MIN_SAMPLE` closed trades (the paper gate's
30) gets a note saying so. The range assumes trades are independent draws, which
overlapping trades in one market are not quite, so read it as the least uncertainty
there is."""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

ZERO = Decimal(0)
DECISIONS = ("taken", "skipped", "modified")
MIN_SAMPLE = 30
# Two-sided 95% critical values of Student's t by degrees of freedom.
T95 = (
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
    2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
    2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
)  # fmt: skip
Z95 = 1.959964


def t95(df: int) -> float:
    """From the table to 30 degrees of freedom, then the first Cornish-Fisher term
    (within 0.003 of the exact value from 31 on)."""
    if df < 1:
        raise ValueError("need at least one degree of freedom")
    if df <= len(T95):
        return T95[df - 1]
    return Z95 + (Z95**3 + Z95) / (4 * df)


def mean_interval(values: Sequence[Decimal]) -> tuple[Decimal, Decimal] | None:
    """The 95% range of the mean; None for fewer than two values."""
    n = len(values)
    if n < 2:
        return None
    xs = [float(v) for v in values]
    mean = sum(xs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1))
    half = t95(n - 1) * sd / math.sqrt(n)
    return _q(Decimal(str(mean - half))), _q(Decimal(str(mean + half)))


def sample_note(n: int, interval: tuple[Decimal, Decimal] | None) -> str | None:
    """What the sample can't tell yet, in plain words."""
    if n == 0:
        return None
    span = ""
    if interval is not None:
        span = f"; the average R could be anywhere from {interval[0]:.2f}R to {interval[1]:.2f}R"
    if n < MIN_SAMPLE:
        return (
            f"{n} closed trade{'s' if n > 1 else ''}: too few to judge "
            f"(Jeron's gates want {MIN_SAMPLE}){span}."
        )
    if interval is not None and interval[0] <= 0 <= interval[1]:
        return f"{n} closed trades and the range still includes 0R{span}."
    return None


@dataclass(frozen=True)
class Fill:
    trade_date: date
    side: str  # "buy" / "sell"
    shares: int
    price: Decimal
    charges: Decimal = ZERO


@dataclass(frozen=True)
class Position:
    status: str  # "no fills" / "open" / "closed"
    bought: int
    sold: int
    held: int
    avg_entry: Decimal | None
    avg_exit: Decimal | None
    first_date: date | None
    last_date: date | None
    charges: Decimal
    # After all charges; open P&L is the held shares marked at `last_close`.
    realised_pnl: Decimal
    open_pnl: Decimal | None
    # Risk at entry: (average entry - stop) x shares bought. None without a stop.
    initial_risk: Decimal | None
    r_multiple: Decimal | None


def position(fills: Iterable[Fill], stop: Decimal | None, last_close: Decimal | None) -> Position:
    """A long position from its fills, in date order. Sells are matched against the
    average entry price."""
    ordered = sorted(fills, key=lambda f: f.trade_date)
    buys = [f for f in ordered if f.side == "buy"]
    sells = [f for f in ordered if f.side == "sell"]
    bought = sum(f.shares for f in buys)
    sold = sum(f.shares for f in sells)
    charges = sum((f.charges for f in ordered), ZERO)
    if sold > bought:
        raise ValueError(f"Sold {sold} shares but bought only {bought}")
    if bought == 0:
        return Position(
            "no fills", 0, sold, 0, None, None, None, None, charges, -charges, None, None, None
        )
    cost = sum((f.price * f.shares for f in buys), ZERO)
    avg_entry = cost / bought
    proceeds = sum((f.price * f.shares for f in sells), ZERO)
    avg_exit = proceeds / sold if sold else None
    held = bought - sold
    realised = proceeds - avg_entry * sold - charges
    open_pnl = (last_close - avg_entry) * held if held and last_close is not None else None
    if held == 0:
        open_pnl = ZERO
    initial_risk = (avg_entry - stop) * bought if stop is not None and stop < avg_entry else None
    total = realised + (open_pnl or ZERO)
    r = total / initial_risk if initial_risk else None
    return Position(
        "open" if held else "closed",
        bought,
        sold,
        held,
        _q(avg_entry),
        None if avg_exit is None else _q(avg_exit),
        ordered[0].trade_date,
        ordered[-1].trade_date,
        charges,
        _q(realised, "0.01"),
        None if open_pnl is None else _q(open_pnl, "0.01"),
        None if initial_risk is None else _q(initial_risk, "0.01"),
        None if r is None else _q(r),
    )


def _q(value: Decimal, places: str = "0.0001") -> Decimal:
    return value.quantize(Decimal(places))


@dataclass(frozen=True)
class JournalRow:
    """What the stats need from one entry (or a pending signal: decision None)."""

    strategy_key: str | None
    decision: str | None
    followed_plan: bool | None
    status: str | None  # the position's status
    r_multiple: Decimal | None
    pnl: Decimal | None
    holding_days: int | None
    has_signal: bool = True


@dataclass
class StrategyStats:
    strategy_key: str | None
    signals: int = 0
    pending: int = 0
    taken: int = 0
    skipped: int = 0
    modified: int = 0
    open: int = 0
    closed: int = 0
    wins: int = 0
    win_rate: Decimal | None = None
    avg_r: Decimal | None = None
    profit_factor: Decimal | None = None
    net_pnl: Decimal = ZERO
    avg_holding_days: Decimal | None = None
    # Average R of closed trades where I followed the plan / deviated.
    followed_avg_r: Decimal | None = None
    deviated_avg_r: Decimal | None = None
    followed: int = 0
    deviated: int = 0
    # The 95% range of avg_r, and what the sample can't tell yet (module notes).
    avg_r_low: Decimal | None = None
    avg_r_high: Decimal | None = None
    sample_note: str | None = None


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    return _q(sum(values, ZERO) / len(values)) if values else None


def strategy_stats(rows: Iterable[JournalRow]) -> list[StrategyStats]:
    """Per strategy (None: trades without a signal). Expectancy is the average R of
    closed trades that have a stop."""
    by_key: dict[str | None, StrategyStats] = {}
    groups: dict[str | None, list[JournalRow]] = {}
    for row in rows:
        groups.setdefault(row.strategy_key, []).append(row)
    for key, group in groups.items():
        s = StrategyStats(key)
        closed = [r for r in group if r.status == "closed"]
        rs = [r.r_multiple for r in closed if r.r_multiple is not None]
        s.signals = sum(r.has_signal for r in group)
        s.pending = sum(r.decision is None for r in group)
        s.taken = sum(r.decision == "taken" for r in group)
        s.skipped = sum(r.decision == "skipped" for r in group)
        s.modified = sum(r.decision == "modified" for r in group)
        s.open = sum(r.status == "open" for r in group)
        s.closed = len(closed)
        pnls = [r.pnl for r in closed if r.pnl is not None]
        s.wins = sum(p > 0 for p in pnls)
        s.win_rate = _q(Decimal(s.wins) / len(pnls)) if pnls else None
        s.avg_r = _mean(rs)
        interval = mean_interval(rs)
        if interval is not None:
            s.avg_r_low, s.avg_r_high = interval
        s.sample_note = sample_note(len(rs), interval)
        gains = sum((p for p in pnls if p > 0), ZERO)
        losses = -sum((p for p in pnls if p < 0), ZERO)
        s.profit_factor = _q(gains / losses) if losses else None
        s.net_pnl = sum(pnls, ZERO)
        days = [Decimal(r.holding_days) for r in closed if r.holding_days is not None]
        s.avg_holding_days = _mean(days)
        followed = [r.r_multiple for r in closed if r.followed_plan and r.r_multiple is not None]
        deviated = [
            r.r_multiple for r in closed if r.followed_plan is False and r.r_multiple is not None
        ]
        s.followed, s.deviated = len(followed), len(deviated)
        s.followed_avg_r, s.deviated_avg_r = _mean(followed), _mean(deviated)
        by_key[key] = s
    return sorted(by_key.values(), key=lambda s: (s.strategy_key is None, s.strategy_key or ""))
