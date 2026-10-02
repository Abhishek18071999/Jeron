"""Backtest runs: report cards, trades and the variants tried."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import BacktestRun, BacktestTrade, BacktestVariant

router = APIRouter(prefix="/backtests", tags=["backtests"])
SessionDep = Annotated[Session, Depends(get_session)]


class RunSummary(BaseModel):
    id: int
    strategy_key: str
    strategy_version: str
    strategy_name: str
    tier: str
    data_start: date
    data_end: date
    oos_start: date
    holdout_start: date
    live_eligible: bool
    fingerprint: str
    created_at: datetime
    trades: dict[str, Any]
    curve: dict[str, Any]
    gates: list[dict[str, Any]]


class Variant(BaseModel):
    window: str
    label: str
    params: dict[str, Any]
    train_start: date
    train_end: date
    trades: int
    expectancy_r: Decimal
    sharpe: Decimal
    chosen: bool


class RunView(BaseModel):
    run: RunSummary
    summary: dict[str, Any]
    equity: list[dict[str, Any]]
    variants: list[Variant]
    runs_of_strategy: int


class Trade(BaseModel):
    seq: int
    segment: str
    symbol: str
    variant: str
    signal_date: date
    entry_date: date
    exit_date: date
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    exit_price: Decimal
    shares: int
    exit_reason: str
    gross_pnl: Decimal
    charges: Decimal
    dividends: Decimal
    net_pnl: Decimal
    r_multiple: Decimal
    regime: str
    score: Decimal
    sessions: int
    open_at_end: bool


def _summary(run: BacktestRun) -> RunSummary:
    oos = run.summary.get("out_of_sample", {})
    return RunSummary(
        id=run.id,
        strategy_key=run.strategy_key,
        strategy_version=run.strategy_version,
        strategy_name=run.strategy_name,
        tier=run.tier,
        data_start=run.data_start,
        data_end=run.data_end,
        oos_start=run.oos_start,
        holdout_start=run.holdout_start,
        live_eligible=run.live_eligible,
        fingerprint=run.fingerprint,
        created_at=run.created_at,
        trades=oos.get("trades", {}),
        curve=oos.get("curve", {}),
        gates=run.summary.get("gates", []),
    )


@router.get("")
def latest_runs(session: SessionDep) -> list[RunSummary]:
    """The newest run of each strategy."""
    newest = (
        select(BacktestRun.strategy_key, func.max(BacktestRun.id).label("id"))
        .group_by(BacktestRun.strategy_key)
        .subquery()
    )
    runs = session.scalars(
        select(BacktestRun)
        .join(newest, newest.c.id == BacktestRun.id)
        .order_by(BacktestRun.strategy_key)
    )
    return [_summary(r) for r in runs]


@router.get("/runs")
def all_runs(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> list[RunSummary]:
    runs = session.scalars(select(BacktestRun).order_by(BacktestRun.id.desc()).limit(limit))
    return [_summary(r) for r in runs]


def _run(session: Session, run_id: int) -> BacktestRun:
    run = session.get(BacktestRun, run_id)
    if run is None:
        raise HTTPException(404, f"No backtest run {run_id}")
    return run


@router.get("/{run_id}")
def run_view(run_id: int, session: SessionDep) -> RunView:
    run = _run(session, run_id)
    variants = session.scalars(
        select(BacktestVariant).where(BacktestVariant.run_id == run.id).order_by(BacktestVariant.id)
    )
    count = session.scalar(
        select(func.count())
        .select_from(BacktestRun)
        .where(BacktestRun.strategy_key == run.strategy_key)
    )
    return RunView(
        run=_summary(run),
        summary=run.summary,
        equity=run.equity,
        variants=[Variant.model_validate(v, from_attributes=True) for v in variants],
        runs_of_strategy=count or 0,
    )


@router.get("/{run_id}/trades")
def run_trades(
    run_id: int,
    session: SessionDep,
    segment: Annotated[str | None, Query(pattern="^(oos|holdout)$")] = None,
) -> list[Trade]:
    _run(session, run_id)
    stmt = select(BacktestTrade).where(BacktestTrade.run_id == run_id)
    if segment:
        stmt = stmt.where(BacktestTrade.segment == segment)
    rows = session.scalars(stmt.order_by(BacktestTrade.seq))
    return [Trade.model_validate(r, from_attributes=True) for r in rows]
