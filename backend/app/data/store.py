"""Reading and writing market data in PostgreSQL."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Row, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.data.provider import Bar, CorporateActionRecord
from app.enums import Exchange
from app.models import CorporateAction, DailyBar, Instrument, SourceFile

NSE_BARS = "nse_bhavcopy"
NSE_ACTIONS = "nse"
NSE_PR = "nse_pr"
YAHOO = "yahoo"
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


def symbol_search(session: Session, query: str, limit: int = 20) -> list[Row[tuple[str, str]]]:
    pattern = f"{query.strip().upper()}%"
    return list(
        session.execute(
            select(Instrument.symbol, Instrument.series)
            .where(Instrument.exchange == Exchange.NSE, Instrument.symbol.like(pattern))
            .order_by(Instrument.symbol)
            .limit(limit)
        )
    )
