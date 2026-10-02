"""The daily scan's results."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import ScanResult, ScanRun
from app.scan.score import SCORE_VERSION

router = APIRouter(prefix="/scan", tags=["scan"])
SessionDep = Annotated[Session, Depends(get_session)]


class RunSummary(BaseModel):
    id: int
    trade_date: date
    score_version: str
    status: str
    universe_size: int
    duration_seconds: Decimal | None
    reasons: list[str]
    created_at: datetime


class Component(BaseModel):
    key: str
    label: str
    value: float | None
    points: float
    max_points: float


class Result(BaseModel):
    rank: int
    symbol: str
    score: Decimal
    close: Decimal
    in_nifty500: bool
    sector: str | None
    components: list[Component]
    indicators: dict[str, Any]


class ScanView(BaseModel):
    run: RunSummary
    details: dict[str, Any]
    total_results: int
    results: list[Result]


def _summary(run: ScanRun) -> RunSummary:
    return RunSummary(
        id=run.id,
        trade_date=run.trade_date,
        score_version=run.score_version,
        status=run.status,
        universe_size=run.universe_size,
        duration_seconds=run.duration_seconds,
        reasons=list(run.details.get("reasons", [])),
        created_at=run.created_at,
    )


def _view(session: Session, run: ScanRun, limit: int, min_score: float) -> ScanView:
    rows = session.scalars(
        select(ScanResult)
        .where(ScanResult.run_id == run.id, ScanResult.score >= min_score)
        .order_by(ScanResult.rank)
    ).all()
    return ScanView(
        run=_summary(run),
        details=run.details,
        total_results=len(rows),
        results=[
            Result(
                rank=r.rank,
                symbol=r.symbol,
                score=r.score,
                close=r.close,
                in_nifty500=r.in_nifty500,
                sector=r.sector,
                components=[Component(**c) for c in r.components],
                indicators=r.indicators,
            )
            for r in rows[:limit]
        ],
    )


Limit = Annotated[int, Query(ge=1, le=3000)]
MinScore = Annotated[float, Query(ge=0, le=100)]


@router.get("/runs")
def scan_runs(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=500)] = 30
) -> list[RunSummary]:
    runs = session.scalars(
        select(ScanRun)
        .where(ScanRun.score_version == SCORE_VERSION)
        .order_by(ScanRun.trade_date.desc())
        .limit(limit)
    )
    return [_summary(r) for r in runs]


@router.get("/latest")
def latest_scan(session: SessionDep, limit: Limit = 100, min_score: MinScore = 0) -> ScanView:
    run = session.scalar(
        select(ScanRun)
        .where(ScanRun.score_version == SCORE_VERSION)
        .order_by(ScanRun.trade_date.desc())
        .limit(1)
    )
    if run is None:
        raise HTTPException(404, "No scan has run yet")
    return _view(session, run, limit, min_score)


@router.get("/{trade_date}")
def scan_for_date(
    trade_date: date, session: SessionDep, limit: Limit = 100, min_score: MinScore = 0
) -> ScanView:
    run = session.scalar(
        select(ScanRun).where(
            ScanRun.trade_date == trade_date, ScanRun.score_version == SCORE_VERSION
        )
    )
    if run is None:
        raise HTTPException(404, f"No scan for {trade_date}")
    return _view(session, run, limit, min_score)
