"""Every strategy version: status, evidence and paper health; the registry of all
versions tried (decision 0018)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analytics.strategies import Registry, StrategyView, registry, strategy_views
from app.db import get_session

router = APIRouter(prefix="/strategies", tags=["strategies"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("")
def strategies(session: SessionDep) -> list[StrategyView]:
    """One row per strategy version in the code, with its status and why."""
    return strategy_views(session)


@router.get("/registry")
def strategy_registry(session: SessionDep) -> Registry:
    """Every version tried, kept or dropped, and how many parameter sets that is."""
    return registry(session)
