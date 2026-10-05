"""The journal (spec section 8): what I did with each signal, and my fills."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.journal import importer, service
from app.journal.calc import StrategyStats
from app.journal.service import EntryView, JournalError, SignalInfo
from app.models import JournalEntry, JournalFill

router = APIRouter(prefix="/journal", tags=["journal"])
SessionDep = Annotated[Session, Depends(get_session)]
Decision = Literal["taken", "skipped", "modified"]


class SignalBrief(BaseModel):
    signal_id: UUID
    ticker: str
    signal_date: date
    strategy_key: str
    research_only: bool
    setup_name: str
    conviction: int
    entry_low: Decimal
    entry_high: Decimal
    valid_until: date
    stop: Decimal
    t1: Decimal
    t2: Decimal
    shares: int
    capital_at_risk: Decimal
    # The signal's event-risk line when it was made (results ahead, calendar not loaded).
    event_risk: str = ""


class FillOut(BaseModel):
    id: int
    trade_date: date
    side: str
    shares: int
    price: Decimal
    charges: Decimal
    charges_estimated: bool
    source: str


class PositionOut(BaseModel):
    status: str
    bought: int
    sold: int
    held: int
    avg_entry: Decimal | None
    avg_exit: Decimal | None
    first_date: date | None
    last_date: date | None
    charges: Decimal
    realised_pnl: Decimal
    open_pnl: Decimal | None
    initial_risk: Decimal | None
    r_multiple: Decimal | None


class EntryOut(BaseModel):
    id: int
    ticker: str
    strategy_key: str | None
    decision: str
    reason: str
    stop: Decimal | None  # mine, else the signal's
    own_stop: bool
    followed_plan: bool | None
    notes: str
    plan_id: int | None = None
    created_at: datetime
    updated_at: datetime
    signal: SignalBrief | None
    fills: list[FillOut]
    last_close: Decimal | None
    last_close_date: date | None
    position: PositionOut


class StatsOut(BaseModel):
    strategy_key: str | None
    signals: int
    pending: int
    taken: int
    skipped: int
    modified: int
    open: int
    closed: int
    wins: int
    win_rate: Decimal | None
    avg_r: Decimal | None
    profit_factor: Decimal | None
    net_pnl: Decimal
    avg_holding_days: Decimal | None
    followed: int
    deviated: int
    followed_avg_r: Decimal | None
    deviated_avg_r: Decimal | None


class JournalView(BaseModel):
    entries: list[EntryOut]
    pending: list[SignalBrief]
    stats: list[StatsOut]


class SignalJournal(BaseModel):
    signal: SignalBrief
    payload: dict[str, Any]
    entry: EntryOut | None


class DecisionIn(BaseModel):
    decision: Decision
    reason: str = ""
    stop: Decimal | None = Field(default=None, gt=0)
    followed_plan: bool | None = None
    notes: str = ""
    plan_id: int | None = None


class ManualIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=32)
    reason: str = ""
    stop: Decimal | None = Field(default=None, gt=0)
    notes: str = ""
    plan_id: int | None = None


class FillIn(BaseModel):
    trade_date: date
    side: Literal["buy", "sell"]
    shares: int = Field(gt=0)
    price: Decimal = Field(gt=0)
    charges: Decimal = Field(default=Decimal(0), ge=0)


def brief(info: SignalInfo) -> SignalBrief:
    p = info.payload

    def d(value: Any) -> Decimal:
        return Decimal(str(value))

    return SignalBrief(
        signal_id=info.signal_id,
        ticker=info.ticker,
        signal_date=info.signal_date,
        strategy_key=info.strategy_key,
        research_only=info.research_only,
        setup_name=p["setup_name"],
        conviction=p["conviction"],
        entry_low=d(p["entry_zone"]["low"]),
        entry_high=d(p["entry_zone"]["high"]),
        valid_until=date.fromisoformat(p["entry_zone"]["valid_until"]),
        stop=d(p["stop"]["price"]),
        t1=d(p["targets"]["t1"]),
        t2=d(p["targets"]["t2"]),
        shares=p["shares"],
        capital_at_risk=d(p["capital_at_risk"]),
        event_risk=p.get("event_risk", ""),
    )


def entry_out(view: EntryView) -> EntryOut:
    e = view.entry
    return EntryOut(
        id=e.id,
        ticker=e.ticker,
        strategy_key=e.strategy_key,
        decision=e.decision,
        reason=e.reason,
        stop=view.stop,
        own_stop=e.stop is not None,
        followed_plan=e.followed_plan,
        notes=e.notes,
        plan_id=e.plan_id,
        created_at=e.created_at,
        updated_at=e.updated_at,
        signal=brief(view.signal) if view.signal else None,
        fills=[FillOut.model_validate(f, from_attributes=True) for f in view.fills],
        last_close=view.last_close,
        last_close_date=view.last_close_date,
        position=PositionOut.model_validate(view.position, from_attributes=True),
    )


def stats_out(s: StrategyStats) -> StatsOut:
    return StatsOut.model_validate(s, from_attributes=True)


def _one(session: Session, entry: JournalEntry) -> EntryOut:
    session.refresh(entry)
    return entry_out(service.entry_views(session, [entry])[0])


def _entry(session: Session, entry_id: int) -> JournalEntry:
    entry = session.get(JournalEntry, entry_id)
    if entry is None:
        raise HTTPException(404, f"No journal entry {entry_id}")
    return entry


@router.get("")
def journal(
    session: SessionDep,
    pending_days: Annotated[int, Query(ge=1, le=3650)] = 30,
    research: bool = True,
) -> JournalView:
    """Entries (newest first), signals waiting for a decision, and stats per strategy."""
    views = service.entry_views(session)
    since = date.today() - timedelta(days=pending_days)
    pending = service.pending_signals(session, since=since, include_research=research)
    return JournalView(
        entries=[entry_out(v) for v in views],
        pending=[brief(p) for p in pending],
        stats=[stats_out(s) for s in service.stats(session, views)],
    )


@router.get("/signal/{signal_id}")
def signal_journal(signal_id: UUID, session: SessionDep) -> SignalJournal:
    info = service.signal_info(session, signal_id)
    if info is None:
        raise HTTPException(404, f"No signal {signal_id}")
    entry = session.scalar(select(JournalEntry).where(JournalEntry.signal_id == signal_id))
    return SignalJournal(
        signal=brief(info),
        payload=info.payload,
        entry=None if entry is None else _one(session, entry),
    )


@router.put("/signal/{signal_id}")
def decide(signal_id: UUID, body: DecisionIn, session: SessionDep) -> EntryOut:
    try:
        entry = service.decide(session, signal_id, **body.model_dump())
    except JournalError as e:
        raise HTTPException(404 if "No signal" in str(e) else 422, str(e)) from None
    return _one(session, entry)


@router.post("")
def manual(body: ManualIn, session: SessionDep) -> EntryOut:
    try:
        entry = service.manual_entry(session, **body.model_dump())
    except JournalError as e:
        raise HTTPException(422, str(e)) from None
    return _one(session, entry)


class TradebookIn(BaseModel):
    csv: str = Field(min_length=1, max_length=10_000_000)


class ImportOut(BaseModel):
    added: int
    already: int
    to_signals: int
    new_entries: int
    skipped: dict[str, int]
    problems: list[str]


@router.post("/import")
def import_tradebook(body: TradebookIn, session: SessionDep) -> ImportOut:
    """Fills from a Zerodha tradebook CSV; a re-import adds nothing."""
    result = importer.import_tradebook(session, body.csv)
    return ImportOut(**vars(result))


@router.get("/{entry_id}")
def entry(entry_id: int, session: SessionDep) -> EntryOut:
    return _one(session, _entry(session, entry_id))


@router.put("/{entry_id}")
def update(entry_id: int, body: DecisionIn, session: SessionDep) -> EntryOut:
    entry = _entry(session, entry_id)
    try:
        service.update_entry(session, entry, **body.model_dump())
    except JournalError as e:
        raise HTTPException(422, str(e)) from None
    return _one(session, entry)


@router.post("/{entry_id}/fills")
def add_fill(entry_id: int, body: FillIn, session: SessionDep) -> EntryOut:
    entry = _entry(session, entry_id)
    try:
        service.add_fill(session, entry, **body.model_dump())
    except JournalError as e:
        raise HTTPException(422, str(e)) from None
    return _one(session, entry)


@router.delete("/fills/{fill_id}")
def delete_fill(fill_id: int, session: SessionDep) -> EntryOut:
    fill = session.get(JournalFill, fill_id)
    if fill is None:
        raise HTTPException(404, f"No fill {fill_id}")
    entry = _entry(session, fill.entry_id)
    try:
        service.delete_fill(session, fill)
    except JournalError as e:
        raise HTTPException(422, str(e)) from None
    return _one(session, entry)
