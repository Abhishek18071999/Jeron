"""Import a Zerodha tradebook into the journal (spec section 8).

Each equity trade becomes one fill, stored with the broker's trade id, so importing the
same file (or an overlapping one) again adds nothing. Matching, in order:
- a buy goes to my open journal entry for that stock; else to the newest signal for the
  stock whose entry window covers the trade date (the entry is marked taken); else to a
  new entry without a signal;
- a sell goes to my open entry for that stock. A sell with nothing open (bought before
  the journal began) is reported, not guessed.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.journal.calc import Fill, position
from app.journal.service import JournalError, add_fill, decide, manual_entry
from app.journal.tradebook import BrokerTrade, estimate_charges, parse_tradebook
from app.models import Instrument, JournalEntry, JournalFill, PaperAccount, SignalRecord

IMPORT_REASON = "Imported from the Zerodha tradebook"


@dataclass
class ImportResult:
    added: int = 0
    already: int = 0
    to_signals: int = 0  # buys matched to a signal
    new_entries: int = 0  # entries created without a signal
    skipped: dict[str, int] = field(default_factory=dict)  # by segment (F&O...)
    problems: list[str] = field(default_factory=list)


def _symbols_by_isin(session: Session, trades: Sequence[BrokerTrade]) -> dict[str, str]:
    """BSE trades carry BSE symbols; the ISIN finds the NSE one."""
    isins = {t.isin for t in trades if t.isin}
    if not isins:
        return {}
    rows = session.execute(
        select(Instrument.isin, Instrument.symbol).where(Instrument.isin.in_(isins))
    )
    return {isin: symbol for isin, symbol in rows if isin}


def _held(session: Session, entry: JournalEntry) -> int:
    fills = session.scalars(select(JournalFill).where(JournalFill.entry_id == entry.id)).all()
    pos = position(
        [Fill(f.trade_date, f.side, f.shares, f.price, f.charges) for f in fills], None, None
    )
    return pos.held


def _open_entry(session: Session, ticker: str) -> JournalEntry | None:
    for entry in session.scalars(
        select(JournalEntry)
        .where(JournalEntry.ticker == ticker)
        .order_by(JournalEntry.created_at.desc(), JournalEntry.id.desc())
    ):
        if _held(session, entry) > 0:
            return entry
    return None


def _signal_for(session: Session, ticker: str, day: date) -> SignalRecord | None:
    """The newest signal for `ticker` whose entry window covers `day` and that has no
    fills yet; live signals before research-only ones."""
    rows = session.scalars(
        select(SignalRecord)
        .join(PaperAccount, PaperAccount.id == SignalRecord.account_id)
        .where(SignalRecord.ticker == ticker, SignalRecord.signal_date < day)
        .order_by(SignalRecord.research_only, SignalRecord.signal_date.desc())
    )
    for record in rows:
        valid_until = date.fromisoformat(record.payload["entry_zone"]["valid_until"])
        if day > valid_until:
            continue
        entry = session.scalar(
            select(JournalEntry).where(JournalEntry.signal_id == record.signal_id)
        )
        if entry is None or not session.scalar(
            select(JournalFill.id).where(JournalFill.entry_id == entry.id).limit(1)
        ):
            return record
    return None


def import_tradebook(session: Session, text: str) -> ImportResult:
    book = parse_tradebook(text)
    result = ImportResult(skipped=book.skipped, problems=list(book.problems))
    known = set(
        session.scalars(
            select(JournalFill.broker_trade_id).where(
                JournalFill.broker_trade_id.in_([t.key for t in book.trades])
            )
        )
    )
    charges = estimate_charges(book.trades)
    nse = _symbols_by_isin(session, book.trades)
    for t in book.trades:
        if t.key in known:
            result.already += 1
            continue
        ticker = nse.get(t.isin or "", t.symbol)
        entry = _open_entry(session, ticker)
        if t.side == "buy" and entry is None:
            record = _signal_for(session, ticker, t.trade_date)
            if record is not None:
                entry = session.scalar(
                    select(JournalEntry).where(JournalEntry.signal_id == record.signal_id)
                )
                if entry is None:  # an entry I already made keeps my stop and notes
                    entry = decide(session, record.signal_id, "taken", reason=IMPORT_REASON)
                result.to_signals += 1
            else:
                entry = manual_entry(session, ticker, reason=IMPORT_REASON)
                result.new_entries += 1
        if entry is None:
            result.problems.append(
                f"Sell of {t.shares} {ticker} on {t.trade_date:%d %b %Y} with nothing open in "
                "the journal (bought before the journal began?): not imported."
            )
            continue
        try:
            add_fill(
                session,
                entry,
                t.trade_date,
                t.side,
                t.shares,
                t.price,
                charges[t.key],
                source="tradebook",
                broker_trade_id=t.key,
                charges_estimated=True,
            )
        except JournalError as e:
            session.rollback()
            result.problems.append(
                f"{t.side.title()} of {t.shares} {ticker} on {t.trade_date}: {e}"
            )
            continue
        known.add(t.key)
        result.added += 1
    return result
