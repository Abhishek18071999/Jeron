"""My real portfolio: open journal positions with exit plans, heat and sector exposure."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.backtest.engine import PortfolioRules
from app.db import get_session
from app.portfolio.calc import AccountState, Holding, SectorExposure
from app.portfolio.service import portfolio as build_portfolio
from app.settings_store import effective_settings

RULES = PortfolioRules()

router = APIRouter(tags=["portfolio"])
SessionDep = Annotated[Session, Depends(get_session)]


class HoldingOut(BaseModel):
    entry_id: int
    ticker: str
    strategy_key: str | None
    sector: str | None
    shares: int
    avg_entry: Decimal
    last_close: Decimal | None
    last_close_date: date | None
    stop: Decimal | None
    initial_stop: Decimal | None
    value: Decimal | None
    pnl: Decimal | None
    r_multiple: Decimal | None
    open_risk: Decimal | None
    give_back: Decimal | None
    stop_distance_pct: Decimal | None
    first_date: date
    days_held: int
    sessions_held: int | None
    action: str | None
    reason: str | None
    problem: str | None
    events: list[str]
    notes: list[str]


class ExemptionOut(BaseModel):
    year: int
    label: str
    long_term: Decimal
    short_term: Decimal
    exemption: Decimal
    used: Decimal
    left: Decimal
    line: str


class TotalsOut(BaseModel):
    positions: int
    value: Decimal
    pnl: Decimal
    open_risk: Decimal
    heat_pct: Decimal
    give_back: Decimal
    without_stop: int
    heat_warn_pct: Decimal
    heat_block_pct: Decimal
    sector_cap_pct: Decimal
    capital: Decimal
    sectors: list[SectorExposure]
    warnings: list[str]
    invested: Decimal
    pending_cost: Decimal
    idle_cash: Decimal
    cash_action: str | None
    tax_notes: list[str]
    exemption: ExemptionOut | None


class AccountOut(BaseModel):
    """The real account's guardrails as the trade plan applies them (app/plan/calc.py)."""

    as_of: date
    equity: Decimal
    peak: Decimal
    drawdown_pct: Decimal
    drawdown_halve_pct: Decimal
    drawdown_pause_pct: Decimal
    # "normal" / "halved" (risk per trade halved) / "paused" (no new entries)
    brake: str
    realised_today: Decimal
    realised_week: Decimal
    daily_loss_limit: Decimal | None  # rupees; None when the limit is off
    weekly_loss_limit: Decimal | None
    entries_week: int
    max_entries_week: int | None
    limits_block: bool
    open_by_tier: dict[str, int]


class PortfolioOut(BaseModel):
    day: date
    data_as_of: date | None
    expected: date
    stale: bool
    holdings: list[HoldingOut]
    totals: TotalsOut
    account: AccountOut | None = None


def _account(a: AccountState, session: Session) -> AccountOut:
    settings = effective_settings(session)
    halve, pause = Decimal(str(RULES.drawdown_halve_pct)), Decimal(str(RULES.drawdown_pause_pct))

    def limit(pct: float) -> Decimal | None:
        return None if pct <= 0 else (a.capital * Decimal(str(pct)) / 100).quantize(Decimal(1))

    return AccountOut(
        as_of=a.as_of,
        equity=a.equity,
        peak=a.peak,
        drawdown_pct=a.drawdown_pct,
        drawdown_halve_pct=halve,
        drawdown_pause_pct=pause,
        brake="paused"
        if a.drawdown_pct >= pause
        else ("halved" if a.drawdown_pct >= halve else "normal"),
        realised_today=a.realised_today,
        realised_week=a.realised_week,
        daily_loss_limit=limit(settings.daily_loss_limit_pct),
        weekly_loss_limit=limit(settings.weekly_loss_limit_pct),
        entries_week=a.entries_week,
        max_entries_week=settings.max_entries_week or None,
        limits_block=settings.risk_limits_block,
        open_by_tier=a.open_by_tier,
    )


def _holding(h: Holding, as_of: date) -> HoldingOut:
    return HoldingOut(
        entry_id=h.entry_id,
        ticker=h.ticker,
        strategy_key=h.strategy_key,
        sector=h.sector,
        shares=h.shares,
        avg_entry=h.avg_entry,
        last_close=h.last_close,
        last_close_date=h.last_close_date,
        stop=h.stop,
        initial_stop=h.initial_stop,
        value=h.value,
        pnl=h.pnl,
        r_multiple=h.r_multiple,
        open_risk=h.open_risk,
        give_back=h.give_back,
        stop_distance_pct=h.stop_distance_pct,
        first_date=h.first_date,
        days_held=h.days_held(as_of),
        sessions_held=h.sessions_held,
        action=h.action,
        reason=h.reason,
        problem=h.problem,
        events=h.events,
        notes=h.notes,
    )


@router.get("/portfolio")
def portfolio(session: SessionDep, day: date | None = None) -> PortfolioOut:
    """Open journal positions as the next pre-open check (or `day`'s) sees them."""
    p = build_portfolio(session, day)
    as_of = p.data_as_of or p.expected
    return PortfolioOut(
        day=p.day,
        data_as_of=p.data_as_of,
        expected=p.expected,
        stale=p.stale,
        holdings=[_holding(h, as_of) for h in p.holdings],
        totals=TotalsOut.model_validate(p.totals, from_attributes=True),
        account=None if p.account is None else _account(p.account, session),
    )
