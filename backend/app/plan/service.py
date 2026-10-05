"""Trade plans from the database: the stock's latest numbers, the market mood, the real
portfolio and the events ahead, then `app.plan.calc`. Saved plans are never changed."""

import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import indicators as ind
from app.backtest.strategies import TIERS, Tier
from app.config import Settings, get_settings
from app.data import store
from app.data.adjust import adjust_bars, build_adjustments
from app.data.events import EVENT_LOOKAHEAD_DAYS, blackout_signal_days, event_risk, next_results
from app.data.pipeline import BOARD_MEETINGS_SOURCE
from app.enums import CorporateActionType, Exchange
from app.journal.service import SignalInfo, signal_info
from app.market.mood import Mood
from app.market.service import latest_ok_scan, mood_on
from app.models import Instrument, ScanResult, TradePlan
from app.plan.calc import CHECKLIST_KEYS, Plan, PlanInputs, build_plan, missing_checklist
from app.portfolio.calc import UNKNOWN_SECTOR
from app.portfolio.service import portfolio

# Sessions of bars loaded when the stock isn't in the latest scan (ATR and volume).
FALLBACK_DAYS = 90
TURNOVER_SESSIONS = 20


class PlanError(Exception):
    """A plan that can't be saved; the message says why."""


@dataclass(frozen=True)
class StockFacts:
    symbol: str
    name: str | None
    sector: str | None
    last_close: Decimal | None
    last_date: date | None
    atr: float | None
    avg_volume20: float | None
    median_turnover: float | None
    swing_low: float | None
    score: Decimal | None
    rank: int | None
    in_scan: bool


@dataclass(frozen=True)
class Events:
    results_date: date | None
    results_line: str
    blackout: bool | None
    ex_dates: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Context:
    stock: StockFacts
    mood: Mood | None
    events: Events
    capital: Decimal
    risk_pct: float
    open_risk: Decimal
    sector_value: Decimal
    sector_cap_pct: Decimal
    signal: SignalInfo | None


def _f(value: object) -> float | None:
    return None if value is None else float(str(value))


def stock_facts(session: Session, symbol: str) -> StockFacts | None:
    instrument = session.scalar(
        select(Instrument).where(Instrument.exchange == Exchange.NSE, Instrument.symbol == symbol)
    )
    if instrument is None:
        return None
    run = latest_ok_scan(session)
    row = (
        None
        if run is None
        else session.scalar(
            select(ScanResult).where(ScanResult.run_id == run.id, ScanResult.symbol == symbol)
        )
    )
    end = run.trade_date if run is not None else None
    bars = store.symbol_bars(
        session,
        symbol,
        store.NSE_BARS,
        start=(end or date.today()) - timedelta(days=FALLBACK_DAYS * 2),
        end=end,
    )
    if not bars and end is not None:
        bars = store.symbol_bars(session, symbol, store.NSE_BARS)[-FALLBACK_DAYS:]
    turnovers = [float(b.turnover) for b in bars[-TURNOVER_SESSIONS:] if b.turnover is not None]
    last = bars[-1] if bars else None
    if row is not None:
        indicators = row.indicators or {}
        atr, avg_volume = _f(indicators.get("atr14")), _f(indicators.get("avg_volume20"))
        swing_low = _f(indicators.get("last_swing_low"))
    else:
        atr = avg_volume = swing_low = None
        if len(bars) > 20:
            actions = [a.record for a in store.symbol_actions(session, symbol, store.NSE_ACTIONS)]
            adjusted = adjust_bars(bars, build_adjustments(bars, actions))
            h = [float(a.high) for a in adjusted]
            lo = [float(a.low) for a in adjusted]
            c = [float(a.close) for a in adjusted]
            atr = ind.atr(h, lo, c)[-1]
            avg_volume = ind.sma([float(a.volume) for a in adjusted][:-1], 20)[-1]
    return StockFacts(
        symbol=symbol,
        name=instrument.name,
        sector=instrument.sector,
        last_close=None if last is None else last.close,
        last_date=None if last is None else last.trade_date,
        atr=atr,
        avg_volume20=avg_volume,
        median_turnover=statistics.median(turnovers) if turnovers else None,
        swing_low=swing_low,
        score=None if row is None else row.score,
        rank=None if row is None else row.rank,
        in_scan=row is not None,
    )


def _n(value: Decimal | None) -> str:
    return "?" if value is None else f"{value.normalize():f}"


