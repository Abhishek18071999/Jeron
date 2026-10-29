"""The journal in the database: decisions on signals, fills, positions and stats."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data import store
from app.data.adjust import SHARE_COUNT_ACTIONS, build_adjustments
from app.enums import Exchange
from app.journal.basis import ShareChange, basis_note, restate_fills, restate_price, share_changes
from app.journal.calc import (
    DECISIONS,
    Fill,
    JournalRow,
    Position,
    StrategyStats,
    position,
    strategy_stats,
)
from app.models import (
    DailyBar,
    Instrument,
    JournalEntry,
    JournalFill,
    PaperAccount,
    SignalRecord,
    TradePlan,
)


class JournalError(ValueError):
    """A request the journal refuses (unknown signal, selling more than held...)."""


IST = ZoneInfo("Asia/Kolkata")


def _today() -> date:
    return datetime.now(IST).date()


@dataclass(frozen=True)
class SignalInfo:
    signal_id: UUID
    ticker: str
    signal_date: date
    strategy_key: str
    research_only: bool
    payload: dict[str, Any]


@dataclass(frozen=True)
class EntryView:
    entry: JournalEntry
    fills: list[JournalFill]
    signal: SignalInfo | None
    stop: Decimal | None  # mine, else the signal's
    last_close: Decimal | None
    last_close_date: date | None
    # On the last close's share basis: fills before a split or bonus restated
    # (app/journal/basis.py), and so is the stop.
    position: Position
    basis_note: str | None = None


def _signal_infos(session: Session, ids: Sequence[UUID]) -> dict[UUID, SignalInfo]:
    if not ids:
        return {}
    rows = session.execute(
        select(SignalRecord, PaperAccount.strategy_key)
        .join(PaperAccount, PaperAccount.id == SignalRecord.account_id)
        .where(SignalRecord.signal_id.in_(list(ids)))
    )
    return {
        r.signal_id: SignalInfo(
            r.signal_id, r.ticker, r.signal_date, key, r.research_only, r.payload
        )
        for r, key in rows
    }


def signal_info(session: Session, signal_id: UUID) -> SignalInfo | None:
    return _signal_infos(session, [signal_id]).get(signal_id)


def last_closes(
    session: Session, tickers: Sequence[str], as_of: date | None = None
) -> dict[str, tuple[date, Decimal]]:
    """Each ticker's newest NSE close on or before `as_of`."""
    out: dict[str, tuple[date, Decimal]] = {}
    for ticker in sorted(set(tickers)):
        query = (
            select(DailyBar.trade_date, DailyBar.close)
            .join(Instrument, Instrument.id == DailyBar.instrument_id)
            .where(
                Instrument.exchange == Exchange.NSE,
                Instrument.symbol == ticker,
                DailyBar.source == store.NSE_BARS,
            )
            .order_by(DailyBar.trade_date.desc())
            .limit(1)
        )
        if as_of is not None:
            query = query.where(DailyBar.trade_date <= as_of)
        row = session.execute(query).first()
        if row is not None:
            out[ticker] = (row[0], row[1])
    return out


def _signal_stop(info: SignalInfo | None) -> Decimal | None:
    if info is None:
        return None
    return Decimal(str(info.payload["stop"]["price"]))


def share_changes_for(session: Session, tickers: Iterable[str]) -> dict[str, list[ShareChange]]:
    """Each ticker's splits and bonuses as the price adjustment applies them (revised
    ex-dates settled by the price move); tickers without any are left out."""
    out: dict[str, list[ShareChange]] = {}
    for ticker in sorted(set(tickers)):
        actions = [
            a.record
            for a in store.symbol_actions(session, ticker, store.NSE_ACTIONS)
            if a.record.action_type in SHARE_COUNT_ACTIONS
        ]
        if not actions:
            continue
        start = min(a.ex_date for a in actions) - timedelta(days=10)
        bars = store.symbol_bars(session, ticker, store.NSE_BARS, start)
        changes = share_changes(build_adjustments(bars, actions))
        if changes:
            out[ticker] = changes
    return out


def restated(
    fills: Iterable[JournalFill | Fill], changes: Sequence[ShareChange], basis: date
) -> list[Fill]:
    """Stored fills on `basis`'s share basis (app/journal/basis.py)."""
    return restate_fills(
        [Fill(f.trade_date, f.side, f.shares, f.price, f.charges) for f in fills], changes, basis
    )


