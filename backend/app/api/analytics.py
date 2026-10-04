"""Backtest vs paper vs my real results per strategy (spec section 7)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analytics.service import StrategyCompare, compare
from app.db import get_session

router = APIRouter(prefix="/analytics", tags=["analytics"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/compare")
def strategies(session: SessionDep) -> list[StrategyCompare]:
    """One row per paper account (strategy version), plus trades without a signal."""
    return compare(session)
