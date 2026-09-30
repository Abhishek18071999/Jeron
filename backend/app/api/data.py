"""Data status, quality reports and the spot-check view."""

import random
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.data import store
from app.data.adjust import adjust_bars, build_adjustments, price_confirms, price_factor
from app.data.crosscheck import ACTION_DATE_TOLERANCE_DAYS, CLOSE_TOLERANCE_PCT
from app.db import get_session
from app.enums import CorporateActionType, QualityStatus
from app.indicators import atr, ema, rsi
from app.models import CorporateAction, DailyBar, DataQualityReport, Instrument, SourceFile

router = APIRouter(prefix="/data", tags=["data"])
SessionDep = Annotated[Session, Depends(get_session)]


class Coverage(BaseModel):
    source: str
    first_date: date | None
    last_date: date | None
    days: int


class QualitySummary(BaseModel):
    trade_date: date
    status: QualityStatus
    reasons: list[str]


class DataStatus(BaseModel):
    coverage: list[Coverage]
    instruments: int
    corporate_actions: int
    latest_quality: QualitySummary | None
    # False when the latest trading day's data failed its checks: the scan must not run.
    scan_allowed: bool


def _summary(report: DataQualityReport) -> QualitySummary:
    return QualitySummary(
        trade_date=report.trade_date,
        status=report.status,
        reasons=list(report.details.get("reasons", [])),
    )


def latest_report(session: Session) -> DataQualityReport | None:
    return session.scalar(
        select(DataQualityReport).order_by(DataQualityReport.trade_date.desc()).limit(1)
    )


@router.get("/status")
def data_status(session: SessionDep) -> DataStatus:
    coverage = []
    for source in (store.NSE_BARS, store.NSE_PR, store.YAHOO):
        first, last, days = session.execute(
            select(
                func.min(SourceFile.trade_date),
                func.max(SourceFile.trade_date),
                func.count(),
            ).where(SourceFile.source == source, SourceFile.status == "ok")
        ).one()
        coverage.append(Coverage(source=source, first_date=first, last_date=last, days=days))
    latest = latest_report(session)
    return DataStatus(
        coverage=coverage,
        instruments=session.scalar(select(func.count()).select_from(Instrument)) or 0,
        corporate_actions=session.scalar(select(func.count()).select_from(CorporateAction)) or 0,
        latest_quality=_summary(latest) if latest else None,
        scan_allowed=latest is not None and latest.status != QualityStatus.FAIL,
    )


@router.get("/quality")
def quality_reports(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=500)] = 60
) -> list[QualitySummary]:
    reports = session.scalars(
        select(DataQualityReport).order_by(DataQualityReport.trade_date.desc()).limit(limit)
    )
    return [_summary(r) for r in reports]


@router.get("/quality/{trade_date}")
def quality_report(trade_date: date, session: SessionDep) -> dict[str, Any]:
    report = session.scalar(
        select(DataQualityReport).where(DataQualityReport.trade_date == trade_date)
    )
    if report is None:
        raise HTTPException(404, f"No quality report for {trade_date}")
    return report.details


class SymbolMatch(BaseModel):
    symbol: str
    series: str


@router.get("/symbols")
def symbols(
    session: SessionDep, q: Annotated[str, Query(min_length=1, max_length=32)]
) -> list[SymbolMatch]:
    return [SymbolMatch(symbol=s, series=series) for s, series in store.symbol_search(session, q)]


class Prices(BaseModel):
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class SpotRow(BaseModel):
    trade_date: date
    series: str
    raw: Prices
    prev_close: Decimal | None
    second_source_close: Decimal | None
    diff_pct: Decimal | None
    close_mismatch: bool
    factor: Decimal
    adjusted: Prices
    ema20: float | None
    ema50: float | None
    ema200: float | None
    rsi14: float | None
    atr14: float | None


class AdjustmentLogEntry(BaseModel):
    ex_date: date
    action_type: CorporateActionType
    description: str
    source: str
    factor: Decimal | None
    applied: bool
    # For splits and bonuses: does the ex-date's opening price gap match the ratio?
    price_confirms: bool | None
    confirmed_by_second_source: bool | None


class SpotCheck(BaseModel):
    symbol: str
    requested_date: date
    include_dividends: bool
    rows: list[SpotRow]
    adjustments: list[AdjustmentLogEntry]
    notes: list[str]


def _round(value: float | None, places: int = 2) -> float | None:
    return None if value is None else round(value, places)


