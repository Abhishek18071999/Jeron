"""The four sections of the app (docs/plans/sections-v1.md): swing, intraday, positional
and long-term, one per holding horizon. Each holds the strategies of its tier, says in
one line whether there is anything to buy, and turns each signal into what to buy,
when, how much and why.

Nothing is decided here: signals are the paper accounts' (decision 0006), and a section
whose strategies all failed spec section 6 says so instead of offering picks. Pure
module: `app.sections.service` supplies the inputs.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.alerts.format import inr, order_line
from app.backtest.costs import small_trade_warning
from app.backtest.strategies import Tier


class SectionKey(StrEnum):
    SWING = "swing"
    INTRADAY = "intraday"
    POSITIONAL = "positional"
    INVEST = "invest"


class State(StrEnum):
    LIVE = "live"  # a strategy passed section 6: its signals are the ones to act on
    RESEARCH = "research"  # strategies tested, none passed: nothing to buy
    UNTESTED = "untested"  # strategies registered, no backtest run yet
    NOT_RUNNING = "not_running"  # no data for it (intraday)


@dataclass(frozen=True)
class SectionDef:
    key: SectionKey
    name: str
    holding: str
    tier: Tier | None
    about: str


SECTIONS = (
    SectionDef(
        SectionKey.SWING,
        "Swing",
        "3 to 15 sessions",
        Tier.SWING,
        "Short moves in liquid stocks, out within three weeks.",
    ),
    SectionDef(
        SectionKey.INTRADAY,
        "Intraday",
        "within one session",
        None,
        "Positions opened and closed during market hours, nothing held overnight.",
    ),
    SectionDef(
        SectionKey.POSITIONAL,
        "Positional",
        "1 to 6 months",
        Tier.POSITIONAL,
        "Trends in market leaders, held for weeks to months.",
    ),
    SectionDef(
        SectionKey.INVEST,
        "Long-term",
        "6 to 12 months or more",
        Tier.INVEST,
        "Companies with strong results, held while the results and the trend hold.",
    ),
)
BY_KEY = {s.key: s for s in SECTIONS}

# Why intraday is not running, and what it would take (docs/plans/sections-v1.md).
INTRADAY_NEEDS = [
    "Jeron only has NSE's end-of-day files. An intraday strategy needs years of minute "
    "prices to be backtested like every other strategy, and live prices during the day.",
    "NSE publishes no free intraday history, and Yahoo Finance keeps 1-minute prices for "
    "the last 7 days only: enough to watch, not to test.",
    "Two broker sources would do: Zerodha Kite Connect's paid Connect plan (reported at "
    "₹500 a month in 2026; the free Personal plan has no market data), or Angel One's "
    "SmartAPI, free with an Angel One account. Both serve historical minute candles and "
    "live quotes.",
    "With a source chosen, intraday is its own milestone: minute bars, an intraday engine "
    "with MIS costs and the 15:20 square-off, strategies written down before they are "
    "tested, and the same seven backtest checks.",
]


def section_for_tier(tier: str) -> SectionKey:
    """The section of a signal's tier."""
    return SectionKey(tier)


@dataclass(frozen=True)
class StrategyState:
    key: str
    version: str
    name: str
    summary: str
    tier: Tier
    backtested: bool
    passed: bool  # live-eligible: passed every spec section 6 check
    gates_passed: int = 0
    gates_total: int = 0
    failed_gates: tuple[str, ...] = ()
    oos_trades: int | None = None
    oos_expectancy_r: float | None = None
    run_id: int | None = None
    account_id: int | None = None
    account_status: str | None = None  # "active", "retired" or None
    retired_reason: str | None = None
    paper_closed_trades: int = 0
    paper_return_pct: float | None = None
    paper_open_positions: int = 0

    @property
    def stage(self) -> str:
        if self.account_status == "retired":
            return "retired"
        if not self.backtested:
            return "waiting for its first backtest"
        if not self.passed:
            return "research only"
        if self.account_id is None:
            return "passed; paper account not opened yet"
        return "paper trading"


@dataclass(frozen=True)
class SectionStatus:
    state: State
    headline: str


