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


@router.get("/stocks/{symbol}/fundamentals")
def get_fundamentals(symbol: str, session: SessionDep) -> FundamentalsOut:
    found = stock_fundamentals(session, symbol.upper())
    if found is None:
        raise HTTPException(status_code=404, detail="No results loaded for this stock")
    s = found.score
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
    )
