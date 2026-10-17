"""Company announcements with their labels: a stock's on its page, the market's latest
on Today. The LLM label (the provider in `.env`) where there is one; otherwise the free
subject rule, worked out on read, so news shows even with the news brain off."""

from datetime import date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import Announcement
from app.models import NewsLabel as NewsLabelRow
from app.news.job import labeller_name, missing_key
from app.news.labels import PROMPT_VERSION, DatedLabel, EventType, news_score, rule_label
from app.signals.build import IST

router = APIRouter(tags=["news"])
SessionDep = Annotated[Session, Depends(get_session)]


class NewsItemOut(BaseModel):
    symbol: str
    day: date
    subject: str | None
    text: str
    event_type: str
    sentiment: int | None  # -2..+2 from the LLM; None: only the subject rule read it
    reason: str
    material: bool


class NewsOut(BaseModel):
    items: list[NewsItemOut]
    labeller: str
    labeller_ready: bool
    note: str | None  # why sentiment is missing, in plain words
    score: float | None = None  # the stock's news score today (50 = neutral)


def _items(session: Session, stmt: Select[Any], labeller: str) -> list[NewsItemOut]:
    rows = session.execute(stmt).all()
    ids = [r.id for r in rows]
    llm = {
        i: (t, s, why)
        for i, t, s, why in session.execute(
            select(
                NewsLabelRow.announcement_id,
                NewsLabelRow.event_type,
                NewsLabelRow.sentiment,
                NewsLabelRow.reason,
            ).where(
                NewsLabelRow.announcement_id.in_(ids),
                NewsLabelRow.labeller == labeller,
                NewsLabelRow.prompt_version == PROMPT_VERSION,
            )
        )
    }
    out = []
    for r in rows:
        kind, material = rule_label(r.subject, r.text)
        found = llm.get(r.id)
        out.append(
            NewsItemOut(
                symbol=r.symbol,
                day=r.day,
                subject=r.subject,
                text=r.text,
                event_type=found[0] if found else kind.value,
                sentiment=found[1] if found else None,
                reason=found[2] if found else ("" if material else "Routine filing."),
                material=material,
            )
        )
    return out


def _view(items: list[NewsItemOut], labeller: str) -> NewsOut:
    settings = get_settings()
    ready = settings.news_ready
    note = None
    if not ready:
        note = (
            missing_key(settings).split(":")[0]
            + ", so headlines show without good or bad labels. The Setup page says how to add one."
        )
    elif items and all(i.sentiment is None for i in items if i.material):
        note = "Not labelled yet: the news labeller reads new announcements after each daily run."
    return NewsOut(items=items, labeller=labeller, labeller_ready=ready, note=note)


@router.get("/stocks/{symbol}/news")
def stock_news(
    symbol: str, session: SessionDep, limit: Annotated[int, Query(ge=1, le=200)] = 40
) -> NewsOut:
    labeller = labeller_name(get_settings())
    stmt = (
        select(*Announcement.__table__.c)
        .where(Announcement.symbol == symbol.upper())
        .order_by(Announcement.day.desc(), Announcement.id.desc())
        .limit(limit)
    )
    items = _items(session, stmt, labeller)
    view = _view(items, labeller)
    today = datetime.now(IST).date()
    dated = [
        DatedLabel(i.day, EventType(i.event_type), i.sentiment)
        for i in items
        if i.sentiment is not None
    ]
    view.score = round(news_score(dated, today), 1) if dated else None
    return view


@router.get("/news/latest")
def latest_news(
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=60)] = 7,
    limit: Annotated[int, Query(ge=1, le=200)] = 30,
) -> NewsOut:
    """The latest material announcements: those the LLM scored good or bad first, then
    the ones the subject rules call material."""
    labeller = labeller_name(get_settings())
    since = datetime.now(IST).date() - timedelta(days=days)
    stmt = (
        select(*Announcement.__table__.c)
        .where(Announcement.day >= since)
        .order_by(Announcement.day.desc(), Announcement.id.desc())
        .limit(5000)
    )
    items = [i for i in _items(session, stmt, labeller) if i.material]
    items.sort(key=lambda i: (i.sentiment is None or i.sentiment == 0, -i.day.toordinal()))
    return _view(items[:limit], labeller)
