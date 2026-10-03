"""Paper-trading accounts and the signals they issued."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.strategies import STRATEGIES
from app.db import get_session
from app.models import PaperAccount, PaperDay, PaperTrade, SignalRecord

router = APIRouter(tags=["paper"])
SessionDep = Annotated[Session, Depends(get_session)]


class Account(BaseModel):
    id: int
    strategy_key: str
    strategy_version: str
    strategy_name: str
    tier: str
    params_label: str
    backtest_run_id: int
    live_eligible: bool
    stage: str  # "research only" or "paper"
    start_date: date
    last_date: date | None
    capital: Decimal
    status: str
    rules: dict[str, Any]
    summary: dict[str, Any]


class Trade(BaseModel):
    seq: int
    signal_id: UUID | None
    ticker: str
    status: str
    signal_date: date
    entry_date: date
    entry_price: Decimal
    initial_stop: Decimal
    target_t1: Decimal
    shares: int
    current_stop: Decimal | None
    last_close: Decimal | None
    shares_held: int
    exit_date: date | None
    exit_price: Decimal | None
    exit_reason: str | None
    charges: Decimal
    dividends: Decimal
    net_pnl: Decimal
    r_multiple: Decimal
    sessions: int
    exits: list[dict[str, Any]]


class Day(BaseModel):
    trade_date: date
    equity: Decimal
    drawdown_pct: Decimal
    heat_pct: Decimal
    open_positions: int


class SignalView(BaseModel):
    signal_id: UUID
    version: int
    account_id: int
    strategy_key: str
    ticker: str
    signal_date: date
    research_only: bool
    late: bool
    created_at: datetime
    payload: dict[str, Any]


class AccountView(BaseModel):
    account: Account
    open_trades: list[Trade]
    closed_trades: list[Trade]
    days: list[Day]
    signals: list[SignalView]


def _account(a: PaperAccount) -> Account:
    strategy = STRATEGIES.get(a.strategy_key)
    return Account(
        id=a.id,
        strategy_key=a.strategy_key,
        strategy_version=a.strategy_version,
        strategy_name=strategy.name if strategy else a.strategy_key,
        tier=strategy.tier.value if strategy else "",
        params_label=a.params_label,
        backtest_run_id=a.backtest_run_id,
        live_eligible=a.live_eligible,
        stage="paper" if a.live_eligible else "research only",
        start_date=a.start_date,
        last_date=a.last_date,
        capital=a.capital,
        status=a.status,
        rules=a.rules,
        summary=a.summary,
    )


def _signal(r: SignalRecord, keys: dict[int, str]) -> SignalView:
    return SignalView(
        signal_id=r.signal_id,
        version=r.version,
        account_id=r.account_id,
        strategy_key=keys.get(r.account_id, ""),
        ticker=r.ticker,
        signal_date=r.signal_date,
        research_only=r.research_only,
        late=r.late,
        created_at=r.created_at,
        payload=r.payload,
    )


def _keys(session: Session) -> dict[int, str]:
    rows = session.execute(select(PaperAccount.id, PaperAccount.strategy_key))
    return {id_: key for id_, key in rows}


@router.get("/paper/accounts")
def paper_accounts(session: SessionDep, include_closed: bool = False) -> list[Account]:
    query = select(PaperAccount).order_by(PaperAccount.id.desc())
    if not include_closed:
        query = query.where(PaperAccount.status == "active")
    return [_account(a) for a in session.scalars(query)]


@router.get("/paper/accounts/{account_id}")
def paper_account(
    account_id: int, session: SessionDep, signals: Annotated[int, Query(ge=0, le=1000)] = 50
) -> AccountView:
    account = session.get(PaperAccount, account_id)
    if account is None:
        raise HTTPException(404, f"No paper account {account_id}")
    trades = [
        Trade.model_validate(t, from_attributes=True)
        for t in session.scalars(
            select(PaperTrade).where(PaperTrade.account_id == account_id).order_by(PaperTrade.seq)
        )
    ]
    days = [
        Day.model_validate(d, from_attributes=True)
        for d in session.scalars(
            select(PaperDay).where(PaperDay.account_id == account_id).order_by(PaperDay.trade_date)
        )
    ]
    keys = {account.id: account.strategy_key}
    recent = session.scalars(
        select(SignalRecord)
        .where(SignalRecord.account_id == account_id)
        .order_by(SignalRecord.signal_date.desc(), SignalRecord.ticker)
        .limit(signals)
    )
    return AccountView(
        account=_account(account),
        open_trades=[t for t in trades if t.status == "open"],
        closed_trades=[t for t in trades if t.status == "closed"],
        days=days,
        signals=[_signal(r, keys) for r in recent],
    )


@router.get("/signals")
def signals(
    session: SessionDep,
    signal_date: Annotated[date | None, Query(alias="date")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[SignalView]:
    """Signals for one day, or the newest ones."""
    query = select(SignalRecord).order_by(
        SignalRecord.signal_date.desc(), SignalRecord.account_id, SignalRecord.ticker
    )
    if signal_date is not None:
        query = query.where(SignalRecord.signal_date == signal_date)
    keys = _keys(session)
    return [_signal(r, keys) for r in session.scalars(query.limit(limit))]


@router.get("/signals/{signal_id}")
def signal(signal_id: UUID, session: SessionDep) -> SignalView:
    row = session.get(SignalRecord, signal_id)
    if row is None:
        raise HTTPException(404, f"No signal {signal_id}")
    return _signal(row, _keys(session))
