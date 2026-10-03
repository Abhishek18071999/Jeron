"""Turn an engine order into a spec section 4 signal.

The engine decides (entry condition, stop, sizing, every risk rule); this module
writes the decision down in the signal schema, with the reasons, targets and the
strategy's backtest record. Pure module: the paper job supplies the inputs.
"""

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.backtest.costs import CostModel
from app.backtest.engine import Order, PortfolioRules
from app.backtest.market import Market
from app.backtest.strategies import TIERS, Params, Strategy, Tier, params_label
from app.signals.schema import BacktestStats, Signal

IST = ZoneInfo("Asia/Kolkata")
MARKET_CLOSE = time(15, 30)
# Expected holding per tier, in sessions (spec section 1: swing 3-15 trading days,
# positional 1-6 months).
HOLDING = {Tier.SWING: (3, 15), Tier.POSITIONAL: (21, 126)}
# Conviction 1-5 from the technical score: below 60, 60s, 70s, 80s, 90 and above.
CONVICTION_STEPS = (60.0, 70.0, 80.0, 90.0)


def _d(value: float, places: str = "0.01") -> Decimal:
    return Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _rs(value: float) -> str:
    return f"₹{value:,.2f}"


def conviction(score: float) -> int:
    return 1 + sum(score >= step for step in CONVICTION_STEPS)


def backtest_stats(summary: dict[str, Any]) -> BacktestStats:
    """The out-of-sample record of a stored backtest run (`BacktestRun.summary`)."""
    oos = summary["out_of_sample"]
    trades, curve = oos["trades"], oos["curve"]
    pf = trades["profit_factor"]
    first, last = summary["periods"]["out_of_sample"]
    return BacktestStats(
        trades=trades["trades"],
        win_rate=_d(trades["win_rate"], "0.0001"),
        avg_R=_d(trades["avg_r"], "0.0001"),
        expectancy_R=_d(trades["expectancy_r"], "0.0001"),
        profit_factor=None if pf in (None, "inf") else _d(pf, "0.0001"),
        max_drawdown_pct=_d(curve["max_drawdown_pct"]),
        period=f"{first} to {last} (out of sample, after costs)",
    )


@dataclass(frozen=True)
class SignalContext:
    strategy: Strategy
    params: Params
    rules: PortfolioRules
    costs: CostModel
    backtest: BacktestStats
    research_only: bool
    created_at: datetime
    next_session: date  # the entry zone is valid for this session only
    notes: list[str] = field(default_factory=list)


def _value(a: Any, s: int, t: int) -> float:
    return float(a[s, t])


def reasons(m: Market, s: int, t: int, strategy: Strategy, params: Params) -> list[str]:
    """3-5 plain-language reasons: the strategy's condition first, then the trend and
    the technical score."""
    c, f = _value(m.close, s, t), _value(m.factor, s, t)
    raw = c / f
    out: list[str] = []
    if strategy.key == "breakout-52w":
        out.append(
            f"Closed at {_rs(raw)}, above the previous 52-week high of "
            f"{_rs(_value(m.prior_high_52w, s, t) / f)}"
        )
        out.append(
            f"Volume {_value(m.volume_ratio, s, t):.1f}x its 20-day average "
            f"(needs {params['volume_x']:g}x)"
        )
    elif strategy.key == "score-swing":
        prev = float(m.score[s, t - 1]) if t > 0 else math.nan
        before = "" if math.isnan(prev) else f" from {prev:.1f}"
        out.append(
            f"Technical score rose to {_value(m.score, s, t):.1f}{before}, crossing "
            f"{params['min_score']:g}"
        )
    elif strategy.key == "pullback-trend":
        out.append(
            f"RSI(14) turned back up to {_value(m.rsi14, s, t):.1f} after dipping below "
            f"{params['rsi_level']:g}"
        )
        out.append(f"Trend is strong: ADX(14) {_value(m.adx14, s, t):.1f}")
    ema200 = _value(m.ema200, s, t)
    if not math.isnan(ema200) and c > ema200:
        out.append(f"Above its 200-day EMA ({_rs(ema200 / f)}): long-term uptrend")
    ema20, ema50 = _value(m.ema20, s, t), _value(m.ema50, s, t)
    if not math.isnan(ema20) and not math.isnan(ema50) and ema20 > ema50 and len(out) < 4:
        out.append("20-day EMA above the 50-day EMA: medium-term uptrend")
    out.append(f"Technical score (tech-v1) {_value(m.score, s, t):.1f} of 100")
    atr = _value(m.atr14, s, t)
    if len(out) < 3:
        out.append(f"Daily range (ATR 14) is {atr / c * 100:.1f}% of the price")
    return out[:5]


