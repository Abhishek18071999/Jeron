"""Journal maths (spec section 8): a position from my fills, and stats per strategy.
Pure functions; prices are raw rupees per share."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

ZERO = Decimal(0)
DECISIONS = ("taken", "skipped", "modified")


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