def events_ahead(session: Session, symbol: str, day: date | None) -> Events:
    """Results and ex-dates after `day` (the latest session), as the signals word them."""
    day = day or date.today()
    loaded = store.board_meetings_loaded(session)
    results = store.results_dates(session, [symbol]).get(symbol, []) if loaded else None
    line = event_risk(results, day, store.board_meetings_updated(session, BOARD_MEETINGS_SOURCE))
    upcoming = next_results(results or [], day)
    when = upcoming.meeting_date if upcoming else None
    blackout = None if results is None else 0 in blackout_signal_days([day], results)
    ex_dates = []
    end = day + timedelta(days=EVENT_LOOKAHEAD_DAYS)
    for a in store.actions_between(
        session, store.NSE_ACTIONS, day + timedelta(days=1), end, [symbol]
    ):
        what = a.action_type.value
        if a.action_type in (CorporateActionType.SPLIT, CorporateActionType.BONUS):
            what += f" {_n(a.ratio_new)}:{_n(a.ratio_old)}"
        elif a.amount:
            what += f" ₹{_n(a.amount)}"
        ex_dates.append(f"{what}, ex-date {a.ex_date:%a %-d %b}")
    return Events(when, line, blackout, ex_dates)


def context(
    session: Session,
    symbol: str,
    *,
    signal_id: UUID | None = None,
    settings: Settings | None = None,
) -> Context | None:
    """None when the stock is unknown."""
    settings = settings or get_settings()
    facts = stock_facts(session, symbol)
    if facts is None:
        return None
    signal = signal_info(session, signal_id) if signal_id is not None else None
    if signal is not None and signal.ticker != symbol:
        raise PlanError(f"Signal {signal_id} is for {signal.ticker}, not {symbol}")
    p = portfolio(session, settings=settings)
    sector = facts.sector or UNKNOWN_SECTOR
    held = next((s.value for s in p.totals.sectors if s.sector == sector), Decimal(0))
    return Context(
        stock=facts,
        mood=mood_on(session),
        events=events_ahead(session, symbol, facts.last_date),
        capital=Decimal(str(settings.capital)),
        risk_pct=settings.risk_pct,
        open_risk=p.totals.open_risk,
        sector_value=held if facts.sector else Decimal(0),
        sector_cap_pct=Decimal(str(settings.sector_cap_pct)),
        signal=signal,
    )


def tier_of(value: str | None) -> Tier:
    """The plan's tier; a signal's "invest" tier uses the positional limits."""
    return Tier.SWING if value in (None, "", "swing") else Tier.POSITIONAL


@dataclass(frozen=True)
class Defaults:
    entry: Decimal | None
    stop: Decimal | None
    tier: Tier
    reason: str
    stop_hint: str


def defaults(ctx: Context) -> Defaults:
    """What the form starts with: the signal's levels, else the last close and a stop
    below the last swing low (or 2 x ATR when that low is too near or too far)."""
    if ctx.signal is not None:
        p = ctx.signal.payload
        tier = tier_of(p.get("tier"))
        return Defaults(
            Decimal(str(p["entry_zone"]["high"])),
            Decimal(str(p["stop"]["price"])),
            tier,
            str(p.get("setup_name", "")),
            f"the signal's stop: {p['stop'].get('reason', '')}".rstrip(": "),
        )
    s = ctx.stock
    close = s.last_close
    if close is None:
        return Defaults(None, None, Tier.SWING, "", "")
    if s.atr is None:
        return Defaults(close, None, Tier.SWING, "", "no ATR: set the stop yourself")
    c, atr = float(close), s.atr
    max_pct = TIERS[Tier.SWING].max_stop_pct
    if s.swing_low is not None and atr <= c - s.swing_low <= c * max_pct / 100:
        stop = Decimal(f"{s.swing_low * 0.995:.2f}")
        return Defaults(close, stop, Tier.SWING, "", "just below the last swing low")
    stop = Decimal(f"{c - 2 * atr:.2f}")
    return Defaults(close, stop, Tier.SWING, "", "2 x ATR below the last close")


