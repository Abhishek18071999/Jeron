"""The watchlist: stocks I am watching, with an optional alert price (decision 0010)."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_session
from app.watchlist import service
from app.watchlist.service import WatchlistError, WatchView

router = APIRouter(prefix="/watchlist", tags=["watchlist"])
SessionDep = Annotated[Session, Depends(get_session)]


class WatchOut(BaseModel):
    id: int
    ticker: str
    name: str | None
    sector: str | None
    alert_price: Decimal | None
    alert_direction: str | None
    note: str
    last_close: Decimal | None
    last_date: date | None
    day_high: Decimal | None
    day_low: Decimal | None
    change_pct: Decimal | None
    pct_to_alert: Decimal | None
    below_52w_high_pct: Decimal | None
    score: Decimal | None
    rank: int | None
    hit: bool
    alerted_on: date | None


class WatchlistOut(BaseModel):
    day: date | None  # the latest session with a close among the items
    items: list[WatchOut]
    hits: int


class WatchIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=32)
    alert_price: Decimal | None = Field(default=None, gt=0)
    alert_direction: Literal["above", "below"] | None = None
    note: str = Field(default="", max_length=500)


def _out(v: WatchView) -> WatchOut:
    i = v.item
    return WatchOut(
        id=i.id,
        ticker=i.ticker,
        name=v.name,
        sector=v.sector,
        alert_price=i.alert_price,
        alert_direction=i.alert_direction,
        note=i.note,
        last_close=v.last_close,
        last_date=v.last_date,
        day_high=v.day_high,
        day_low=v.day_low,
        change_pct=v.change_pct,
        pct_to_alert=v.pct_to_alert,
        below_52w_high_pct=v.below_52w_high_pct,
        score=v.score,
        rank=v.rank,
        hit=v.hit,
        alerted_on=v.alerted_on,
    )


def _view(session: Session) -> WatchlistOut:
    views = service.items(session)
    days = [v.last_date for v in views if v.last_date is not None]
    return WatchlistOut(
        day=max(days) if days else None,
        items=[_out(v) for v in views],
        hits=sum(1 for v in views if v.hit),
    )


@router.get("")
def watchlist(session: SessionDep) -> WatchlistOut:
    """Watched stocks, A to Z, with the latest close and how far each alert price is."""
    return _view(session)


@router.post("")
def watch(body: WatchIn, session: SessionDep) -> WatchlistOut:
    """Watch a stock, or change its alert price and note."""
    try:
        service.add(
            session,
            body.ticker,
            alert_price=body.alert_price,
            alert_direction=body.alert_direction,
            note=body.note,
        )
    except WatchlistError as e:
        raise HTTPException(422, str(e)) from None
    return _view(session)


@router.delete("/{ticker}")
def unwatch(ticker: str, session: SessionDep) -> WatchlistOut:
    if not service.remove(session, ticker):
        raise HTTPException(404, f"{ticker.upper()} is not on the watchlist")
    return _view(session)
