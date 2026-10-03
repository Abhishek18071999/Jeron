"""Reading and writing market data in PostgreSQL."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.data.crosscheck import Neighbours
from app.data.nse_lists import (
    IndexClose,
    IndexConstituent,
    SecurityStatusRecord,
    SymbolChangeRecord,
)
from app.data.provider import Bar, CorporateActionRecord, InstrumentRecord
from app.enums import Exchange
from app.models import (
    CorporateAction,
    DailyBar,
    IndexBar,
    IndexMembership,
    Instrument,
    SecurityStatus,
    SourceFile,
    SurveillanceFlag,
    SymbolChange,
)

NSE_BARS = "nse_bhavcopy"
NSE_ACTIONS = "nse"
NSE_PR = "nse_pr"
NSE_INDICES = "nse_indices"
NSE_SEC_LIST = "nse_sec_list"
YAHOO = "yahoo"
ASM_IMPORT = "asm_import"
_CHUNK = 2000


def instrument_ids(
    session: Session, symbols: Iterable[str], details: dict[str, Bar] | None = None
) -> dict[str, int]:
    """Instrument ids by NSE symbol, creating instruments that don't exist yet."""
    wanted = set(symbols)
    if not wanted:
        return {}
    ids = _existing_ids(session, wanted)
    missing = sorted(wanted - ids.keys())
    for start in range(0, len(missing), _CHUNK):
        rows = []
        for symbol in missing[start : start + _CHUNK]:
            bar = (details or {}).get(symbol)
            rows.append(
                {
                    "exchange": Exchange.NSE,
                    "symbol": symbol,
                    "series": bar.series if bar else "EQ",
                    "isin": bar.isin if bar else None,
                }
            )
        stmt = pg_insert(Instrument).values(rows).on_conflict_do_nothing()
        session.execute(stmt)
    if missing:
        ids = _existing_ids(session, wanted)
    return ids


def existing_ids(session: Session, symbols: Iterable[str]) -> dict[str, int]:
    """Instrument ids by NSE symbol, for the symbols that exist."""
    wanted = set(symbols)
    return _existing_ids(session, wanted) if wanted else {}


