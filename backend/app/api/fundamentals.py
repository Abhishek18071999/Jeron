"""The fundamental brain on the stock page: the score, what it is made of and the
quarters behind it."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_session
from app.fundamentals.job import stock_fundamentals

router = APIRouter(tags=["fundamentals"])
SessionDep = Annotated[Session, Depends(get_session)]


class QuarterOut(BaseModel):
    period_end: date
    filed: date
    consolidated: bool
    revenue: float | None
    net_profit: float | None
    eps: float | None


class CashFlowYearOut(BaseModel):
    year_end: date
    operating_cash_flow: float
    profit: float | None


class HealthOut(BaseModel):
    """fundamentals-v2: balance sheet, cash flow and EV/EBITDA, shown not scored."""

    balance_sheet_as_of: date | None
    roe: float | None
    roce: float | None
    debt_equity: float | None
    ev_ebitda: float | None
    equity: float | None
    debt: float | None
    cash: float | None
    cash_flow: list[CashFlowYearOut]  # newest first, up to 3 financial years
    warnings: list[str]
    notes: list[str]


class FundamentalsOut(BaseModel):
    symbol: str
    as_of: date
    version: str
    score: float | None
    quality: float
    valuation: float
    rejected: str | None
    facts: dict[str, float | None]
    notes: list[str]
    quarters: list[QuarterOut]  # newest first, up to 12
    health: HealthOut


@router.get("/stocks/{symbol}/fundamentals")
def get_fundamentals(symbol: str, session: SessionDep) -> FundamentalsOut:
    found = stock_fundamentals(session, symbol.upper())
    if found is None:
        raise HTTPException(status_code=404, detail="No results loaded for this stock")
    s, h = found.score, found.health
    return FundamentalsOut(
        symbol=found.symbol,
        as_of=found.as_of,
        version=s.version,
        score=s.score,
        quality=s.quality,
        valuation=s.valuation,
        rejected=s.rejected,
        facts=s.facts,
        notes=s.notes,
        quarters=[
            QuarterOut(
                period_end=q.period_end,
                filed=q.disseminated_at.date(),
                consolidated=q.consolidated,
                revenue=q.revenue,
                net_profit=q.net_profit,
                eps=q.eps,
            )
            for q in reversed(found.quarters[-12:])
        ],
        health=HealthOut(
            balance_sheet_as_of=h.balance_sheet_as_of,
            roe=h.roe,
            roce=h.roce,
            debt_equity=h.debt_equity,
            ev_ebitda=h.ev_ebitda,
            equity=h.equity,
            debt=h.debt,
            cash=h.cash,
            cash_flow=[
                CashFlowYearOut(
                    year_end=y.year_end, operating_cash_flow=y.operating_cash_flow, profit=y.profit
                )
                for y in h.cash_flow
            ],
            warnings=h.warnings,
            notes=h.notes,
        ),
    )
