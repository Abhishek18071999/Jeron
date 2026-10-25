"""The portfolio from the database: open journal positions with the pre-open check's
exit plan (`app.exits.job`), sectors and the section 5 limits from settings."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.costs import financial_year
from app.backtest.engine import PortfolioRules
from app.calendar.nse import TradingCalendar
from app.config import Settings
from app.data import store
from app.data.nse_lists import NIFTY_500
from app.enums import Exchange
from app.exits.job import PositionCheck, PreOpen, broker_stop, build_preopen, check_day
from app.journal.calc import Fill
from app.journal.service import EntryView, entry_views
from app.models import Instrument, JournalEntry, JournalFill, SignalRecord
from app.portfolio.calc import (
    AccountState,
    Holding,
    PortfolioTotals,
    Sale,
    account_state,
    realised_sales,
    totals,
)
from app.portfolio.equity import EquityCurve, equity_curve
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
    account: AccountState | None = None


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
    order, raised_from = broker_stop(check), None
    if plan is not None and check.last_close is not None:
        # The plan's prices are on today's basis (adjusted for any split since the buy).
        avg_entry, last_close = _price(plan.entry), _price(check.last_close)
        stop, initial_stop = _price(plan.stop), _price(plan.initial_stop)
        sessions, action, reason = plan.sessions, plan.action.value, plan.reason
        notes = list(plan.notes)
        if plan.stop_raised and plan.stop_before is not None:
            raised_from = _price(plan.stop_before)
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
        tier=check.tier.value,
        broker_shares=order[0] if order else None,
        stop_raised_from=raised_from,
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


def sales_this_year(session: Session, as_of: date) -> list[Sale]:
    """Every journal sale in `as_of`'s financial year, lots matched first in, first out
    within each journal entry."""
    start = date(financial_year(as_of), 4, 1)
    ids = session.scalars(
        select(JournalFill.entry_id).where(
            JournalFill.side == "sell", JournalFill.trade_date >= start
        )
    ).all()
    if not ids:
        return []
    fills: dict[tuple[int, str], list[Fill]] = {}
    for f, ticker in session.execute(
        select(JournalFill, JournalEntry.ticker)
        .join(JournalEntry, JournalEntry.id == JournalFill.entry_id)
        .where(JournalFill.entry_id.in_(set(ids)))
    ):
        fills.setdefault((f.entry_id, ticker), []).append(
            Fill(f.trade_date, f.side, f.shares, f.price, f.charges)
        )
    return [
        s
        for (_, ticker), own in fills.items()
        for s in realised_sales(ticker, own)
        if s.sell_date >= start
    ]


def journal_fills(session: Session) -> list[tuple[str, list[Fill]]]:
    """Every journal entry's (ticker, fills)."""
    fills: dict[tuple[int, str], list[Fill]] = {}
    for f, ticker in session.execute(
        select(JournalFill, JournalEntry.ticker).join(
            JournalEntry, JournalEntry.id == JournalFill.entry_id
        )
    ):
        fills.setdefault((f.entry_id, ticker), []).append(
            Fill(f.trade_date, f.side, f.shares, f.price, f.charges)
        )
    return [(ticker, own) for (_, ticker), own in fills.items()]


def journal_history(session: Session) -> tuple[list[Sale], list[date]]:
    """Every journal sale (lots first in, first out within each entry) and each entry's
    first buy date."""
    fills = journal_fills(session)
    sales = [s for ticker, own in fills for s in realised_sales(ticker, own)]
    first_buys = [
        min(f.trade_date for f in own if f.side == "buy")
        for _, own in fills
        if any(f.side == "buy" for f in own)
    ]
    return sales, first_buys


def equity_history(session: Session, capital: Decimal, until: date | None = None) -> EquityCurve:
    """The real account's equity each session from the first buy to `until` (default
    the newest session loaded), with the Nifty 500 beside it (`app.portfolio.equity`)."""
    positions = journal_fills(session)
    buys = [f.trade_date for _, own in positions for f in own if f.side == "buy"]
    if not buys:
        return equity_curve(capital, [], {}, [])
    start = min(buys)
    days = store.ok_dates(session, store.NSE_BARS, start, until)
    if not days:
        return equity_curve(capital, [], {}, [])
    end = days[-1]
    closes: dict[str, dict[date, Decimal]] = {}
    for ticker in {t for t, _ in positions}:
        # The close before the first buy too, so a stock is marked from day one.
        bars = store.symbol_bars(session, ticker, store.NSE_BARS, start - timedelta(days=10), end)
        closes[ticker] = {b.trade_date: b.close for b in bars}
    index = store.index_closes(session, NIFTY_500, start, end)
    return equity_curve(capital, positions, closes, days, index)


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
    as_of = p.data_as_of or p.expected
    capital = Decimal(str(settings.capital))
    sales, first_buys = journal_history(session)
    today = (now or datetime.now(IST)).astimezone(IST).date()
    curve = equity_history(session, capital, today)
    return Portfolio(
        day=p.day,
        data_as_of=p.data_as_of,
        expected=p.expected,
        stale=p.stale,
        holdings=holdings,
        totals=totals(
            holdings,
            capital,
            Decimal(str(RULES.heat_warn_pct)),
            Decimal(str(RULES.heat_block_pct)),
            Decimal(str(settings.sector_cap_pct)),
            pending_cost(session, p.data_as_of),
            settings.idle_cash_in_index,
            as_of,
            sales_this_year(session, as_of),
        ),
        account=account_state(capital, sales, first_buys, holdings, today, curve.peak),
    )