def plan_for(ctx: Context, entry: Decimal, stop: Decimal, tier: Tier) -> Plan:
    mood = ctx.mood
    return build_plan(
        PlanInputs(
            ticker=ctx.stock.symbol,
            tier=tier,
            entry=entry,
            stop=stop,
            capital=ctx.capital,
            risk_pct=ctx.risk_pct,
            risk_multiplier=1.0 if mood is None else mood.risk_multiplier,
            mood=None if mood is None else mood.mode.value,
            atr=ctx.stock.atr,
            avg_volume20=ctx.stock.avg_volume20,
            median_turnover=ctx.stock.median_turnover,
            sector=ctx.stock.sector,
            open_risk=ctx.open_risk,
            sector_value=ctx.sector_value,
            sector_cap_pct=ctx.sector_cap_pct,
            results_blackout=ctx.events.blackout,
            results_line=ctx.events.results_line,
            ex_dates=ctx.events.ex_dates,
        )
    )


def _details(plan: Plan, ctx: Context) -> dict[str, Any]:
    i = plan.inputs
    return {
        "capital": str(i.capital),
        "risk_pct": i.risk_pct,
        "risk_multiplier": i.risk_multiplier,
        "sized_by": plan.sized_by,
        "atr": i.atr,
        "avg_volume20": i.avg_volume20,
        "median_turnover": i.median_turnover,
        "slippage_pct": plan.slippage_pct,
        "sector": i.sector,
        "reward_risk_t1": None if plan.reward_risk_t1 is None else str(plan.reward_risk_t1),
        "round_trip_costs": None if plan.round_trip_costs is None else str(plan.round_trip_costs),
        "stop_atr": None if plan.stop_atr is None else str(plan.stop_atr),
        "position_pct": str(plan.position_pct),
        "heat_before_pct": str(plan.heat_before_pct),
        "heat_after_pct": str(plan.heat_after_pct),
        "sector_before_pct": str(plan.sector_before_pct),
        "sector_after_pct": str(plan.sector_after_pct),
        "results_date": None if ctx.events.results_date is None else str(ctx.events.results_date),
        "results_line": ctx.events.results_line,
        "ex_dates": list(ctx.events.ex_dates),
        "checks": [asdict(c) for c in plan.checks],
    }


def latest_plan(session: Session, ticker: str, signal_id: UUID | None = None) -> TradePlan | None:
    query = select(TradePlan).where(TradePlan.ticker == ticker)
    if signal_id is not None:
        query = query.where(TradePlan.signal_id == signal_id)
    return session.scalar(query.order_by(TradePlan.id.desc()).limit(1))


def save_plan(
    session: Session,
    ticker: str,
    *,
    entry: Decimal,
    stop: Decimal,
    tier: Tier,
    reason: str,
    checklist: list[str],
    signal_id: UUID | None = None,
    settings: Settings | None = None,
) -> TradePlan:
    """Re-check everything on the server and store a new plan. Raises PlanError (with
    every reason) when a hard check fails or the checklist isn't complete."""
    ticker = ticker.strip().upper()
    ctx = context(session, ticker, signal_id=signal_id, settings=settings)
    if ctx is None:
        raise PlanError(f"Unknown stock {ticker}")
    if signal_id is not None and ctx.signal is None:
        raise PlanError(f"No signal {signal_id}")
    plan = plan_for(ctx, entry, stop, tier)
    problems = list(plan.blockers)
    unticked = missing_checklist(checklist)
    if unticked:
        problems.append("Tick every checklist item: " + "; ".join(unticked))
    if problems:
        raise PlanError(". ".join(problems))
    previous = latest_plan(session, ticker, signal_id)
    row = TradePlan(
        ticker=ticker,
        signal_id=signal_id,
        supersedes_id=None if previous is None else previous.id,
        tier=tier.value,
        entry=entry,
        stop=stop,
        target1=plan.target1,
        target2=plan.target2,
        shares=plan.shares,
        risk_amount=plan.risk_amount,
        position_value=plan.position_value,
        reward_risk_t2=plan.reward_risk_t2 or Decimal(0),
        stop_distance_pct=plan.stop_distance_pct or Decimal(0),
        mood=None if ctx.mood is None else ctx.mood.mode.value,
        reason=reason.strip(),
        data_as_of=ctx.stock.last_date,
        details=_details(plan, ctx),
        checklist=[k for k in CHECKLIST_KEYS if k in set(checklist)],
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def plans(
    session: Session,
    ticker: str | None = None,
    signal_id: UUID | None = None,
    limit: int = 50,
) -> list[TradePlan]:
    query = select(TradePlan)
    if ticker:
        query = query.where(TradePlan.ticker == ticker.strip().upper())
    if signal_id is not None:
        query = query.where(TradePlan.signal_id == signal_id)
    return list(session.scalars(query.order_by(TradePlan.id.desc()).limit(limit)))
