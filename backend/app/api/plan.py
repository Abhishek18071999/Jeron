"""Trade plans (decision 0010): size a buy the engine's way, check it, save it."""

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.journal import SignalBrief, brief
from app.db import get_session
from app.models import TradePlan
from app.plan import service
from app.plan.calc import CHECKLIST, Plan
from app.plan.service import PlanError, tier_of

router = APIRouter(tags=["plan"])
SessionDep = Annotated[Session, Depends(get_session)]
TierIn = Literal["swing", "positional"]


class CheckOut(BaseModel):
    key: str
    label: str
    status: str
    detail: str
    hard: bool


class PlanOut(BaseModel):
    entry: Decimal
    stop: Decimal
    tier: str
    shares: int
    sized_by: str
    risk_per_share: Decimal
    risk_amount: Decimal
    position_value: Decimal
    position_pct: Decimal
    target1: Decimal
    target2: Decimal
    reward_risk_t1: Decimal | None
    reward_risk_t2: Decimal | None
    round_trip_costs: Decimal | None
    slippage_pct: float
    stop_distance_pct: Decimal | None
    stop_atr: Decimal | None
    heat_before_pct: Decimal
    heat_after_pct: Decimal
    heat_warn_pct: Decimal
    heat_block_pct: Decimal
    sector_before_pct: Decimal
    sector_after_pct: Decimal
    sector_cap_pct: Decimal
    risk_pct: float
    risk_multiplier: float
    checks: list[CheckOut]
    ok: bool
    blockers: list[str]


class StockOut(BaseModel):
    symbol: str
    name: str | None
    sector: str | None
    last_close: Decimal | None
    last_date: date | None
    atr: float | None
    avg_volume20: float | None
    score: Decimal | None
    rank: int | None
    in_scan: bool


class MoodOut(BaseModel):
    day: date
    mode: str
    reason: str
    risk_multiplier: float


class EventsOut(BaseModel):
    results_date: date | None
    results_line: str
    blackout: bool | None
    ex_dates: list[str]


class DefaultsOut(BaseModel):
    entry: Decimal | None
    stop: Decimal | None
    tier: str
    reason: str
    stop_hint: str


class SavedPlan(BaseModel):
    id: int
    ticker: str
    signal_id: UUID | None
    supersedes_id: int | None
    tier: str
    entry: Decimal
    stop: Decimal
    target1: Decimal
    target2: Decimal
    shares: int
    risk_amount: Decimal
    position_value: Decimal
    reward_risk_t2: Decimal
    stop_distance_pct: Decimal
    mood: str | None
    reason: str
    data_as_of: date | None
    details: dict[str, Any]
    checklist: list[str]
    created_at: datetime


class PlanView(BaseModel):
    stock: StockOut
    signal: SignalBrief | None
    defaults: DefaultsOut
    mood: MoodOut | None
    events: EventsOut
    capital: Decimal
    open_risk: Decimal
    plan: PlanOut | None
    checklist: list[dict[str, str]]
    saved: list[SavedPlan]


class PlanIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=32)
    tier: TierIn = "swing"
    entry: Decimal = Field(gt=0)
    stop: Decimal = Field(gt=0)
    reason: str = Field(default="", max_length=2000)
    signal_id: UUID | None = None
    checklist: list[str] = []


def plan_out(plan: Plan) -> PlanOut:
    i = plan.inputs
    return PlanOut(
        entry=i.entry,
        stop=i.stop,
        tier=i.tier.value,
        shares=plan.shares,
        sized_by=plan.sized_by,
        risk_per_share=plan.risk_per_share,
        risk_amount=plan.risk_amount,
        position_value=plan.position_value,
        position_pct=plan.position_pct,
        target1=plan.target1,
        target2=plan.target2,
        reward_risk_t1=plan.reward_risk_t1,
        reward_risk_t2=plan.reward_risk_t2,
        round_trip_costs=plan.round_trip_costs,
        slippage_pct=plan.slippage_pct,
        stop_distance_pct=plan.stop_distance_pct,
        stop_atr=plan.stop_atr,
        heat_before_pct=plan.heat_before_pct,
        heat_after_pct=plan.heat_after_pct,
        heat_warn_pct=i.heat_warn_pct,
        heat_block_pct=i.heat_block_pct,
        sector_before_pct=plan.sector_before_pct,
        sector_after_pct=plan.sector_after_pct,
        sector_cap_pct=i.sector_cap_pct,
        risk_pct=i.risk_pct,
        risk_multiplier=i.risk_multiplier,
        checks=[CheckOut(**asdict(c)) for c in plan.checks],
        ok=plan.ok,
        blockers=plan.blockers,
    )


