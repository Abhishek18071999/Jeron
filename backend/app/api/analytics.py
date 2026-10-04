"""Backtest vs paper vs my real results per strategy (spec section 7)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.analytics.service import StrategyCompare, compare
from app.analytics.weekly import build_weekly, weekly_message
from app.db import get_session

router = APIRouter(prefix="/analytics", tags=["analytics"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/compare")
def strategies(session: SessionDep) -> list[StrategyCompare]:
    """One row per paper account (strategy version), plus trades without a signal."""
    return compare(session)


class WeeklyOut(BaseModel):
    week_start: date
    day: date
    text: str


@router.get("/weekly")
def weekly(session: SessionDep, day: date | None = None) -> WeeklyOut:
    """This week's summary so far. Read-only: nothing is retired or sent from here."""
    w = build_weekly(session, day or date.today(), retire=False)
    return WeeklyOut(week_start=w.week_start, day=w.day, text=weekly_message(w))