def _existing_ids(session: Session, symbols: set[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    ordered = sorted(symbols)
    for start in range(0, len(ordered), _CHUNK):
        rows = session.execute(
            select(Instrument.symbol, Instrument.id).where(
                Instrument.exchange == Exchange.NSE,
                Instrument.symbol.in_(ordered[start : start + _CHUNK]),
            )
        )
        found.update({symbol: id_ for symbol, id_ in rows})
    return found


def refresh_instrument_details(session: Session, bars: Sequence[Bar]) -> None:
    """Record each stock's latest series and ISIN (call with the newest day's bars)."""
    latest = {b.symbol: b for b in bars}
    rows = session.execute(
        select(Instrument.id, Instrument.symbol, Instrument.series, Instrument.isin).where(
            Instrument.exchange == Exchange.NSE, Instrument.symbol.in_(list(latest))
        )
    )
    for id_, symbol, series, isin in rows:
        bar = latest[symbol]
        if bar.series != series or (bar.isin and bar.isin != isin):
            session.execute(
                update(Instrument)
                .where(Instrument.id == id_)
                .values(series=bar.series, isin=bar.isin or isin)
            )


def save_bars(session: Session, source: str, bars: Sequence[Bar]) -> int:
    ids = instrument_ids(session, (b.symbol for b in bars), {b.symbol: b for b in bars})
    rows = [
        {
            "instrument_id": ids[b.symbol],
            "trade_date": b.trade_date,
            "source": source,
            "series": b.series if source == NSE_BARS else None,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "prev_close": b.prev_close,
            "volume": b.volume,
            "turnover": b.turnover,
        }
        for b in bars
    ]
    for start in range(0, len(rows), _CHUNK):
        stmt = pg_insert(DailyBar).values(rows[start : start + _CHUNK])
        columns = ("series", "open", "high", "low", "close", "prev_close", "volume", "turnover")
        stmt = stmt.on_conflict_do_update(
            index_elements=["instrument_id", "trade_date", "source"],
            set_={c: stmt.excluded[c] for c in columns} | {"ingested_at": func.now()},
        )
        session.execute(stmt)
    return len(rows)


def save_actions(session: Session, source: str, actions: Sequence[CorporateActionRecord]) -> int:
    if not actions:
        return 0
    ids = instrument_ids(session, (a.symbol for a in actions))
    rows = [
        {
            "instrument_id": ids[a.symbol],
            "ex_date": a.ex_date,
            "action_type": a.action_type,
            "ratio_new": a.ratio_new,
            "ratio_old": a.ratio_old,
            "amount": a.amount,
            "source": source,
            "raw_text": (a.raw_text or "")[:500],
        }
        for a in actions
    ]
    stmt = (
        pg_insert(CorporateAction)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_corporate_actions_identity")
    )
    session.execute(stmt)
    return len(rows)


def record_source_file(
    session: Session,
    source: str,
    trade_date: date,
    status: str,
    *,
    url: str | None = None,
    sha256: str | None = None,
    rows: int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    values = {
        "source": source,
        "trade_date": trade_date,
        "status": status,
        "url": url,
        "sha256": sha256,
        "rows": rows,
        "details": details or {},
    }
    stmt = pg_insert(SourceFile).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["source", "trade_date"],
        set_={k: stmt.excluded[k] for k in ("status", "url", "sha256", "rows", "details")}
        | {"fetched_at": func.now()},
    )
    session.execute(stmt)


def source_file(session: Session, source: str, trade_date: date) -> SourceFile | None:
    return session.get(SourceFile, (source, trade_date))


def source_statuses(session: Session, source: str, start: date, end: date) -> dict[date, str]:
    rows = session.execute(
        select(SourceFile.trade_date, SourceFile.status).where(
            SourceFile.source == source, SourceFile.trade_date.between(start, end)
        )
    )
    return {d: s for d, s in rows}


def ok_dates(
    session: Session, source: str, start: date | None = None, end: date | None = None
) -> list[date]:
    stmt = select(SourceFile.trade_date).where(
        SourceFile.source == source, SourceFile.status == "ok"
    )
    if start:
        stmt = stmt.where(SourceFile.trade_date >= start)
    if end:
        stmt = stmt.where(SourceFile.trade_date <= end)
    return list(session.scalars(stmt.order_by(SourceFile.trade_date)))


def _to_bar(symbol: str, row: DailyBar) -> Bar:
    return Bar(
        symbol=symbol,
        trade_date=row.trade_date,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        volume=row.volume,
        prev_close=row.prev_close,
        turnover=row.turnover,
        series=row.series or "EQ",
    )


def symbol_bars(
    session: Session,
    symbol: str,
    source: str,
    start: date | None = None,
    end: date | None = None,
) -> list[Bar]:
    stmt = (
        select(DailyBar)
        .join(Instrument, Instrument.id == DailyBar.instrument_id)
        .where(
            Instrument.exchange == Exchange.NSE,
            Instrument.symbol == symbol,
            DailyBar.source == source,
        )
    )
    if start:
        stmt = stmt.where(DailyBar.trade_date >= start)
    if end:
        stmt = stmt.where(DailyBar.trade_date <= end)
    return [_to_bar(symbol, row) for row in session.scalars(stmt.order_by(DailyBar.trade_date))]


def day_bars(
    session: Session, source: str, trade_date: date, symbols: Iterable[str] | None = None
) -> list[Bar]:
    stmt = (
        select(Instrument.symbol, DailyBar)
        .join(Instrument, Instrument.id == DailyBar.instrument_id)
        .where(DailyBar.source == source, DailyBar.trade_date == trade_date)
    )
    if symbols is not None:
        stmt = stmt.where(Instrument.symbol.in_(list(symbols)))
    return [
        _to_bar(symbol, row) for symbol, row in session.execute(stmt.order_by(Instrument.symbol))
    ]


def recent_closes(
    session: Session, source: str, before: date, sessions: int
) -> dict[str, list[Decimal]]:
    """Each symbol's closes over the last `sessions` ingested days before `before`."""
    days = list(
        session.scalars(
            select(SourceFile.trade_date)
            .where(
                SourceFile.source == source,
                SourceFile.status == "ok",
                SourceFile.trade_date < before,
            )
            .order_by(SourceFile.trade_date.desc())
            .limit(sessions)
        )
    )
    if not days:
        return {}
    rows = session.execute(
        select(Instrument.symbol, DailyBar.close)
        .join(Instrument, Instrument.id == DailyBar.instrument_id)
        .where(DailyBar.source == source, DailyBar.trade_date.in_(days))
        .order_by(Instrument.symbol, DailyBar.trade_date)
    )
    closes: dict[str, list[Decimal]] = {}
    for symbol, close in rows:
        closes.setdefault(symbol, []).append(close)
    return closes


def close_ratios(
    session: Session, source: str, day: date, symbols: Iterable[str], sessions: int
) -> dict[str, Neighbours]:
    """`source` close / NSE close for `symbols` on up to `sessions` NSE trading days
    before and after `day` (the day itself excluded)."""
    wanted = list(symbols)
    if not wanted:
        return {}
    before = session.scalars(
        select(SourceFile.trade_date)
        .where(SourceFile.source == NSE_BARS, SourceFile.status == "ok")
        .where(SourceFile.trade_date < day)
        .order_by(SourceFile.trade_date.desc())
        .limit(sessions)
    ).all()
    after = session.scalars(
        select(SourceFile.trade_date)
        .where(SourceFile.source == NSE_BARS, SourceFile.status == "ok")
        .where(SourceFile.trade_date > day)
        .order_by(SourceFile.trade_date)
        .limit(sessions)
    ).all()
    days = [*before, *after]
    if not days:
        return {}
    nse = DailyBar.__table__.alias("nse")
    other = DailyBar.__table__.alias("other")
    rows = session.execute(
        select(Instrument.symbol, nse.c.trade_date, nse.c.close, other.c.close)
        .join(nse, nse.c.instrument_id == Instrument.id)
        .join(
            other,
            (other.c.instrument_id == nse.c.instrument_id)
            & (other.c.trade_date == nse.c.trade_date),
        )
        .where(
            nse.c.source == NSE_BARS,
            other.c.source == source,
            nse.c.trade_date.in_(days),
            Instrument.symbol.in_(wanted),
        )
    )
    split: dict[str, tuple[list[Decimal], list[Decimal]]] = {}
    for symbol, trade_date, nse_close, other_close in rows:
        if not nse_close:
            continue
        sides = split.setdefault(symbol, ([], []))
        sides[0 if trade_date < day else 1].append(other_close / nse_close)
    return {s: Neighbours(tuple(b), tuple(a)) for s, (b, a) in split.items()}


@dataclass(frozen=True)
class StoredAction:
    record: CorporateActionRecord
    source: str


def _to_action(symbol: str, row: CorporateAction) -> StoredAction:
    return StoredAction(
        CorporateActionRecord(
            symbol=symbol,
            ex_date=row.ex_date,
            action_type=row.action_type,
            ratio_new=row.ratio_new,
            ratio_old=row.ratio_old,
            amount=row.amount,
            raw_text=row.raw_text,
        ),
        row.source,
    )


def symbol_actions(session: Session, symbol: str, source: str | None = None) -> list[StoredAction]:
    stmt = (
        select(CorporateAction)
        .join(Instrument, Instrument.id == CorporateAction.instrument_id)
        .where(Instrument.exchange == Exchange.NSE, Instrument.symbol == symbol)
    )
    if source:
        stmt = stmt.where(CorporateAction.source == source)
    return [
        _to_action(symbol, row)
        for row in session.scalars(stmt.order_by(CorporateAction.ex_date, CorporateAction.id))
    ]


def actions_between(
    session: Session,
    source: str,
    start: date,
    end: date,
    symbols: Iterable[str] | None = None,
) -> list[CorporateActionRecord]:
    stmt = (
        select(Instrument.symbol, CorporateAction)
        .join(Instrument, Instrument.id == CorporateAction.instrument_id)
        .where(CorporateAction.source == source, CorporateAction.ex_date.between(start, end))
    )
    if symbols is not None:
        stmt = stmt.where(Instrument.symbol.in_(list(symbols)))
    return [_to_action(symbol, row).record for symbol, row in session.execute(stmt)]


def liquid_symbols(
    session: Session,
    as_of: date,
    min_median_turnover: Decimal = Decimal("50000000"),
    min_price: Decimal = Decimal("20"),
    lookback: int = 20,
) -> list[str]:
    """EQ-series stocks whose median daily turnover over the last `lookback` sessions
    is at least ₹5 crore and whose last close is at least ₹20 (the spec's liquidity
    floor). This is the set cross-checked against the second source."""
    days = list(
        session.scalars(
            select(SourceFile.trade_date)
            .where(
                SourceFile.source == NSE_BARS,
                SourceFile.status == "ok",
                SourceFile.trade_date <= as_of,
            )
            .order_by(SourceFile.trade_date.desc())
            .limit(lookback)
        )
    )
    if not days:
        return []
    last_close = func.max(DailyBar.close).filter(DailyBar.trade_date == days[0])
    stmt = (
        select(Instrument.symbol)
        .join(DailyBar, DailyBar.instrument_id == Instrument.id)
        .where(
            DailyBar.source == NSE_BARS,
            DailyBar.series == "EQ",
            DailyBar.trade_date.in_(days),
        )
        .group_by(Instrument.symbol)
        .having(
            func.percentile_cont(0.5).within_group(DailyBar.turnover) >= min_median_turnover,
            last_close >= min_price,
        )
        .order_by(Instrument.symbol)
    )
    return list(session.scalars(stmt))


def symbol_search(session: Session, query: str, limit: int = 20) -> list[tuple[str, str]]:
    pattern = f"{query.strip().upper()}%"
    rows = session.execute(
        select(Instrument.symbol, Instrument.series)
        .where(Instrument.exchange == Exchange.NSE, Instrument.symbol.like(pattern))
        .order_by(Instrument.symbol)
        .limit(limit)
    )
    return [(symbol, series) for symbol, series in rows]


def _like(text: str) -> str:
    """`text` with LIKE's wildcards escaped (backslash is the escape character)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def stock_search(
    session: Session, query: str, limit: int = 10
) -> list[tuple[str, str | None, str]]:
    """(symbol, company name, series) matching a symbol or a company name, best first:
    exact symbol, symbol prefix (spaces ignored, so "tata steel" finds TATASTEEL), name
    prefix, a word in the name starting with it, then anywhere."""
    words = " ".join(query.split())
    if not words:
        return []
    compact = _like(words.upper().replace(" ", ""))
    lowered = _like(words.lower())
    name = func.lower(Instrument.name)
    rank = case(
        (Instrument.symbol == words.upper().replace(" ", ""), 0),
        (Instrument.symbol.like(f"{compact}%", escape="\\"), 1),
        (name.like(f"{lowered}%", escape="\\"), 2),
        (name.like(f"% {lowered}%", escape="\\"), 3),
        else_=4,
    )
    rows = session.execute(
        select(Instrument.symbol, Instrument.name, Instrument.series)
        .where(
            Instrument.exchange == Exchange.NSE,
            or_(
                Instrument.symbol.like(f"%{compact}%", escape="\\"),
                name.like(f"%{lowered}%", escape="\\"),
            ),
        )
        .order_by(rank, Instrument.symbol)
        .limit(limit)
    )
    return [(symbol, company, series) for symbol, company, series in rows]


# --- Indices, security list, reference lists (M2) -------------------------------------


def save_index_closes(session: Session, closes: Sequence[IndexClose]) -> int:
    if not closes:
        return 0
    rows = [
        {
            "index_name": c.index_name,
            "trade_date": c.trade_date,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
        }
        for c in closes
    ]
    stmt = pg_insert(IndexBar).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["index_name", "trade_date"],
        set_={c: stmt.excluded[c] for c in ("open", "high", "low", "close")},
    )
    session.execute(stmt)
    return len(rows)


def index_closes(session: Session, index_name: str, start: date, end: date) -> dict[date, Decimal]:
    rows = session.execute(
        select(IndexBar.trade_date, IndexBar.close).where(
            IndexBar.index_name == index_name, IndexBar.trade_date.between(start, end)
        )
    )
    return {d: c for d, c in rows}


def save_security_status(
    session: Session, trade_date: date, records: Sequence[SecurityStatusRecord]
) -> int:
    if not records:
        return 0
    ids = instrument_ids(session, (r.symbol for r in records))
    rows = [
        {
            "instrument_id": ids[r.symbol],
            "trade_date": trade_date,
            "series": r.series,
            "price_band": r.price_band,
            "remarks": (r.remarks or "")[:200] or None,
            "gsm_stage": r.gsm_stage,
        }
        for r in {r.symbol: r for r in records}.values()
    ]
    for start in range(0, len(rows), _CHUNK):
        stmt = pg_insert(SecurityStatus).values(rows[start : start + _CHUNK])
        columns = ("series", "price_band", "remarks", "gsm_stage")
        stmt = stmt.on_conflict_do_update(
            index_elements=["instrument_id", "trade_date"],
            set_={c: stmt.excluded[c] for c in columns},
        )
        session.execute(stmt)
    return len(rows)


def gsm_symbols(
    session: Session, as_of: date, max_age_days: int = 7
) -> tuple[date, set[str]] | None:
    """Stocks on GSM in the newest security list on or before `as_of` (no older than
    `max_age_days`), with that list's date. None if there is no recent list."""
    listed = session.scalar(
        select(func.max(SourceFile.trade_date)).where(
            SourceFile.source == NSE_SEC_LIST,
            SourceFile.status == "ok",
            SourceFile.trade_date <= as_of,
            SourceFile.trade_date > as_of - timedelta(days=max_age_days),
        )
    )
    if listed is None:
        return None
    rows = session.scalars(
        select(Instrument.symbol)
        .join(SecurityStatus, SecurityStatus.instrument_id == Instrument.id)
        .where(SecurityStatus.trade_date == listed, SecurityStatus.gsm_stage.is_not(None))
    )
    return listed, set(rows)


def replace_surveillance(
    session: Session, measure: str, symbols: dict[str, str | None], as_of: date, source: str
) -> tuple[int, int]:
    """Make `symbols` (symbol -> stage) the stocks on `measure` from `as_of`: open a
    period for new ones and close the period of those no longer listed. Returns
    (added, removed). Earlier periods are kept, so the history stays point in time."""
    ids = instrument_ids(session, symbols)
    open_flags = {
        f.instrument_id: f
        for f in session.scalars(
            select(SurveillanceFlag).where(
                SurveillanceFlag.measure == measure, SurveillanceFlag.end_date.is_(None)
            )
        )
    }
    wanted = {ids[s]: stage for s, stage in symbols.items()}
    removed = 0
    for instrument_id, flag in open_flags.items():
        if instrument_id not in wanted:
            flag.end_date = as_of
            removed += 1
    added = 0
    for instrument_id, stage in wanted.items():
        if instrument_id not in open_flags:
            session.add(
                SurveillanceFlag(
                    instrument_id=instrument_id,
                    measure=measure,
                    stage=stage,
                    start_date=as_of,
                    source=source,
                )
            )
            added += 1
    session.flush()
    return added, removed


def surveillance_symbols(session: Session, measure: str, as_of: date) -> set[str]:
    rows = session.scalars(
        select(Instrument.symbol)
        .join(SurveillanceFlag, SurveillanceFlag.instrument_id == Instrument.id)
        .where(
            SurveillanceFlag.measure == measure,
            SurveillanceFlag.start_date <= as_of,
            (SurveillanceFlag.end_date.is_(None)) | (SurveillanceFlag.end_date > as_of),
        )
    )
    return set(rows)


def refresh_index_membership(
    session: Session, index_name: str, members: Sequence[IndexConstituent], as_of: date
) -> tuple[int, int]:
    """Record today's constituents: open a membership for new ones and end the
    membership of stocks that left. Returns (joined, left)."""
    ids = instrument_ids(session, (m.symbol for m in members))
    current = {
        m.instrument_id: m
        for m in session.scalars(
            select(IndexMembership).where(
                IndexMembership.index_name == index_name, IndexMembership.end_date.is_(None)
            )
        )
    }
    wanted = set(ids.values())
    left = 0
    for instrument_id, membership in current.items():
        if instrument_id not in wanted:
            membership.end_date = as_of
            left += 1
    joined = 0
    for instrument_id in wanted - current.keys():
        session.add(
            IndexMembership(index_name=index_name, instrument_id=instrument_id, start_date=as_of)
        )
        joined += 1
    for m in members:
        if m.industry:
            session.execute(
                update(Instrument).where(Instrument.id == ids[m.symbol]).values(sector=m.industry)
            )
    session.flush()
    return joined, left


def index_members(session: Session, index_name: str, as_of: date) -> set[str]:
    rows = session.scalars(
        select(Instrument.symbol)
        .join(IndexMembership, IndexMembership.instrument_id == Instrument.id)
        .where(
            IndexMembership.index_name == index_name,
            IndexMembership.start_date <= as_of,
            (IndexMembership.end_date.is_(None)) | (IndexMembership.end_date > as_of),
        )
    )
    return set(rows)


def update_instrument_names(session: Session, records: Sequence[InstrumentRecord]) -> int:
    """Fill in names and listing dates for instruments Jeron already has."""
    existing = _existing_ids(session, {r.symbol for r in records})
    updated = 0
    for r in records:
        if r.symbol in existing:
            session.execute(
                update(Instrument)
                .where(Instrument.id == existing[r.symbol])
                .values(name=r.name, listing_date=r.listing_date)
            )
            updated += 1
    return updated


def save_symbol_changes(session: Session, changes: Sequence[SymbolChangeRecord]) -> int:
    if not changes:
        return 0
    rows = [
        {
            "old_symbol": c.old_symbol[:32],
            "new_symbol": c.new_symbol[:32],
            "change_date": c.change_date,
            "company_name": (c.company_name or "")[:200] or None,
        }
        for c in changes
    ]
    for start in range(0, len(rows), _CHUNK):
        session.execute(
            pg_insert(SymbolChange).values(rows[start : start + _CHUNK]).on_conflict_do_nothing()
        )
    return len(rows)


def symbol_lineage(session: Session, symbols: Iterable[str]) -> dict[str, list[tuple[str, date]]]:
    """For each symbol, its earlier symbols and the date each stopped being used,
    newest first: {"ZYDUSLIFE": [("CADILAHC", 2022-03-07)]}."""
    renames: dict[str, list[tuple[str, date]]] = {}
    for old, new, when in session.execute(
        select(SymbolChange.old_symbol, SymbolChange.new_symbol, SymbolChange.change_date)
    ):
        renames.setdefault(new, []).append((old, when))
    lineage: dict[str, list[tuple[str, date]]] = {}
    for symbol in symbols:
        chain: list[tuple[str, date]] = []
        seen = {symbol}
        current, cutoff = symbol, date.max
        while True:
            earlier = [(o, d) for o, d in renames.get(current, []) if d <= cutoff and o not in seen]
            if not earlier:
                break
            old, when = max(earlier, key=lambda e: e[1])
            chain.append((old, when))
            seen.add(old)
            current, cutoff = old, when
        if chain:
            lineage[symbol] = chain
    return lineage
