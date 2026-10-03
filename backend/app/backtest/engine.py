"""The event-driven daily-bar backtest engine (spec sections 5 and 6).

One pass over the sessions. Each day, in this order:

0. Idle cash earns a liquid-fund rate for the calendar days since the last session.
1. Open: yesterday's orders try to fill. A buy fills at the open if the open is
   within the entry zone (at or below the signal close + 0.5 x ATR), or at the top of
   the zone if the day trades down to it; it is skipped if the stock opens below the
   stop, doesn't trade, runs away above the zone, or is locked at the upper circuit.
   Exits decided at yesterday's close (trailing stop, time stop) sell at the open.
2. During the day: a stop sells at the stop price, or at the open if the stock gaps
   below it. On a day locked at the lower circuit (no trades except at the limit) the
   stop can't fill and sells at the next open that trades. If the stop and the +2R
   target are both inside the day's range, the stop is assumed to come first. Half
   the position is sold at the +2R target (T1); the stop moves to breakeven.
3. Close: stop to breakeven once a close is +1R; after T1, the rest trails at
   2 x ATR(14) below the highest close and is sold at the next open after a close
   below the trail; the tier's time stop sells at the next open if +1R hasn't been
   reached. Equity is marked to the close. A position held into an ex-date gets
   the dividend, even if it is sold that day.
4. New entries from today's signals, sized by the risk rules, become orders for
   tomorrow.

Prices are split- and bonus-adjusted, so a split mid-trade changes nothing; share
counts are whole raw shares at entry. Every buy and sell pays slippage and the
Indian charges in `app.backtest.costs`.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from app.backtest.costs import CostModel
from app.backtest.features import Array
from app.backtest.market import Market, Regime
from app.backtest.strategies import TIERS, Params, Tier

# A full-day circuit lock with no published band: the smallest band is 2%.
DEFAULT_LOCK_MOVE_PCT = 1.9


@dataclass(frozen=True)
class PortfolioRules:
    capital: float = 1_000_000.0
    risk_pct: float = 1.0
    max_position_pct: float = 20.0
    max_volume_pct: float = 1.0
    heat_block_pct: float = 6.0
    drawdown_halve_pct: float = 10.0
    drawdown_pause_pct: float = 15.0
    pause_sessions: int = 20
    entry_zone_atr: float = 0.5
    t1_r: float = 2.0
    t2_r: float = 3.0
    breakeven_r: float = 1.0
    trail_atr: float = 2.0
    min_stop_atr: float = 1.0
    min_reward_risk_t2: float = 2.0
    # Idle cash sits in a liquid fund: a yearly rate, accrued per calendar day.
    cash_rate_pct: float = 6.5
    heat_warn_pct: float = 5.0
    # Overrides the tier's maximum number of open positions.
    max_positions: int | None = None
    # Opt-in portfolio rules (spec section 5), off in backtests: NSE's archive has no
    # point-in-time sectors. A sector may hold at most this % of equity; stocks
    # without a sector are not capped.
    sector_cap_pct: float | None = None
    # Skip a stock whose daily returns over `correlation_sessions` correlate at least
    # `correlation_min` with `max_correlated` stocks already held or ordered.
    max_correlated: int | None = None
    correlation_min: float = 0.7
    correlation_sessions: int = 120


@dataclass(frozen=True)
class Variant:
    """One grid point of a strategy, with its precomputed entry signals."""

    label: str
    params: Params
    entries: Array  # bool (stocks, days)


@dataclass
class Fill:
    day: int
    price: float  # adjusted, after slippage
    shares: float  # adjusted shares
    charges: float
    reason: str


@dataclass
class Trade:
    s: int
    symbol: str
    variant: str
    signal_day: int
    entry_day: int
    entry: float  # adjusted price paid, after slippage
    stop0: float
    t1: float
    shares: float  # adjusted shares bought
    raw_shares: int
    entry_charges: float
    score: float
    regime: Regime
    risk_off: bool
    stop: float = 0.0
    trail: float = math.nan
    t1_done: bool = False
    reached_1r: bool = False
    pending_exit: str | None = None
    remaining: float = 0.0
    sessions: int = 0
    dividends: float = 0.0
    exits: list[Fill] = field(default_factory=list)
    open_at_end: bool = False

    @property
    def risk(self) -> float:
        """Rupees at risk at entry: (entry - initial stop) x shares."""
        return (self.entry - self.stop0) * self.shares

    @property
    def exit_day(self) -> int:
        return self.exits[-1].day if self.exits else self.entry_day

    @property
    def exit_price(self) -> float:
        sold = sum(f.shares for f in self.exits)
        return sum(f.price * f.shares for f in self.exits) / sold if sold else math.nan

    @property
    def charges(self) -> float:
        return self.entry_charges + sum(f.charges for f in self.exits)

    @property
    def gross_pnl(self) -> float:
        return sum((f.price - self.entry) * f.shares for f in self.exits)

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - self.charges + self.dividends

    @property
    def r_multiple(self) -> float:
        return self.net_pnl / self.risk if self.risk > 0 else 0.0

    @property
    def exit_reason(self) -> str:
        return self.exits[-1].reason if self.exits else ""


@dataclass
class Order:
    s: int
    variant: str
    signal_day: int
    stop: float
    zone_high: float
    raw_shares: int
    score: float
    slippage_pct: float


@dataclass
class Skip:
    s: int
    day: int
    reason: str


@dataclass
class SimResult:
    start: int
    end: int
    equity: Array  # one value per session from start to end
    trades: list[Trade]
    skipped: list[Skip]
    brake_events: list[tuple[int, str]]
    dividends: list[tuple[int, float]]
    interest: list[tuple[int, float]] = field(default_factory=list)
    # Every order placed (signal at a close, to fill the next session).
    orders: list[Order] = field(default_factory=list)
    # Orders placed at the last close (only with `orders_on_last_day`).
    pending: list[Order] = field(default_factory=list)
    # Positions still open at the end (only without `close_at_end`).
    open_trades: list[Trade] = field(default_factory=list)
    # Open risk (entry - stop) x shares as % of equity, per session from start to end.
    heat_pct: Array = field(default_factory=lambda: np.zeros(0))


def _locked(m: Market, s: int, t: int, prev_close: float, down: bool) -> bool:
    """Whether the day traded only at one price, at a circuit limit."""
    h, lo, c = m.high[s, t], m.low[s, t], m.close[s, t]
    if h != lo or not prev_close or math.isnan(prev_close):
        return False
    move = (c / prev_close - 1) * 100
    band = m.band_pct[s, t]
    limit = (band - 0.1) if not math.isnan(band) else DEFAULT_LOCK_MOVE_PCT
    return bool(move <= -limit) if down else bool(move >= limit)


def correlation(m: Market, a: int, b: int, t: int, sessions: int) -> float:
    """Correlation of two stocks' daily returns over the `sessions` up to day t, on
    the days both traded (NaN with fewer than half of them)."""
    lo = max(0, t - sessions)
    ca, cb = m.close[a, lo : t + 1], m.close[b, lo : t + 1]
    ra, rb = ca[1:] / ca[:-1] - 1, cb[1:] / cb[:-1] - 1
    both = ~np.isnan(ra) & ~np.isnan(rb)
    if both.sum() < max(sessions // 2, 3):
        return math.nan
    x, y = ra[both], rb[both]
    if x.std() == 0 or y.std() == 0:
        return math.nan
    return float(np.corrcoef(x, y)[0, 1])


def simulate(
    market: Market,
    tier: Tier,
    schedule: Sequence[tuple[int, Variant]],
    start: int,
    end: int,
    rules: PortfolioRules | None = None,
    costs: CostModel | None = None,
    *,
    close_at_end: bool = True,
    orders_on_last_day: bool = False,
) -> SimResult:
    """Run from session `start` to `end` (inclusive). `schedule` is (first session,
    variant) pairs, oldest first: the variant whose signals are traded from that day.

    A backtest sells what is still open at the last close. Paper trading keeps it
    open (`close_at_end=False`) and places orders at the last close for the next
    session (`orders_on_last_day=True`)."""
    rules = rules or PortfolioRules()
    costs = costs or CostModel()
    tier_rules = TIERS[tier]
    max_positions = rules.max_positions or tier_rules.max_positions
    m = market
    cash = rules.capital
    peak = rules.capital
    paused_until = -1
    pause_floor = math.inf
    open_trades: list[Trade] = []
    done: list[Trade] = []
    orders: list[Order] = []
    skipped: list[Skip] = []
    brakes: list[tuple[int, str]] = []
    dividends: list[tuple[int, float]] = []
    interest: list[tuple[int, float]] = []
    placed: list[Order] = []
    heat_pct = np.zeros(end - start + 1)
    daily_rate = (1 + rules.cash_rate_pct / 100) ** (1 / 365) - 1
    equity = np.zeros(end - start + 1)
    last_close = np.full(len(m.symbols), math.nan)
    if start > 0:
        # Closes before the start, for circuit checks and marking.
        before = m.close[:, :start]
        has = ~np.isnan(before)
        idx = np.where(has.any(axis=1), before.shape[1] - 1 - np.argmax(has[:, ::-1], axis=1), -1)
        for k in np.flatnonzero(idx >= 0):
            last_close[k] = before[k, idx[k]]
    schedule = sorted(schedule, key=lambda x: x[0])

    def sell(trade: Trade, day: int, price: float, shares: float, reason: str) -> None:
        nonlocal cash
        slip = costs.slippage_pct(np.nan_to_num(m.median_turnover[trade.s, day]))
        fill_price = price * (1 - slip / 100)
        value = fill_price * shares
        charges = costs.charges(value, "sell").total
        cash += value - charges
        trade.exits.append(Fill(day, fill_price, shares, charges, reason))
        trade.remaining -= shares

    def variant_for(day: int) -> Variant | None:
        active = None
        for first, variant in schedule:
            if first <= day:
                active = variant
        return active

    for t in range(start, end + 1):
        # 0. Interest on the cash held since the last session.
        if t > start and cash > 0 and daily_rate:
            gap = (m.days[t] - m.days[t - 1]).days
            earned = cash * ((1 + daily_rate) ** gap - 1)
            cash += earned
            interest.append((t, earned))

        # 1. Orders from yesterday's signals.
        for order in orders:
            s = order.s
            if np.isnan(m.close[s, t]):
                skipped.append(Skip(s, t, "did not trade the next day"))
                continue
            if _locked(m, s, t, last_close[s], down=False):
                skipped.append(Skip(s, t, "locked at the upper circuit"))
                continue
            o, lo = m.open[s, t], m.low[s, t]
            if o <= order.stop:
                skipped.append(Skip(s, t, "opened below the stop"))
                continue
            if o <= order.zone_high:
                price = o
            elif lo <= order.zone_high:
                price = order.zone_high
            else:
                skipped.append(Skip(s, t, "ran above the entry zone"))
                continue
            fill = price * (1 + order.slippage_pct / 100)
            factor = m.factor[s, t]
            raw = order.raw_shares
            unit = fill / factor  # raw rupees per raw share
            if raw * unit + costs.charges(raw * unit, "buy").total > cash:
                raw = math.floor(cash / (unit * 1.002))
                while raw > 0 and raw * unit + costs.charges(raw * unit, "buy").total > cash:
                    raw -= 1
            if raw < 1:
                skipped.append(Skip(s, t, "not enough cash"))
                continue
            shares = raw / factor
            charges = costs.charges(fill * shares, "buy").total
            cash -= fill * shares + charges
            risk_per_share = fill - order.stop
            trade = Trade(
                s=s,
                symbol=m.symbols[s],
                variant=order.variant,
                signal_day=order.signal_day,
                entry_day=t,
                entry=fill,
                stop0=order.stop,
                t1=fill + rules.t1_r * risk_per_share,
                shares=shares,
                raw_shares=raw,
                entry_charges=charges,
                score=order.score,
                regime=m.regime[order.signal_day],
                risk_off=bool(m.risk_off[order.signal_day]),
                stop=order.stop,
                remaining=shares,
            )
            open_trades.append(trade)
        orders = []

        # 2 and 3. Manage open positions.
        still_open: list[Trade] = []
        for trade in open_trades:
            s = trade.s
            if np.isnan(m.close[s, t]):
                if t > m.last_day[s]:
                    # The stock never trades again (delisted or merged): valued at
                    # its last close, which may flatter the result.
                    sell(
                        trade,
                        int(m.last_day[s]),
                        last_close[s],
                        trade.remaining,
                        "stopped trading (sold at last close)",
                    )
                    done.append(trade)
                else:
                    still_open.append(trade)
                continue
            if m.dividend[s, t] > 0 and trade.entry_day < t:
                # Held into the ex-date, so the dividend is ours even if we sell today.
                amount = m.dividend[s, t] * trade.remaining
                trade.dividends += amount
                cash += amount
                dividends.append((t, amount))
            o, h, lo, c = m.open[s, t], m.high[s, t], m.low[s, t], m.close[s, t]
            locked_down = _locked(m, s, t, last_close[s], down=True)
            if trade.pending_exit and trade.entry_day < t:
                if locked_down:
                    still_open.append(trade)
                    last_close[s] = c
                    continue
                sell(trade, t, o, trade.remaining, trade.pending_exit)
                done.append(trade)
                last_close[s] = c
                continue
            hit = None
            if trade.entry_day < t and o <= trade.stop:
                hit = o
            elif lo <= trade.stop:
                hit = trade.stop
            if hit is not None:
                reason = "stop" if trade.stop < trade.entry else "breakeven stop"
                if locked_down:
                    trade.pending_exit = f"{reason} (lower circuit, sold next open)"
                    still_open.append(trade)
                    last_close[s] = c
                    continue
                sell(trade, t, hit, trade.remaining, reason)
                done.append(trade)
                last_close[s] = c
                continue
            if not trade.t1_done and h >= trade.t1:
                price = max(o, trade.t1) if trade.entry_day < t else trade.t1
                half_raw = math.floor(trade.remaining * m.factor[s, t] / 2)
                if half_raw >= 1:
                    sell(trade, t, price, half_raw / m.factor[s, t], "target T1 (+2R), half")
                trade.t1_done = True
                trade.stop = max(trade.stop, trade.entry)
            r = trade.entry - trade.stop0
            if c >= trade.entry + rules.breakeven_r * r:
                trade.reached_1r = True
                trade.stop = max(trade.stop, trade.entry)
            atr = m.atr14[s, t]
            if trade.t1_done:
                if not math.isnan(trade.trail) and c < trade.trail:
                    trade.pending_exit = "trailing stop (2 x ATR, closing basis)"
                elif not math.isnan(atr):
                    trade.trail = max(
                        np.nan_to_num(trade.trail, nan=-math.inf), c - rules.trail_atr * atr
                    )
            if trade.entry_day < t:
                trade.sessions += 1
            if (
                trade.pending_exit is None
                and not trade.reached_1r
                and trade.sessions >= tier_rules.time_stop_sessions
            ):
                trade.pending_exit = f"time stop ({tier_rules.time_stop_sessions} sessions)"
            last_close[s] = c
            still_open.append(trade)
        open_trades = still_open
        traded_today = ~np.isnan(m.close[:, t])
        last_close[traded_today] = m.close[traded_today, t]

        # Mark to market.
        value = cash + sum(tr.remaining * last_close[tr.s] for tr in open_trades)
        equity[t - start] = value
        open_risk = sum(max(0.0, tr.entry - tr.stop) * tr.remaining for tr in open_trades)
        heat_pct[t - start] = open_risk / value * 100 if value > 0 else 0.0
        if value > peak:
            peak = value
        drawdown = (1 - value / peak) * 100
        if value >= peak:
            pause_floor = math.inf
        if drawdown >= rules.drawdown_pause_pct and t >= paused_until and value < pause_floor:
            # Pause, then resume (at half risk while the drawdown is above 10%). Pause
            # again only if equity falls a further 5%.
            paused_until = t + rules.pause_sessions
            pause_floor = value * 0.95
            brakes.append((t, f"drawdown {drawdown:.1f}%: new entries paused"))

        # 4. New signals at today's close, filled tomorrow.
        if (t == end and not orders_on_last_day) or m.quality_fail[t] or t < paused_until:
            continue
        variant = variant_for(t)
        if variant is None:
            continue
        candidates = [int(k) for k in np.flatnonzero(variant.entries[:, t])]
        if len(candidates) == 0:
            continue
        held = {tr.s for tr in open_trades}
        ranked = sorted(
            (s for s in candidates if s not in held),
            key=lambda s: (-np.nan_to_num(m.score[s, t], nan=-1.0), m.symbols[s]),
        )
        risk_mult = 1.0
        if m.risk_off[t]:
            risk_mult *= 0.5
        if drawdown >= rules.drawdown_halve_pct:
            risk_mult *= 0.5
        heat = sum(max(0.0, tr.entry - tr.stop) * tr.remaining for tr in open_trades)
        slots = max_positions - len(open_trades)
        sector_value: dict[str, float] = {}
        if rules.sector_cap_pct is not None:
            for tr in open_trades:
                sector = m.sectors[tr.s]
                if sector:
                    sector_value[sector] = (
                        sector_value.get(sector, 0.0) + tr.remaining * last_close[tr.s]
                    )
        holding = [tr.s for tr in open_trades]
        for s in ranked:
            if slots <= 0:
                skipped.append(Skip(s, t, "no free position slot"))
                continue
            c, atr = m.close[s, t], m.atr14[s, t]
            if math.isnan(atr) or atr <= 0:
                skipped.append(Skip(s, t, "no ATR"))
                continue
            distance = variant.params["stop_atr"] * atr
            if distance < rules.min_stop_atr * atr or distance / c * 100 > tier_rules.max_stop_pct:
                skipped.append(Skip(s, t, f"stop more than {tier_rules.max_stop_pct:g}% away"))
                continue
            stop = c - distance
            zone_high = c + rules.entry_zone_atr * atr
            factor = m.factor[s, t]
            budget = value * rules.risk_pct / 100 * risk_mult
            raw_risk = (zone_high - stop) / factor
            raw = math.floor(budget / raw_risk)
            raw = min(raw, math.floor(value * rules.max_position_pct / 100 / (zone_high / factor)))
            avg_volume = m.avg_volume20[s, t]
            if not math.isnan(avg_volume):
                raw = min(raw, math.floor(avg_volume * factor * rules.max_volume_pct / 100))
            if raw < 1:
                skipped.append(Skip(s, t, "position too small"))
                continue
            shares = raw / factor
            slip = costs.slippage_pct(np.nan_to_num(m.median_turnover[s, t]))
            # Reward:risk to T2 after estimated round-trip costs (spec section 4).
            round_trip = (
                costs.charges(c * shares, "buy").total
                + costs.charges((c + rules.t2_r * distance) * shares, "sell").total
                + 2 * slip / 100 * c * shares
            )
            reward = rules.t2_r * distance * shares - round_trip
            risk = distance * shares + round_trip
            if reward / risk < rules.min_reward_risk_t2:
                skipped.append(Skip(s, t, "reward:risk to T2 below 2 after costs"))
                continue
            new_risk = (zone_high - stop) * shares
            if (heat + new_risk) / value * 100 > rules.heat_block_pct:
                skipped.append(Skip(s, t, f"portfolio heat above {rules.heat_block_pct:g}%"))
                continue
            sector = m.sectors[s]
            if rules.sector_cap_pct is not None and sector:
                after = sector_value.get(sector, 0.0) + zone_high * shares
                if after / value * 100 > rules.sector_cap_pct:
                    skipped.append(
                        Skip(s, t, f"sector {sector} above {rules.sector_cap_pct:g}% of equity")
                    )
                    continue
            if rules.max_correlated is not None:
                together = [
                    h
                    for h in holding
                    if correlation(m, s, h, t, rules.correlation_sessions) >= rules.correlation_min
                ]
                if len(together) >= rules.max_correlated:
                    names = ", ".join(sorted(m.symbols[h] for h in together))
                    skipped.append(
                        Skip(s, t, f"moves with {names} (correlation >= {rules.correlation_min:g})")
                    )
                    continue
            heat += new_risk
            slots -= 1
            if sector:
                sector_value[sector] = sector_value.get(sector, 0.0) + zone_high * shares
            holding.append(s)
            order = Order(
                s,
                variant.label,
                t,
                stop,
                zone_high,
                raw,
                float(np.nan_to_num(m.score[s, t], nan=0.0)),
                slip,
            )
            orders.append(order)
            placed.append(order)

    still: list[Trade] = []
    for trade in open_trades:
        trade.open_at_end = True
        if close_at_end:
            sell(
                trade,
                end,
                last_close[trade.s],
                trade.remaining,
                "open at the end (marked at close)",
            )
            done.append(trade)
        else:
            still.append(trade)
    done.sort(key=lambda tr: (tr.entry_day, tr.symbol))
    return SimResult(
        start,
        end,
        equity,
        done,
        skipped,
        brakes,
        dividends,
        interest,
        orders=placed,
        pending=orders if orders_on_last_day else [],
        open_trades=still,
        heat_pct=heat_pct,
    )