def saved_out(row: TradePlan) -> SavedPlan:
    return SavedPlan.model_validate(row, from_attributes=True)


@router.get("/plan/{symbol}")
def plan_view(
    symbol: str,
    session: SessionDep,
    entry: Annotated[Decimal | None, Query(gt=0)] = None,
    stop: Annotated[Decimal | None, Query(gt=0)] = None,
    tier: TierIn | None = None,
    signal_id: UUID | None = None,
) -> PlanView:
    """The plan for a buy at `entry` with `stop` (default: the signal's levels, else the
    last close and a suggested stop), sized and checked, with what it is checked against."""
    symbol = symbol.strip().upper()
    try:
        ctx = service.context(session, symbol, signal_id=signal_id)
    except PlanError as e:
        raise HTTPException(422, str(e)) from None
    if ctx is None:
        raise HTTPException(404, f"Unknown stock {symbol}")
    if signal_id is not None and ctx.signal is None:
        raise HTTPException(404, f"No signal {signal_id}")
    d = service.defaults(ctx)
    chosen_tier = tier_of(tier) if tier else d.tier
    entry, stop = entry or d.entry, stop or d.stop
    plan = (
        None if entry is None or stop is None else service.plan_for(ctx, entry, stop, chosen_tier)
    )
    mood = ctx.mood
    return PlanView(
        stock=StockOut(
            **{k: v for k, v in asdict(ctx.stock).items() if k in StockOut.model_fields}
        ),
        signal=None if ctx.signal is None else brief(ctx.signal),
        defaults=DefaultsOut(
            entry=d.entry, stop=d.stop, tier=d.tier.value, reason=d.reason, stop_hint=d.stop_hint
        ),
        mood=None
        if mood is None
        else MoodOut(
            day=mood.day,
            mode=mood.mode.value,
            reason=mood.reason,
            risk_multiplier=mood.risk_multiplier,
        ),
        events=EventsOut(**asdict(ctx.events)),
        capital=ctx.capital,
        open_risk=ctx.open_risk,
        plan=None if plan is None else plan_out(plan),
        checklist=[{"key": k, "label": label} for k, label in CHECKLIST],
        saved=[saved_out(p) for p in service.plans(session, symbol, limit=10)],
    )


@router.post("/plans")
def save(body: PlanIn, session: SessionDep) -> SavedPlan:
    """Save a plan: every hard check must pass and every checklist item be ticked. Plans
    are never changed; saving again makes a new plan that supersedes the last one."""
    try:
        row = service.save_plan(
            session,
            body.ticker,
            entry=body.entry,
            stop=body.stop,
            tier=tier_of(body.tier),
            reason=body.reason,
            checklist=body.checklist,
            signal_id=body.signal_id,
        )
    except PlanError as e:
        raise HTTPException(422, str(e)) from None
    return saved_out(row)


@router.get("/plans")
def list_plans(
    session: SessionDep,
    ticker: str | None = None,
    signal_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[SavedPlan]:
    return [saved_out(p) for p in service.plans(session, ticker, signal_id, limit)]


@router.get("/plans/{plan_id}")
def get_plan(plan_id: int, session: SessionDep) -> SavedPlan:
    row = session.get(TradePlan, plan_id)
    if row is None:
        raise HTTPException(404, f"No plan {plan_id}")
    return saved_out(row)
