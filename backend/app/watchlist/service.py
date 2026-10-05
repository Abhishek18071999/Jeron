"""The watchlist from the database: items with the latest close, the latest scan's
score and 52-week numbers, and the daily alert check."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data import store
from app.enums import Exchange
from app.models import Alert, DailyBar, Instrument, ScanResult, ScanRun, WatchlistItem
from app.scan.score import SCORE_VERSION
from app.watchlist.calc import DIRECTIONS, Hit, alert_key, is_hit, pct_to_alert


class WatchlistError(Exception):
    pass


@dataclass(frozen=True)
class WatchView:
    item: WatchlistItem
    name: str | None
    sector: str | None
    last_close: Decimal | None
    last_date: date | None
    day_high: Decimal | None
    day_low: Decimal | None
    change_pct: Decimal | None  # the latest session's change
    pct_to_alert: Decimal | None
    below_52w_high_pct: Decimal | None
    score: Decimal | None
    rank: int | None
    hit: bool  # the latest session reached the alert price
    alerted_on: date | None  # the session an alert for the current price was sent for


def _check(direction: str | None, price: Decimal | None) -> None:
    if (direction is None) != (price is None):
        raise WatchlistError("Give both an alert price and above/below, or neither")
    if direction is not None and direction not in DIRECTIONS:
        raise WatchlistError("Alert direction must be above or below")
    if price is not None and price <= 0:
        raise WatchlistError("Alert price must be above zero")


def add(
    session: Session,
    ticker: str,
    *,
    alert_price: Decimal | None = None,
    alert_direction: str | None = None,
    note: str = "",
) -> WatchlistItem:
    """Watch a stock; if it is already watched, update its alert and note."""
    ticker = ticker.strip().upper()
    _check(alert_direction, alert_price)
    known = session.scalar(
        select(Instrument.id).where(
            Instrument.exchange == Exchange.NSE, Instrument.symbol == ticker
        )
    )
    if known is None:
        raise WatchlistError(f"Unknown stock {ticker}")
    item = session.scalar(select(WatchlistItem).where(WatchlistItem.ticker == ticker))
    if item is None:
        item = WatchlistItem(ticker=ticker)
        session.add(item)
    item.alert_price = alert_price
    item.alert_direction = alert_direction
    item.note = note.strip()
    session.commit()
    return item


def remove(session: Session, ticker: str) -> bool:
    item = session.scalar(select(WatchlistItem).where(WatchlistItem.ticker == ticker.upper()))
    if item is None:
        return False
    session.delete(item)
    session.commit()
    return True


def _latest_bars(session: Session, tickers: list[str]) -> dict[str, list[DailyBar]]:
    """The last two NSE bars per ticker, latest first (a watchlist is short)."""
    out: dict[str, list[DailyBar]] = {}
    ids = store.existing_ids(session, tickers)
    for ticker, instrument_id in ids.items():
        out[ticker] = list(
            session.scalars(
                select(DailyBar)
                .where(DailyBar.instrument_id == instrument_id, DailyBar.source == store.NSE_BARS)
                .order_by(DailyBar.trade_date.desc())
                .limit(2)
            )
        )
    return out


def _f(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value)).quantize(Decimal("0.01"))


def items(session: Session) -> list[WatchView]:
    rows = list(session.scalars(select(WatchlistItem).order_by(WatchlistItem.ticker)))
    tickers = [r.ticker for r in rows]
    names = {
        s: (n, sec)
        for s, n, sec in session.execute(
            select(Instrument.symbol, Instrument.name, Instrument.sector).where(
                Instrument.exchange == Exchange.NSE, Instrument.symbol.in_(tickers)
            )
        )
    }
    bars = _latest_bars(session, tickers)
    # The newest completed scan (as `app.market.service.latest_ok_scan`, which imports
    # the alerts job, which imports this module).
    run = session.scalar(
        select(ScanRun)
        .where(ScanRun.score_version == SCORE_VERSION, ScanRun.status == "ok")
        .order_by(ScanRun.trade_date.desc())
        .limit(1)
    )
    scans = (
        {
            r.symbol: r
            for r in session.scalars(
                select(ScanResult).where(
                    ScanResult.run_id == run.id, ScanResult.symbol.in_(tickers)
                )
            )
        }
        if run is not None and tickers
        else {}
    )
    keys = {
        alert_key(r.id, r.alert_direction, r.alert_price): r.id
        for r in rows
        if r.alert_price is not None and r.alert_direction is not None
    }
    alerted = {
        keys[a.key]: a.trade_date
        for a in session.scalars(
            select(Alert).where(Alert.key.in_(list(keys)), Alert.status == "sent")
        )
    }
    out = []
    for r in rows:
        name, sector = names.get(r.ticker, (None, None))
        recent = bars.get(r.ticker, [])
        last = recent[0] if recent else None
        prev = recent[1] if len(recent) > 1 else None
        scan = scans.get(r.ticker)
        hit = (
            last is not None
            and r.alert_price is not None
            and r.alert_direction is not None
            and is_hit(r.alert_direction, r.alert_price, last.high, last.low)
        )
        out.append(
            WatchView(
                item=r,
                name=name,
                sector=sector,
                last_close=None if last is None else last.close,
                last_date=None if last is None else last.trade_date,
                day_high=None if last is None else last.high,
                day_low=None if last is None else last.low,
                change_pct=None
                if last is None or prev is None or not prev.close
                else ((last.close / prev.close - 1) * 100).quantize(Decimal("0.01")),
                pct_to_alert=None
                if last is None or r.alert_price is None
                else pct_to_alert(r.alert_price, last.close),
                below_52w_high_pct=None
                if scan is None
                else _f((scan.indicators or {}).get("below_52w_high_pct")),
                score=None if scan is None else scan.score,
                rank=None if scan is None else scan.rank,
                hit=hit,
                alerted_on=alerted.get(r.id),
            )
        )
    return out


def hits(session: Session, day: date) -> list[Hit]:
    """Watchlist items whose alert price the day's bar reached."""
    rows = list(
        session.scalars(
            select(WatchlistItem)
            .where(WatchlistItem.alert_price.is_not(None))
            .order_by(WatchlistItem.ticker)
        )
    )
    if not rows:
        return []
    bars = {
        b.symbol: b for b in store.day_bars(session, store.NSE_BARS, day, [r.ticker for r in rows])
    }
    out = []
    for r in rows:
        bar = bars.get(r.ticker)
        if bar is None or r.alert_price is None or r.alert_direction is None:
            continue
        if is_hit(r.alert_direction, r.alert_price, bar.high, bar.low):
            out.append(
                Hit(
                    r.id,
                    r.ticker,
                    r.alert_direction,
                    r.alert_price,
                    day,
                    bar.high,
                    bar.low,
                    bar.close,
                    r.note,
                )
            )
    return out