def entry_fills(session: Session, entry: JournalEntry, extra: Sequence[Fill] = ()) -> list[Fill]:
    """One entry's fills (plus `extra`), restated to today's share basis."""
    stored = session.scalars(select(JournalFill).where(JournalFill.entry_id == entry.id)).all()
    changes = share_changes_for(session, [entry.ticker]).get(entry.ticker, [])
    return restated([*stored, *extra], changes, _today())


def entry_views(
    session: Session,
    entries: Sequence[JournalEntry] | None = None,
    as_of: date | None = None,
) -> list[EntryView]:
    if entries is None:
        entries = session.scalars(
            select(JournalEntry).order_by(JournalEntry.created_at.desc(), JournalEntry.id.desc())
        ).all()
    if not entries:
        return []
    fills: dict[int, list[JournalFill]] = {}
    for f in session.scalars(
        select(JournalFill)
        .where(JournalFill.entry_id.in_([e.id for e in entries]))
        .order_by(JournalFill.trade_date, JournalFill.id)
    ):
        fills.setdefault(f.entry_id, []).append(f)
    infos = _signal_infos(session, [e.signal_id for e in entries if e.signal_id])
    tickers = [e.ticker for e in entries]
    closes = last_closes(session, tickers, as_of)
    changes = share_changes_for(session, tickers)
    views = []
    for e in entries:
        info = infos.get(e.signal_id) if e.signal_id else None
        close = closes.get(e.ticker)
        own = fills.get(e.id, [])
        own_changes = changes.get(e.ticker, [])
        # Everything on the last close's basis: a split after it isn't priced in yet.
        basis = close[0] if close else (as_of or _today())
        first = min((f.trade_date for f in own), default=None)
        if e.stop is not None:
            stop = restate_price(e.stop, own_changes, e.stop_set_on or first or basis, basis)
        else:
            stop = restate_price(
                _signal_stop(info), own_changes, info.signal_date if info else basis, basis
            )
        pos = position(restated(own, own_changes, basis), stop, close[1] if close else None)
        views.append(
            EntryView(
                e,
                own,
                info,
                stop,
                close[1] if close else None,
                close[0] if close else None,
                pos,
                basis_note(own_changes, first, basis),
            )
        )
    return views


def pending_signals(
    session: Session, since: date | None = None, include_research: bool = True
) -> list[SignalInfo]:
    """Signals with no journal entry yet, newest first."""
    query = (
        select(SignalRecord.signal_id)
        .outerjoin(JournalEntry, JournalEntry.signal_id == SignalRecord.signal_id)
        .where(JournalEntry.id.is_(None))
        .order_by(SignalRecord.signal_date.desc(), SignalRecord.ticker)
    )
    if since is not None:
        query = query.where(SignalRecord.signal_date >= since)
    if not include_research:
        query = query.where(SignalRecord.research_only.is_(False))
    ids = list(session.scalars(query))
    infos = _signal_infos(session, ids)
    return [infos[i] for i in ids]


def _check_decision(decision: str) -> None:
    if decision not in DECISIONS:
        raise JournalError(f"Decision must be one of {', '.join(DECISIONS)}")


def _set_stop(entry: JournalEntry, stop: Decimal | None) -> None:
    """A changed stop is dated, so a later split restates it; an unchanged one keeps its
    date (a form sends the stop back with every save)."""
    if stop != entry.stop:
        entry.stop_set_on = None if stop is None else _today()
    entry.stop = stop


def _check_plan(session: Session, plan_id: int | None, ticker: str) -> None:
    """A journal entry may point at a saved trade plan for the same stock."""
    if plan_id is None:
        return
    plan = session.get(TradePlan, plan_id)
    if plan is None:
        raise JournalError(f"No trade plan {plan_id}")
    if plan.ticker != ticker:
        raise JournalError(f"Trade plan {plan_id} is for {plan.ticker}, not {ticker}")


