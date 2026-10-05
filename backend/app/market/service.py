"""The market mood from the database: the day's scan universe, each stock's 52-week
range and the index closes. See `app.market.mood` for the rule."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.job import REGIME_HISTORY_DAYS
from app.data import store
from app.data.adjust import adjust_bars, build_adjustments
from app.data.nse_lists import INDIA_VIX, NIFTY_50, NIFTY_500
from app.data.provider import CorporateActionRecord
from app.enums import CorporateActionType
from app.market.mood import HIGH_LOW_SESSIONS, Mood, StockMood, market_mood, regime_detail
from app.models import DailyBar, ScanResult, ScanRun
from app.scan.job import _session_dates
from app.scan.score import SCORE_VERSION

Range = tuple[float, float, float | None, float | None, int]


def latest_ok_scan(session: Session, day: date | None = None) -> ScanRun | None:
    """The day's completed scan, or the newest one when `day` is None."""
    query = select(ScanRun).where(ScanRun.score_version == SCORE_VERSION, ScanRun.status == "ok")
    if day is not None:
        query = query.where(ScanRun.trade_date == day)
    return session.scalar(query.order_by(ScanRun.trade_date.desc()).limit(1))


def _f(value: object) -> float | None:
    return None if value is None else float(str(value))


def _ranges(
    session: Session, ids: dict[str, int], window: list[date], day: date
) -> dict[str, Range]:
    """Per symbol: (day's high, day's low, highest high and lowest low of the window's
    earlier sessions, sessions in the window). Raw prices, except for stocks with a
    split, bonus or rights issue in the window, which are adjusted."""
    first = window[0]
    by_id = {v: k for k, v in ids.items()}
    rows = session.execute(
        select(
            DailyBar.instrument_id,
            func.max(DailyBar.high).filter(DailyBar.trade_date == day),
            func.min(DailyBar.low).filter(DailyBar.trade_date == day),
            func.max(DailyBar.high).filter(DailyBar.trade_date < day),
            func.min(DailyBar.low).filter(DailyBar.trade_date < day),
            func.count(),
        )
        .where(
            DailyBar.source == store.NSE_BARS,
            DailyBar.instrument_id.in_(list(ids.values())),
            DailyBar.trade_date.between(first, day),
        )
        .group_by(DailyBar.instrument_id)
    )
    out: dict[str, Range] = {}
    for instrument_id, high, low, prior_high, prior_low, count in rows:
        if high is None or low is None:
            continue
        out[by_id[instrument_id]] = (
            float(high),
            float(low),
            _f(prior_high),
            _f(prior_low),
            int(count),
        )
    actions: dict[str, list[CorporateActionRecord]] = defaultdict(list)
    for a in store.actions_between(session, store.NSE_ACTIONS, first, day, list(ids)):
        actions[a.symbol].append(a)
    for symbol, found in actions.items():
        if all(a.action_type == CorporateActionType.DIVIDEND for a in found):
            continue
        bars = store.symbol_bars(session, symbol, store.NSE_BARS, first, day)
        if not bars or bars[-1].trade_date != day:
            continue
        everything = [a.record for a in store.symbol_actions(session, symbol, store.NSE_ACTIONS)]
        adjusted = adjust_bars(bars, build_adjustments(bars, everything))
        earlier = adjusted[:-1]
        out[symbol] = (
            float(adjusted[-1].high),
            float(adjusted[-1].low),
            max(float(a.high) for a in earlier) if earlier else None,
            min(float(a.low) for a in earlier) if earlier else None,
            len(adjusted),
        )
    return out


def _closes(session: Session, name: str, start: date, day: date) -> dict[date, float]:
    return {d: float(v) for d, v in store.index_closes(session, name, start, day).items()}


# The last mood computed, by scan run: the Today page asks for it on every load.
_cache: dict[tuple[int, object], Mood] = {}


def mood_on(session: Session, day: date | None = None) -> Mood | None:
    """The mood on `day`'s scan (default: the newest completed scan); None without one."""
    run = latest_ok_scan(session, day)
    if run is None:
        return None
    key = (run.id, run.created_at)
    if key not in _cache:
        _cache.clear()
        _cache[key] = _mood(session, run)
    return _cache[key]


def _mood(session: Session, run: ScanRun) -> Mood:
    day = run.trade_date
    results = session.execute(
        select(
            ScanResult.symbol,
            ScanResult.instrument_id,
            ScanResult.sector,
            ScanResult.in_nifty500,
            ScanResult.close,
            ScanResult.indicators,
        ).where(ScanResult.run_id == run.id)
    ).all()
    ids = {r.symbol: r.instrument_id for r in results}
    window = _session_dates(session, day, HIGH_LOW_SESSIONS) or [day]
    ranges = _ranges(session, ids, window, day) if ids else {}
    stocks = []
    for r in results:
        ind = r.indicators or {}
        close = _f(ind.get("close")) or float(Decimal(r.close))
        missing: Range = (close, close, None, None, 0)
        high, low, prior_high, prior_low, count = ranges.get(r.symbol, missing)
        stocks.append(
            StockMood(
                symbol=r.symbol,
                sector=r.sector,
                in_nifty500=r.in_nifty500,
                close=close,
                ema200=_f(ind.get("ema200")),
                return_6m=_f(ind.get("return_6m")),
                high=high,
                low=low,
                prior_high=prior_high,
                prior_low=prior_low,
                sessions=count,
            )
        )
    start = day - timedelta(days=REGIME_HISTORY_DAYS)
    n500 = _closes(session, NIFTY_500, start, day)
    regime = (
        regime_detail(
            sorted(n500),
            n500,
            _closes(session, NIFTY_50, start, day),
            _closes(session, INDIA_VIX, start, day),
        )
        if n500
        else None
    )
    return market_mood(day, stocks, regime)
