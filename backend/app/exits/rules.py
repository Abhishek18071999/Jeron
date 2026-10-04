"""The exit rules of spec section 5 for a real position: what the engine would do with
it, day by day since the first buy, and what that means for tomorrow's open.

The rules are the engine's, with its constants (`PortfolioRules`, `TIERS`):
- a stop hit during the day (or an open below it) ends the trade;
- half is booked at T1, +2R from the average entry; the stop moves to breakeven;
- once a close is +1R, the stop moves to breakeven;
- after T1 the rest trails at 2 x ATR(14) below the highest close, closing basis: a
  close below the trail sells at the next open;
- the tier's time stop sells at the next open if +1R hasn't been reached in time.

Prices are split/bonus-adjusted to today's basis, so today's numbers are raw rupees.
Pure: no database.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from app.alerts.format import inr
from app.backtest.engine import PortfolioRules
from app.backtest.strategies import TIERS, Tier

RULES = PortfolioRules()


class Action(StrEnum):
    HOLD = "hold"
    SELL_HALF = "sell half"
    SELL_ALL = "sell all"


@dataclass(frozen=True)
class ExitBar:
    day: date
    open: float
    high: float
    low: float
    close: float
    atr14: float  # NaN until there is enough history


@dataclass(frozen=True)
class ExitPlan:
    as_of: date
    entry: float
    initial_stop: float
    stop: float  # today's stop (intraday)
    t1: float
    one_r: float  # the close that counts as +1R
    t1_hit: date | None
    reached_1r: bool
    trail: float | None  # after T1: a close below this sells at the next open
    sessions: int  # sessions held after the entry day
    time_stop_sessions: int
    action: Action
    reason: str
    # The day the rules said to exit (stop hit, trail, time stop), if any.
    exit_day: date | None = None
    notes: list[str] = field(default_factory=list)


def _rs(price: float) -> str:
    return inr(round(price, 2))


def exit_plan(
    entry: float,
    stop: float,
    tier: Tier,
    bars: Sequence[ExitBar],
    half_booked: bool,
    rules: PortfolioRules = RULES,
) -> ExitPlan:
    """The plan after the last bar. `bars` run from the entry day (the first buy) to
    the latest close; `entry` is the average buy price and `stop` the initial stop, on
    the same basis as the bars. `half_booked`: I already sold at least half."""
    if not bars:
        raise ValueError("No bars since the entry")
    if stop >= entry:
        raise ValueError(f"Stop {stop} is not below the entry {entry}")
    tier_rules = TIERS[tier]
    r = entry - stop
    t1 = entry + rules.t1_r * r
    one_r = entry + rules.breakeven_r * r
    current, trail = stop, math.nan
    t1_hit: date | None = None
    reached = False
    sessions = 0
    exit_day: date | None = None
    reason = ""
    for i, b in enumerate(bars):
        hit = None
        if i > 0 and b.open <= current:
            hit = b.open
        elif b.low <= current:
            hit = current
        if hit is not None:
            kind = "stop" if current < entry else "breakeven stop"
            reason = f"{kind} {_rs(current)} hit on {b.day:%d %b} (low {_rs(b.low)})"
            exit_day = b.day
            break
        if t1_hit is None and b.high >= t1:
            t1_hit = b.day
            current = max(current, entry)
        if b.close >= one_r:
            reached = True
            current = max(current, entry)
        if t1_hit is not None:
            if not math.isnan(trail) and b.close < trail:
                reason = (
                    f"close {_rs(b.close)} on {b.day:%d %b} below the trail {_rs(trail)} "
                    f"({rules.trail_atr:g} x ATR, closing basis)"
                )
                exit_day = b.day
                break
            if not math.isnan(b.atr14):
                trail = max(
                    trail if not math.isnan(trail) else -math.inf,
                    b.close - rules.trail_atr * b.atr14,
                )
        if i > 0:
            sessions += 1
        if not reached and sessions >= tier_rules.time_stop_sessions:
            reason = (
                f"time stop: {sessions} sessions without a close at +1R ({_rs(one_r)}); "
                f"{tier_rules.time_stop_label}"
            )
            exit_day = b.day
            break

    last = bars[-1]
    notes: list[str] = []
    if exit_day is not None:
        action = Action.SELL_ALL
        if exit_day != last.day:
            reason += f"; still held at {last.day:%d %b}"
    elif t1_hit is not None and not half_booked:
        action = Action.SELL_HALF
        reason = f"T1 {_rs(t1)} (+{rules.t1_r:g}R) reached on {t1_hit:%d %b}: book half"
    else:
        action = Action.HOLD
        reason = f"stop {_rs(current)}"
        if not math.isnan(trail):
            reason += f"; sell at the next open after a close below {_rs(trail)}"
        elif t1_hit is None:
            reason += f"; T1 {_rs(t1)}"
    if exit_day is None and not reached:
        left = tier_rules.time_stop_sessions - sessions
        notes.append(
            f"Time stop: {sessions} of {tier_rules.time_stop_sessions} sessions; needs a close "
            f"at or above {_rs(one_r)} within {left} more"
        )
    if half_booked and t1_hit is None:
        notes.append("Half already sold before T1")
    return ExitPlan(
        as_of=last.day,
        entry=entry,
        initial_stop=stop,
        stop=current,
        t1=t1,
        one_r=one_r,
        t1_hit=t1_hit,
        reached_1r=reached,
        trail=None if math.isnan(trail) else trail,
        sessions=sessions,
        time_stop_sessions=tier_rules.time_stop_sessions,
        action=action,
        reason=reason,
        exit_day=exit_day,
        notes=notes,
    )
