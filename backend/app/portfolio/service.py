"""The portfolio from the database: open journal positions with the pre-open check's
exit plan (`app.exits.job`), sectors and the section 5 limits from settings."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.engine import PortfolioRules
from app.calendar.nse import TradingCalendar
from app.config import Settings
from app.enums import Exchange
from app.exits.job import PositionCheck, PreOpen, build_preopen, check_day
from app.journal.service import EntryView, entry_views
from app.models import Instrument, JournalEntry, SignalRecord
from app.portfolio.calc import Holding, PortfolioTotals, totals
from app.settings_store import effective_settings
from app.signals.build import IST

RULES = PortfolioRules()


@dataclass(frozen=True)
class Portfolio:
    day: date  # the session the exit plans are for
    data_as_of: date | None
    expected: date  # the session whose close the plans need
    stale: bool
    holdings: list[Holding]
    totals: PortfolioTotals


def _price(value: float) -> Decimal:
    return Decimal(f"{value:.2f}")


def holding(check: PositionCheck, view: EntryView, sector: str | None) -> Holding:
    pos = view.position
    plan = check.plan
    pnl = None
    if pos.open_pnl is not None:
        pnl = pos.realised_pnl + pos.open_pnl
    avg_entry, last_close, stop = pos.avg_entry or Decimal(0), view.last_close, view.stop
    initial_stop, sessions, action, reason, notes = view.stop, None, None, None, []
    if plan is not None and check.last_close is not None:
        # The plan's prices are on today's basis (adjusted for any split since the buy).
        avg_entry, last_close = _price(plan.entry), _price(check.last_close)
        stop, initial_stop = _price(plan.stop), _price(plan.initial_stop)
        sessions, action, reason = plan.sessions, plan.action.value, plan.reason
        notes = list(plan.notes)
    return Holding(
        entry_id=view.entry.id,
        ticker=view.entry.ticker,
        strategy_key=view.entry.strategy_key,
        sector=sector,
        shares=pos.held,
        avg_entry=avg_entry,
        last_close=last_close,
        last_close_date=view.last_close_date,
        stop=stop,
        initial_stop=initial_stop,
        pnl=pnl,
        r_multiple=pos.r_multiple,
        first_date=pos.first_date or view.entry.created_at.date(),
        sessions_held=sessions,
        action=action,
        reason=reason,
        problem=check.problem,
        events=list(check.events),
        notes=notes,
    )


def pending_cost(session: Session, signal_day: date | None) -> Decimal:
    """What the live signals issued at `signal_day`'s close, with no journal entry yet,
    would cost at the top of their entry zones."""
    if signal_day is None:
        return Decimal(0)
    payloads: Iterable[dict[str, Any]] = session.scalars(
        select(SignalRecord.payload)
        .outerjoin(JournalEntry, JournalEntry.signal_id == SignalRecord.signal_id)
        .where(
            JournalEntry.id.is_(None),
            SignalRecord.signal_date == signal_day,
            SignalRecord.research_only.is_(False),
        )
    )
    return sum(
        (Decimal(str(p["entry_zone"]["high"])) * int(p["shares"]) for p in payloads), Decimal(0)
    )


def portfolio(
    session: Session,
    day: date | None = None,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
    pre: PreOpen | None = None,
) -> Portfolio:
    """Open positions as the next pre-open check (or `day`'s) sees them. `pre` reuses a
    pre-open check already built."""
    settings = settings or effective_settings(session)
    calendar = TradingCalendar.default()
    if pre is None:
        day = day or check_day(calendar, now or datetime.now(IST))
        pre = build_preopen(session, day, calendar)
    p = pre
    ids = [c.entry_id for c in p.positions]
    entries = session.scalars(select(JournalEntry).where(JournalEntry.id.in_(ids))).all()
    views = {v.entry.id: v for v in entry_views(session, entries, as_of=p.data_as_of)}
    sectors = dict(
        session.execute(
            select(Instrument.symbol, Instrument.sector).where(
                Instrument.exchange == Exchange.NSE,
                Instrument.symbol.in_([c.ticker for c in p.positions]),
            )
        ).all()
    )
    holdings = [holding(c, views[c.entry_id], sectors.get(c.ticker)) for c in p.positions]
    return Portfolio(
        day=p.day,
        data_as_of=p.data_as_of,
        expected=p.expected,
        stale=p.stale,
        holdings=holdings,
        totals=totals(
            holdings,
            Decimal(str(settings.capital)),
            Decimal(str(RULES.heat_warn_pct)),
            Decimal(str(RULES.heat_block_pct)),
            Decimal(str(settings.sector_cap_pct)),
            pending_cost(session, p.data_as_of),
        ),
    )