def decide(
    session: Session,
    signal_id: UUID,
    decision: str,
    *,
    reason: str = "",
    stop: Decimal | None = None,
    followed_plan: bool | None = None,
    notes: str = "",
    plan_id: int | None = None,
) -> JournalEntry:
    """Record (or change) what I did with a signal."""
    _check_decision(decision)
    info = signal_info(session, signal_id)
    if info is None:
        raise JournalError(f"No signal {signal_id}")
    _check_plan(session, plan_id, info.ticker)
    entry = session.scalar(select(JournalEntry).where(JournalEntry.signal_id == signal_id))
    if entry is None:
        entry = JournalEntry(
            signal_id=signal_id, ticker=info.ticker, strategy_key=info.strategy_key
        )
        session.add(entry)
    entry.decision = decision
    entry.reason = reason
    _set_stop(entry, stop)
    entry.followed_plan = followed_plan
    entry.notes = notes
    if plan_id is not None:
        entry.plan_id = plan_id
    session.commit()
    return entry


def manual_entry(
    session: Session,
    ticker: str,
    *,
    reason: str = "",
    stop: Decimal | None = None,
    notes: str = "",
    plan_id: int | None = None,
) -> JournalEntry:
    """A trade I took without a signal."""
    ticker = ticker.strip().upper()
    if not ticker:
        raise JournalError("Ticker is required")
    _check_plan(session, plan_id, ticker)
    entry = JournalEntry(
        ticker=ticker,
        decision="taken",
        reason=reason,
        stop=stop,
        stop_set_on=None if stop is None else _today(),
        notes=notes,
        followed_plan=None,
        plan_id=plan_id,
    )
    session.add(entry)
    session.commit()
    return entry


def update_entry(
    session: Session,
    entry: JournalEntry,
    *,
    decision: str,
    reason: str,
    stop: Decimal | None,
    followed_plan: bool | None,
    notes: str,
    plan_id: int | None = None,
) -> JournalEntry:
    _check_decision(decision)
    _check_plan(session, plan_id, entry.ticker)
    entry.decision = decision
    entry.reason = reason
    _set_stop(entry, stop)
    entry.followed_plan = followed_plan
    entry.notes = notes
    if plan_id is not None:
        entry.plan_id = plan_id
    session.commit()
    return entry


def add_fill(
    session: Session,
    entry: JournalEntry,
    trade_date: date,
    side: str,
    shares: int,
    price: Decimal,
    charges: Decimal = Decimal(0),
    *,
    source: str = "manual",
    broker_trade_id: str | None = None,
    charges_estimated: bool = False,
) -> JournalFill:
    if side not in ("buy", "sell"):
        raise JournalError("Side must be buy or sell")
    if shares <= 0 or price <= 0 or charges < 0:
        raise JournalError("Shares and price must be positive, charges not negative")
    # Checked on today's share basis: after a split the broker sells the new count.
    fills = entry_fills(session, entry, [Fill(trade_date, side, shares, price, charges)])
    try:
        position(fills, None, None)
    except ValueError as e:
        raise JournalError(str(e)) from e
    if entry.decision == "skipped":
        entry.decision = "taken"
    fill = JournalFill(
        entry_id=entry.id,
        trade_date=trade_date,
        side=side,
        shares=shares,
        price=price,
        charges=charges,
        source=source,
        broker_trade_id=broker_trade_id,
        charges_estimated=charges_estimated,
    )
    session.add(fill)
    session.commit()
    return fill


def delete_fill(session: Session, fill: JournalFill) -> None:
    rest = session.scalars(
        select(JournalFill).where(JournalFill.entry_id == fill.entry_id, JournalFill.id != fill.id)
    ).all()
    entry = session.get(JournalEntry, fill.entry_id)
    ticker = entry.ticker if entry is not None else ""
    changes = share_changes_for(session, [ticker]).get(ticker, [])
    try:
        position(restated(rest, changes, _today()), None, None)
    except ValueError as e:
        raise JournalError(f"Delete the sells first: {e}") from e
    session.delete(fill)
    session.commit()


def stats(session: Session, views: Sequence[EntryView] | None = None) -> list[StrategyStats]:
    """Per strategy, counting pending signals too."""
    views = entry_views(session) if views is None else views
    rows = [
        JournalRow(
            v.entry.strategy_key,
            v.entry.decision,
            v.entry.followed_plan,
            v.position.status,
            v.position.r_multiple,
            v.position.realised_pnl if v.position.status == "closed" else None,
            (v.position.last_date - v.position.first_date).days
            if v.position.status == "closed" and v.position.first_date and v.position.last_date
            else None,
            has_signal=v.entry.signal_id is not None,
        )
        for v in views
    ]
    rows += [
        JournalRow(p.strategy_key, None, None, None, None, None, None)
        for p in pending_signals(session)
    ]
    return strategy_stats(rows)
