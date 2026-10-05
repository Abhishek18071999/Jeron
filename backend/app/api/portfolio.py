"""My real portfolio: open journal positions with exit plans, heat and sector exposure."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_session
from app.portfolio.calc import Holding, SectorExposure
from app.portfolio.service import portfolio as build_portfolio

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


class PortfolioOut(BaseModel):
    day: date
    data_as_of: date | None
    expected: date
    stale: bool
    holdings: list[HoldingOut]
    totals: TotalsOut


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
    )
