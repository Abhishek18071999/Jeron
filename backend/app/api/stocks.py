"""The latest scan's full ranked list for the Stocks page, by industry."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.enums import Exchange
from app.market.service import latest_ok_scan
from app.models import Instrument, ScanResult, WatchlistItem

router = APIRouter(tags=["stocks"])
SessionDep = Annotated[Session, Depends(get_session)]


class RankedStock(BaseModel):
    rank: int
    symbol: str
    name: str | None
    sector: str | None
    score: Decimal
    close: Decimal
    in_nifty500: bool
    return_6m: float | None
    rs_6m: float | None
    below_52w_high_pct: float | None
    watched: bool


class Ranked(BaseModel):
    trade_date: date | None
    sector: str | None
    sort: str
    total: int
    offset: int
    items: list[RankedStock]


def _f(value: Any) -> float | None:
    return None if value is None else float(value)


@router.get("/stocks/ranked")
def ranked(
    session: SessionDep,
    sector: str | None = None,
    sort: Literal["score", "rs", "return"] = "score",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> Ranked:
    """The newest completed scan's universe, best score first (or by 6-month relative
    strength / return), optionally one NSE industry only."""
    run = latest_ok_scan(session)
    if run is None:
        return Ranked(trade_date=None, sector=sector, sort=sort, total=0, offset=offset, items=[])
    query = select(ScanResult).where(ScanResult.run_id == run.id)
    if sector:
        query = query.where(ScanResult.sector == sector)
    rows = list(session.scalars(query.order_by(ScanResult.rank)))
    if sort != "score":
        key = "rs_6m" if sort == "rs" else "return_6m"

        def value(r: ScanResult) -> float:
            v = _f((r.indicators or {}).get(key))
            return -1e9 if v is None else v

        rows.sort(key=lambda r: (-value(r), r.rank))
    page = rows[offset : offset + limit]
    symbols = [r.symbol for r in page]
    names = dict(
        session.execute(
            select(Instrument.symbol, Instrument.name).where(
                Instrument.exchange == Exchange.NSE, Instrument.symbol.in_(symbols)
            )
        ).all()
    )
    watched = set(
        session.scalars(select(WatchlistItem.ticker).where(WatchlistItem.ticker.in_(symbols)))
    )
    items = []
    for r in page:
        ind = r.indicators or {}
        items.append(
            RankedStock(
                rank=r.rank,
                symbol=r.symbol,
                name=names.get(r.symbol),
                sector=r.sector,
                score=r.score,
                close=r.close,
                in_nifty500=r.in_nifty500,
                return_6m=_f(ind.get("return_6m")),
                rs_6m=_f(ind.get("rs_6m")),
                below_52w_high_pct=_f(ind.get("below_52w_high_pct")),
                watched=r.symbol in watched,
            )
        )
    return Ranked(
        trade_date=run.trade_date,
        sector=sector,
        sort=sort,
        total=len(rows),
        offset=offset,
        items=items,
    )