@router.get("/spot-check")
def spot_check(
    session: SessionDep,
    symbol: Annotated[str, Query(min_length=1, max_length=32)],
    trade_date: Annotated[date, Query(alias="date")],
    window: Annotated[int, Query(ge=1, le=30)] = 5,
    dividends: bool = False,
) -> SpotCheck:
    """Raw and adjusted prices, the second source and indicators around one date."""
    symbol = symbol.strip().upper()
    bars = store.symbol_bars(session, symbol, store.NSE_BARS)
    if not bars:
        raise HTTPException(404, f"No prices stored for {symbol}")
    all_actions = store.symbol_actions(session, symbol)
    nse_actions = [a.record for a in all_actions if a.source == store.NSE_ACTIONS]
    second_actions = [a.record for a in all_actions if a.source == store.YAHOO]
    adjustments = build_adjustments(bars, nse_actions, include_dividends=dividends)
    adjusted = adjust_bars(bars, adjustments)

    closes = [float(a.close) for a in adjusted]
    highs = [float(a.high) for a in adjusted]
    lows = [float(a.low) for a in adjusted]
    ema20, ema50, ema200 = ema(closes, 20), ema(closes, 50), ema(closes, 200)
    rsi14, atr14 = rsi(closes), atr(highs, lows, closes)

    # Rows: `window` sessions either side of the requested date (or the nearest one).
    index = next((i for i, b in enumerate(bars) if b.trade_date >= trade_date), len(bars) - 1)
    lo, hi = max(0, index - window), min(len(bars), index + window + 1)
    yahoo = {
        b.trade_date: b.close
        for b in store.symbol_bars(
            session, symbol, store.YAHOO, bars[lo].trade_date, bars[hi - 1].trade_date
        )
    }
    rows = []
    for i in range(lo, hi):
        bar, adj = bars[i], adjusted[i]
        second = yahoo.get(bar.trade_date)
        diff = (
            (abs(second - bar.close) / bar.close * 100).quantize(Decimal("0.01"))
            if second
            else None
        )
        rows.append(
            SpotRow(
                trade_date=bar.trade_date,
                series=bar.series,
                raw=Prices(
                    open=bar.open, high=bar.high, low=bar.low, close=bar.close, volume=bar.volume
                ),
                prev_close=bar.prev_close,
                second_source_close=second,
                diff_pct=diff,
                close_mismatch=diff is not None and diff > CLOSE_TOLERANCE_PCT,
                factor=adj.factor,
                adjusted=Prices(
                    open=adj.open, high=adj.high, low=adj.low, close=adj.close, volume=adj.volume
                ),
                ema20=_round(ema20[i]),
                ema50=_round(ema50[i]),
                ema200=_round(ema200[i]),
                rsi14=_round(rsi14[i]),
                atr14=_round(atr14[i]),
            )
        )

    applied = {(a.action.ex_date, a.action.raw_text) for a in adjustments}
    log = []
    for stored in all_actions:
        action = stored.record
        confirmed = None
        factor = price_factor(action)
        if stored.source == store.NSE_ACTIONS and action.action_type in (
            CorporateActionType.SPLIT,
            CorporateActionType.BONUS,
        ):
            confirmed = any(
                abs((s.ex_date - action.ex_date).days) <= ACTION_DATE_TOLERANCE_DAYS
                for s in second_actions
                if s.action_type == CorporateActionType.SPLIT
            )
        log.append(
            AdjustmentLogEntry(
                ex_date=action.ex_date,
                action_type=action.action_type,
                description=action.raw_text or action.action_type.value,
                source=stored.source,
                factor=factor,
                applied=stored.source == store.NSE_ACTIONS
                and (action.ex_date, action.raw_text) in applied,
                price_confirms=price_confirms(bars, action.ex_date, factor) if factor else None,
                confirmed_by_second_source=confirmed,
            )
        )

    notes = []
    if bars[index].trade_date != trade_date:
        notes.append(f"No trading on {trade_date}; showing the nearest trading day.")
    if not yahoo:
        notes.append("The second source has no prices for these dates.")
    if any(
        a.action_type in (CorporateActionType.RIGHTS, CorporateActionType.OTHER)
        for a in nse_actions
    ):
        notes.append("This stock has a rights issue or scheme that is logged but not adjusted.")
    return SpotCheck(
        symbol=symbol,
        requested_date=trade_date,
        include_dividends=dividends,
        rows=rows,
        adjustments=log,
        notes=notes,
    )


class SamplePick(BaseModel):
    symbol: str
    trade_date: date
    reason: str


@router.get("/spot-check/sample")
def spot_check_sample(
    session: SessionDep,
    n: Annotated[int, Query(ge=1, le=100)] = 20,
    seed: int | None = None,
) -> list[SamplePick]:
    """Random stock-dates to compare against a broker's chart. About a quarter are
    split or bonus ex-dates, where adjustment mistakes would show."""
    rng = random.Random(seed)
    days = store.ok_dates(session, store.NSE_BARS)
    if not days:
        return []
    liquid = store.liquid_symbols(session, days[-1])
    picks: list[SamplePick] = []
    events = list(
        session.execute(
            select(Instrument.symbol, CorporateAction.ex_date, CorporateAction.raw_text)
            .join(Instrument, Instrument.id == CorporateAction.instrument_id)
            .where(
                CorporateAction.source == store.NSE_ACTIONS,
                CorporateAction.action_type.in_(
                    [CorporateActionType.SPLIT, CorporateActionType.BONUS]
                ),
                CorporateAction.ex_date <= days[-1],
            )
        )
    )
    for symbol, ex_date, text in rng.sample(events, min(len(events), n // 4)):
        picks.append(SamplePick(symbol=symbol, trade_date=ex_date, reason=f"ex-date: {text}"))
    candidates = liquid or list(
        session.scalars(
            select(Instrument.symbol)
            .join(DailyBar, DailyBar.instrument_id == Instrument.id)
            .where(DailyBar.trade_date == days[-1], DailyBar.source == store.NSE_BARS)
        )
    )
    while len(picks) < n and candidates:
        picks.append(
            SamplePick(symbol=rng.choice(candidates), trade_date=rng.choice(days), reason="random")
        )
    return sorted(picks, key=lambda p: (p.trade_date, p.symbol))