def _versions(states: Sequence[StrategyState]) -> str:
    names = [s.version for s in states]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def status(section: SectionDef, strategies: Sequence[StrategyState]) -> SectionStatus:
    """The section's state in one line."""
    if section.tier is None:
        return SectionStatus(
            State.NOT_RUNNING,
            "Not running: Jeron has no intraday prices yet, so no intraday strategy can be "
            "tested. Nothing to buy here.",
        )
    live = [s for s in strategies if s.passed and s.account_status != "retired"]
    if live:
        opened = [s for s in live if s.account_id is not None]
        if not opened:
            return SectionStatus(
                State.LIVE,
                f"{_versions(live)} passed the backtest; run paper to open its account "
                "and start its signals.",
            )
        one = len(opened) == 1
        return SectionStatus(
            State.LIVE,
            f"Live: {_versions(opened)} passed the backtest and {'is' if one else 'are'} "
            f"paper trading. {'Its' if one else 'Their'} signals are the ones to act on.",
        )
    tested = [s for s in strategies if s.backtested]
    if tested:
        return SectionStatus(
            State.RESEARCH,
            f"Nothing to buy: no {section.name.lower()} strategy has passed the backtest "
            "bar. Its signals are research only, for evidence, not trades.",
        )
    if strategies:
        return SectionStatus(
            State.UNTESTED,
            f"Nothing to buy yet: {_versions(strategies)} is waiting for its first "
            f"backtest. Run: backtest --strategy {strategies[0].key}, then paper.",
        )
    return SectionStatus(State.RESEARCH, "Nothing to buy: no strategy in this section yet.")


def _day(d: date | str) -> str:
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return d.strftime("%a %-d %b")


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


@dataclass(frozen=True)
class SignalCard:
    """One signal as what to buy, when, how much and why."""

    signal_id: UUID
    ticker: str
    signal_date: date
    strategy_key: str
    research_only: bool
    setup_name: str
    strategy_version: str
    conviction: int
    entry_low: Decimal
    entry_high: Decimal
    valid_until: date
    stop: Decimal
    t1: Decimal
    t2: Decimal
    shares: int
    cost: Decimal  # shares at the top of the entry zone
    cost_pct: Decimal  # of capital
    at_risk: Decimal
    at_risk_pct: Decimal
    what: str
    when: str
    how_much: str
    cancel_if: str
    why: list[str]
    exit_plan: str
    holding: str
    event_risk: str
    backtest: str
    notes: list[str] = field(default_factory=list)


def card(
    signal_id: UUID,
    signal_date: date,
    strategy_key: str,
    research_only: bool,
    payload: Mapping[str, Any],
    capital: Decimal,
) -> SignalCard:
    p = payload
    zone, bt = p["entry_zone"], p["backtest_stats"]
    shares = int(p["shares"])
    high = _dec(zone["high"])
    cost = high * shares
    at_risk = _dec(p["capital_at_risk"])
    cost_pct = cost / capital * 100 if capital > 0 else Decimal(0)
    risk_pct = at_risk / capital * 100 if capital > 0 else Decimal(0)
    valid = date.fromisoformat(zone["valid_until"])
    pf = bt["profit_factor"]
    holding = p["expected_holding"]
    return SignalCard(
        signal_id=signal_id,
        ticker=p["ticker"],
        signal_date=signal_date,
        strategy_key=strategy_key,
        research_only=research_only,
        setup_name=p["setup_name"],
        strategy_version=p["strategy_version"],
        conviction=int(p["conviction"]),
        entry_low=_dec(zone["low"]),
        entry_high=high,
        valid_until=valid,
        stop=_dec(p["stop"]["price"]),
        t1=_dec(p["targets"]["t1"]),
        t2=_dec(p["targets"]["t2"]),
        shares=shares,
        cost=cost.quantize(Decimal("0.01")),
        cost_pct=cost_pct.quantize(Decimal("0.1")),
        at_risk=at_risk,
        at_risk_pct=risk_pct.quantize(Decimal("0.01")),
        what=(
            f"{'Research only, not a trade: ' if research_only else ''}Buy {p['ticker']}: "
            f"{p['setup_name']}, conviction {p['conviction']}/5. Stop {inr(p['stop']['price'])}, "
            f"targets {inr(p['targets']['t1'])} and {inr(p['targets']['t2'])}."
        ),
        when=f"On {_day(valid)}. " + order_line(p).removeprefix("How: "),
        how_much=(
            f"{shares:,} shares, about {inr(cost, 0)} at the top of the zone "
            f"({cost_pct:.1f}% of capital), {inr(at_risk, 0)} at risk ({risk_pct:.2f}% of "
            "capital) if the stop is hit."
        ),
        cancel_if=p["invalidation"],
        why=list(p["why"]),
        exit_plan=p["exit_plan"],
        holding=(
            f"{holding['min_days']} to {holding['max_days']} sessions; time stop "
            f"{p['time_stop_days']} sessions"
        ),
        event_risk=p["event_risk"],
        backtest=(
            f"{bt['trades']} trades out of sample, expectancy {_dec(bt['expectancy_R']):.2f}R, "
            f"profit factor {'n/a' if pf is None else f'{_dec(pf):.2f}'}, max drawdown "
            f"{_dec(bt['max_drawdown_pct']):.1f}% ({bt['period']})"
        ),
        notes=[*p.get("notes", []), *filter(None, [small_trade_warning(float(at_risk))])],
    )
