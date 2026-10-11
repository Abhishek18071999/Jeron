"""Who bought and sold a stock in size: bulk and block deals and insider trades, for the
stock page. Information only; nothing here feeds a signal (docs/decisions/0011)."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.data import store
from app.data.deals import InsiderTrade, Party, insider_totals, summarize_deals
from app.db import get_session

router = APIRouter(tags=["deals"])
SessionDep = Annotated[Session, Depends(get_session)]
LATEST = 25


class PartyOut(BaseModel):
    name: str
    bought_quantity: int
    sold_quantity: int
    bought_value: Decimal
    sold_value: Decimal
    net_value: Decimal
    deals: int
    days: int
    kinds: list[str]
    last_day: date | None


class DealOut(BaseModel):
    day: date
    kind: str
    client: str
    side: str
    quantity: int
    price: Decimal
    value: Decimal


class InsiderOut(BaseModel):
    disclosed: date
    person: str
    category: str
    side: str
    quantity: int
    value: Decimal | None
    mode: str
    on_market: bool
    traded_from: date | None
    traded_to: date | None
    before_pct: Decimal | None
    after_pct: Decimal | None


class InsiderTotalsOut(BaseModel):
    promoter_bought: Decimal
    promoter_sold: Decimal
    promoter_net: Decimal
    others_bought: Decimal
    others_sold: Decimal
    others_net: Decimal
    on_market: int
    other_modes: int


class CoverageOut(BaseModel):
    """Which days of the period Jeron holds data for, across all stocks."""

    first: date | None
    last: date | None
    days: int
    # Trading days from `first` to `last` (deals only): days < sessions means gaps.
    sessions: int | None


class StockDeals(BaseModel):
    symbol: str
    since: date
    buyers: list[PartyOut]
    sellers: list[PartyOut]
    day_traders: list[PartyOut]
    deals: list[DealOut]
    deal_count: int
    insider: list[InsiderOut]
    insider_count: int
    insider_totals: InsiderTotalsOut
    deals_coverage: CoverageOut
    insider_coverage: CoverageOut


def _party(p: Party) -> PartyOut:
    return PartyOut(
        name=p.name,
        bought_quantity=p.bought_quantity,
        sold_quantity=p.sold_quantity,
        bought_value=p.bought_value.quantize(Decimal("1")),
        sold_value=p.sold_value.quantize(Decimal("1")),
        net_value=p.net_value.quantize(Decimal("1")),
        deals=p.deals,
        days=len(p.days),
        kinds=sorted(p.kinds),
        last_day=p.last_day,
    )


def _insider(t: InsiderTrade) -> InsiderOut:
    return InsiderOut(
        disclosed=t.disclosed,
        person=t.person,
        category=t.category,
        side=t.side,
        quantity=t.quantity,
        value=t.value,
        mode=t.mode,
        on_market=t.on_market,
        traded_from=t.traded_from,
        traded_to=t.traded_to,
        before_pct=t.before_pct,
        after_pct=t.after_pct,
    )


@router.get("/stocks/{symbol}/deals")
def stock_deals(
    symbol: str,
    session: SessionDep,
    days: Annotated[int, Query(ge=30, le=3650)] = 365,
    day: Annotated[date | None, Query()] = None,
) -> StockDeals:
    """The biggest net buyers and sellers in bulk and block deals over the last `days`,
    firms that bought and sold the same day apart, and insiders' trades."""
    symbol = symbol.strip().upper()
    since = (day or date.today()) - timedelta(days=days)
    found = store.symbol_deals(session, symbol, since)
    insider = store.symbol_insider_trades(session, symbol, since)
    summary = summarize_deals(found)
    totals = insider_totals(insider)
    deals_cov = store.deals_coverage(session, since)
    sessions = (
        len(store.ok_dates(session, store.NSE_BARS, deals_cov.first, deals_cov.last))
        if deals_cov.first and deals_cov.last
        else None
    )
    insider_cov = store.insider_coverage(session, since)
    return StockDeals(
        symbol=symbol,
        since=since,
        buyers=[_party(p) for p in summary.buyers],
        sellers=[_party(p) for p in summary.sellers],
        day_traders=[_party(p) for p in summary.day_traders],
        deals=[
            DealOut(
                day=d.day,
                kind=d.kind,
                client=d.client,
                side=d.side,
                quantity=d.quantity,
                price=d.price,
                value=d.value.quantize(Decimal("1")),
            )
            for d in found[:LATEST]
        ],
        deal_count=len(found),
        insider=[_insider(t) for t in insider[:LATEST]],
        insider_count=len(insider),
        insider_totals=InsiderTotalsOut(
            promoter_bought=totals.promoter_bought,
            promoter_sold=totals.promoter_sold,
            promoter_net=totals.promoter_net,
            others_bought=totals.others_bought,
            others_sold=totals.others_sold,
            others_net=totals.others_net,
            on_market=totals.on_market,
            other_modes=totals.other_modes,
        ),
        deals_coverage=CoverageOut(
            first=deals_cov.first, last=deals_cov.last, days=deals_cov.days, sessions=sessions
        ),
        insider_coverage=CoverageOut(
            first=insider_cov.first, last=insider_cov.last, days=insider_cov.days, sessions=None
        ),
    )