def build_signal(
    m: Market, order: Order, ctx: SignalContext, signal_id: UUID | None = None
) -> Signal:
    """The signal for an order the engine placed at the close of `order.signal_day`.
    Raises `pydantic.ValidationError` if the result breaks the schema."""
    s, t = order.s, order.signal_day
    strategy, rules, costs = ctx.strategy, ctx.rules, ctx.costs
    tier = TIERS[strategy.tier]
    f = _value(m.factor, s, t)
    close = _value(m.close, s, t) / f
    atr = _value(m.atr14, s, t) / f
    stop = order.stop / f
    zone_high = order.zone_high / f
    risk = close - stop
    t1, t2 = close + rules.t1_r * risk, close + rules.t2_r * risk
    shares = order.raw_shares
    slip = order.slippage_pct / 100

    def reward_risk(target: float) -> float:
        # As the engine checks it: from the signal close, after estimated charges and
        # slippage on both sides.
        round_trip = (
            costs.charges(close * shares, "buy").total
            + costs.charges(target * shares, "sell").total
            + 2 * slip * close * shares
        )
        return ((target - close) * shares - round_trip) / (risk * shares + round_trip)

    day = m.days[t]
    time_stop = tier.time_stop_sessions
    one_r = close + rules.breakeven_r * risk
    return Signal(
        signal_id=signal_id or uuid4(),
        created_at=ctx.created_at,
        data_as_of=datetime.combine(day, MARKET_CLOSE, IST),
        ticker=m.symbols[s],
        setup_name=strategy.name,
        strategy_version=f"{strategy.version} ({params_label(ctx.params)})",
        tier=strategy.tier.value,
        direction="long",
        why=reasons(m, s, t, strategy, ctx.params),
        entry_zone={
            "low": _d(close),
            "high": _d(zone_high),
            "valid_until": ctx.next_session,
        },
        stop={
            "price": _d(stop),
            "type": "ATR",
            "reason": (
                f"{ctx.params['stop_atr']:g} x ATR(14) ({_rs(atr)}) below the signal close "
                f"{_rs(close)}"
            ),
        },
        targets={
            "t1": _d(t1),
            "t2": _d(t2),
            "basis": (
                f"+{rules.t1_r:g}R and +{rules.t2_r:g}R from the signal close, R = "
                f"{_rs(risk)}; after a fill, T1 is +{rules.t1_r:g}R from the fill price"
            ),
        },
        risk_reward_t1=_d(reward_risk(t1)),
        risk_reward_t2=_d(reward_risk(t2)),
        expected_holding={
            "min_days": HOLDING[strategy.tier][0],
            "max_days": HOLDING[strategy.tier][1],
        },
        shares=shares,
        capital_at_risk=_d((zone_high - stop) * shares),
        exit_plan=(
            f"Stop to breakeven once a close is at or above +{rules.breakeven_r:g}R "
            f"({_rs(one_r)}); book 50% at T1; trail the rest by {rules.trail_atr:g} x ATR(14) "
            "on closing basis, selling at the next open"
        ),
        time_stop_days=time_stop,
        invalidation=(
            f"Don't buy on {ctx.next_session} if it opens at or below the stop "
            f"({_rs(stop)}), stays above {_rs(zone_high)} all day, or is locked at the "
            "upper circuit. After entry, a trade at or below the stop ends the idea; "
            f"exit at the next open if it hasn't closed at +{rules.breakeven_r:g}R within "
            f"{time_stop} sessions."
        ),
        event_risk="Not checked: results dates and the event calendar arrive in M6.",
        conviction=conviction(order.score),
        brains_breakdown={
            "technical": _d(order.score, "0.1"),
            "fundamental": None,
            "news": None,
            "combined": _d(order.score, "0.1"),
        },
        backtest_stats=ctx.backtest,
        research_only=ctx.research_only,
        notes=list(ctx.notes),
    )
