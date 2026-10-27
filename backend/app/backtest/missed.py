"""What discipline at the open costs (the 2026-10 trading review, item 10): every
order the engine skipped because the stock opened above the entry zone, bought at that
open anyway, with the same stop and the engine's exit rules on that one position.

Reporting only: nothing here changes a trade. Both sides are measured the same way,
after slippage and before charges, in R of the price actually paid, so the missed
entries and the filled trades can be compared directly. If missed entries average
strongly positive, the entry zone (close + 0.5 x ATR) is costing edge; if they average
about the same as the filled trades or less, skipping gaps costs nothing.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from app.backtest.costs import CostModel
from app.backtest.engine import PortfolioRules, Skip, Trade
from app.backtest.market import Market
from app.backtest.strategies import TIERS, Tier

ABOVE_ZONE = "opened above the entry zone"


def missed_r(
    m: Market, tier: Tier, rules: PortfolioRules, costs: CostModel, skip: Skip, end: int
) -> float | None:
    """R of buying the skipped order at that day's open and following the exit rules
    to `end`, where whatever is left is marked at the close. None without a stop or a
    price."""
    tier_rules = TIERS[tier]
    rules = tier_rules.apply(rules)
    s, t0 = skip.s, skip.day
    if math.isnan(skip.stop) or t0 > end:
        return None
    slip = costs.slippage_pct(float(np.nan_to_num(m.median_turnover[s, t0])))
    entry = float(m.open[s, t0]) * (1 + slip / 100)
    risk = entry - skip.stop
    if not risk > 0:
        return None
    stop, trail = skip.stop, math.nan
    t1 = entry + rules.t1_r * risk
    remaining, pnl = 1.0, 0.0
    t1_done = reached = False
    sessions = 0
    pending = False

    def sell(price: float, part: float) -> None:
        nonlocal remaining, pnl
        pnl += (price * (1 - slip / 100) - entry) * part
        remaining -= part

    last = entry
    for t in range(t0, end + 1):
        o, h, lo, c = m.open[s, t], m.high[s, t], m.low[s, t], m.close[s, t]
        if np.isnan(c):
            continue
        if pending and t > t0:
            sell(float(o), remaining)
            break
        hit = None
        if t > t0 and o <= stop:
            hit = float(o)
        elif lo <= stop:
            hit = stop
        if hit is not None:
            sell(hit, remaining)
            break
        if not t1_done and h >= t1:
            sell(max(float(o), t1) if t > t0 else t1, remaining / 2)
            t1_done = True
            stop = max(stop, entry)
        if c >= entry + rules.breakeven_r * risk:
            reached = True
            stop = max(stop, entry)
        atr = m.atr14[s, t]
        if t1_done:
            if not math.isnan(trail) and c < trail:
                pending = True
            elif not math.isnan(atr):
                trail = max(np.nan_to_num(trail, nan=-math.inf), c - rules.trail_atr * atr)
        if t > t0:
            sessions += 1
        if (
            not pending
            and rules.time_stop
            and not reached
            and sessions >= tier_rules.time_stop_sessions
        ):
            pending = True
        last = float(c)
    if remaining > 1e-9:
        sell(last, remaining)
    return pnl / risk


@dataclass(frozen=True)
class MissedEntries:
    missed: int  # orders skipped for opening above the zone
    missed_avg_r: float | None
    missed_win_rate: float | None
    filled: int
    filled_avg_r: float | None  # the same measure (gross of charges) on the trades taken

    def to_dict(self) -> dict[str, float | int | str | None]:
        return {
            "missed": self.missed,
            "missed_avg_r": self.missed_avg_r,
            "missed_win_rate": self.missed_win_rate,
            "filled": self.filled,
            "filled_avg_r": self.filled_avg_r,
            "basis": "after slippage, before charges",
        }


def _avg(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def missed_entries(
    m: Market,
    tier: Tier,
    rules: PortfolioRules,
    costs: CostModel,
    skipped: Sequence[Skip],
    trades: Sequence[Trade],
    first: int,
    last: int,
) -> MissedEntries:
    """Missed (opened above the zone) against filled, for entries from `first` to
    `last` (session indexes, inclusive)."""
    rs = [
        r
        for k in skipped
        if k.reason == ABOVE_ZONE and first <= k.day <= last
        if (r := missed_r(m, tier, rules, costs, k, len(m.days) - 1)) is not None
    ]
    filled = [t.gross_pnl / t.risk for t in trades if first <= t.entry_day <= last and t.risk > 0]
    return MissedEntries(
        len(rs),
        _avg(rs),
        round(sum(r > 0 for r in rs) / len(rs), 3) if rs else None,
        len(filled),
        _avg(filled),
    )
