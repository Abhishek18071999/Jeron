"""The dashboard, the stock page and the alert log (M5)."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.job import PENDING_DAYS, account_rows, day_signals, regime_on
from app.api.journal import EntryOut, SignalBrief, brief, entry_out
from app.backtest.market import REGIME_RULES, Regime
from app.config import get_settings
from app.data import store
from app.data.adjust import adjust_bars, build_adjustments
from app.db import get_session
from app.indicators import ema
from app.journal import service
from app.journal.service import SignalInfo
from app.models import (
    Alert,
    DataQualityReport,
    Instrument,
    JournalEntry,
    PaperAccount,
    PaperTrade,
    ScanResult,
    ScanRun,
    SignalRecord,
)
from app.paper.job import latest_scan_date
from app.scan.score import SCORE_VERSION

router = APIRouter(tags=["dashboard"])
SessionDep = Annotated[Session, Depends(get_session)]


class Quality(BaseModel):
    trade_date: date
    status: str
    reasons: list[str]


class ScanBrief(BaseModel):
    trade_date: date
    status: str
    universe_size: int
    reasons: list[str]
    top: list[dict[str, Any]]


class RegimeOut(BaseModel):
    regime: str
    rule: str
    risk_off: bool


class AccountBrief(BaseModel):
    id: int
    strategy_key: str
    stage: str
    equity: Decimal
    return_pct: Decimal
    open_positions: int
    heat_pct: Decimal
    drawdown_pct: Decimal


class PaperPosition(BaseModel):
    account_id: int
    strategy_key: str
    research_only: bool
    ticker: str
    entry_date: date
    entry_price: Decimal
    current_stop: Decimal | None
    last_close: Decimal | None
    shares_held: int
    r_multiple: Decimal
    net_pnl: Decimal


class AlertOut(BaseModel):
    id: int
    key: str
    kind: str
    trade_date: date | None
    signal_id: UUID | None
    status: str
    channel: str | None
    error: str | None
    attempts: int
    sent_at: datetime | None
    created_at: datetime
    text: str


class AlertsSetup(BaseModel):
    telegram: bool
    email: bool
    research_signals: bool


class Dashboard(BaseModel):
    as_of: date | None
    quality: Quality | None
    scan: ScanBrief | None
    regime: RegimeOut | None
    signals: list[SignalBrief]
    accounts: list[AccountBrief]
    paper_positions: list[PaperPosition]
    journal_positions: list[EntryOut]
    pending: list[SignalBrief]
    alerts: AlertsSetup
    last_summary: AlertOut | None


def _regime(session: Session, day: date) -> RegimeOut | None:
    found = regime_on(session, day)
    if found is None:
        return None
    regime, risk_off = found
    return RegimeOut(regime=regime, rule=REGIME_RULES[Regime(regime)], risk_off=risk_off)


def _alert(a: Alert) -> AlertOut:
    return AlertOut.model_validate(a, from_attributes=True)


def _scan(session: Session, day: date) -> ScanBrief | None:
    run = session.scalar(
        select(ScanRun).where(ScanRun.trade_date == day, ScanRun.score_version == SCORE_VERSION)
    )
    if run is None:
        return None
    top = session.scalars(
        select(ScanResult).where(ScanResult.run_id == run.id).order_by(ScanResult.rank).limit(10)
    )
    return ScanBrief(
        trade_date=run.trade_date,
        status=run.status,
        universe_size=run.universe_size,
        reasons=list(run.details.get("reasons", [])),
        top=[{"symbol": r.symbol, "score": r.score, "close": r.close} for r in top],
    )


@router.get("/dashboard")
def dashboard(session: SessionDep) -> Dashboard:
    settings = get_settings()
    report = session.scalar(
        select(DataQualityReport).order_by(DataQualityReport.trade_date.desc()).limit(1)
    )
    day = latest_scan_date(session)
    keys = {a.id: a for a in session.scalars(select(PaperAccount))}
    active = [a for a in keys.values() if a.status == "active"]
    paper_positions = [
        PaperPosition(
            account_id=t.account_id,
            strategy_key=keys[t.account_id].strategy_key,
            research_only=not keys[t.account_id].live_eligible,
            ticker=t.ticker,
            entry_date=t.entry_date,
            entry_price=t.entry_price,
            current_stop=t.current_stop,
            last_close=t.last_close,
            shares_held=t.shares_held,
            r_multiple=t.r_multiple,
            net_pnl=t.net_pnl,
        )
        for t in session.scalars(
            select(PaperTrade)
            .where(
                PaperTrade.status == "open",
                PaperTrade.account_id.in_([a.id for a in active]),
            )
            .order_by(PaperTrade.account_id, PaperTrade.entry_date, PaperTrade.ticker)
        )
    ]
    accounts = [
        AccountBrief(id=a.id, **row.__dict__)
        for a, row in zip(sorted(active, key=lambda a: a.id), account_rows(session), strict=True)
    ]
    signals: list[SignalBrief] = []
    if day is not None:
        signals = [
            brief(SignalInfo(r.signal_id, r.ticker, r.signal_date, key, r.research_only, r.payload))
            for r, key in day_signals(session, day)
        ]
    pending_since = (day or date.today()) - timedelta(days=PENDING_DAYS)
    last_summary = session.scalar(
        select(Alert).where(Alert.kind == "digest").order_by(Alert.created_at.desc()).limit(1)
    )
    return Dashboard(
        as_of=day,
        quality=None
        if report is None
        else Quality(
            trade_date=report.trade_date,
            status=report.status.value,
            reasons=list(report.details.get("reasons", [])),
        ),
        scan=None if day is None else _scan(session, day),
        regime=None if day is None else _regime(session, day),
        signals=signals,
        accounts=accounts,
        paper_positions=paper_positions,
        journal_positions=[
            entry_out(v) for v in service.entry_views(session) if v.position.status == "open"
        ],
        pending=[
            brief(p)
            for p in service.pending_signals(session, since=pending_since, include_research=False)
        ],
        alerts=AlertsSetup(
            telegram=settings.telegram_ready,
            email=settings.email_ready,
            research_signals=settings.alert_research_signals,
        ),
        last_summary=None if last_summary is None else _alert(last_summary),
    )


@router.get("/alerts")
def alerts(session: SessionDep, limit: Annotated[int, Query(ge=1, le=500)] = 50) -> list[AlertOut]:
    return [
        _alert(a)
        for a in session.scalars(select(Alert).order_by(Alert.created_at.desc()).limit(limit))
    ]


class Candle(BaseModel):
    time: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    factor: Decimal
    ema50: float | None
    ema200: float | None


class ScorePoint(BaseModel):
    trade_date: date
    score: Decimal
    rank: int


class StockSignal(BaseModel):
    signal: SignalBrief
    # The signal's levels on the chart's (adjusted) price basis.
    chart: dict[str, Decimal]
    payload: dict[str, Any]


class StockPaperTrade(BaseModel):
    account_id: int
    strategy_key: str
    status: str
    entry_date: date
    entry_price: Decimal
    exit_date: date | None
    exit_price: Decimal | None
    exit_reason: str | None
    r_multiple: Decimal


class StockView(BaseModel):
    symbol: str
    name: str | None
    series: str
    sector: str | None
    industry: str | None
    candles: list[Candle]
    scores: list[ScorePoint]
    latest_scan: dict[str, Any] | None
    signals: list[StockSignal]
    paper_trades: list[StockPaperTrade]
    journal: list[EntryOut]


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


class StockMatch(BaseModel):
    symbol: str
    name: str | None
    series: str
    # The short name or old symbol that matched ("RIL", "was ZOMATO"), if any.
    alias: str | None


@router.get("/stocks/search")
def stock_search(
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=64)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[StockMatch]:
    """Stocks whose symbol, company name, short name or old symbol matches what is
    typed, best first."""
    return [
        StockMatch(symbol=m.symbol, name=m.name, series=m.series, alias=m.alias)
        for m in store.stock_search(session, q, limit)
    ]


@router.get("/stocks/{symbol}")
def stock(
    symbol: str, session: SessionDep, sessions: Annotated[int, Query(ge=20, le=5000)] = 500
) -> StockView:
    """Split/bonus-adjusted candles (oldest first), score history, signals, paper trades
    and journal entries for one stock."""
    symbol = symbol.strip().upper()
    instrument = session.scalar(select(Instrument).where(Instrument.symbol == symbol))
    bars = store.symbol_bars(session, symbol, store.NSE_BARS)
    if instrument is None or not bars:
        raise HTTPException(404, f"No prices stored for {symbol}")
    actions = [
        a.record for a in store.symbol_actions(session, symbol) if a.source == store.NSE_ACTIONS
    ]
    adjusted = adjust_bars(bars, build_adjustments(bars, actions))
    closes = [float(a.close) for a in adjusted]
    ema50, ema200 = ema(closes, 50), ema(closes, 200)
    first = max(0, len(adjusted) - sessions)
    candles = [
        Candle(
            time=a.raw.trade_date,
            open=a.open,
            high=a.high,
            low=a.low,
            close=a.close,
            volume=a.volume,
            factor=a.factor,
            ema50=_r(ema50[i]),
            ema200=_r(ema200[i]),
        )
        for i, a in enumerate(adjusted)
        if i >= first
    ]
    factor_on = {a.raw.trade_date: a.factor for a in adjusted}

    rows = session.execute(
        select(ScanResult, ScanRun.trade_date)
        .join(ScanRun, ScanRun.id == ScanResult.run_id)
        .where(ScanResult.symbol == symbol, ScanRun.score_version == SCORE_VERSION)
        .order_by(ScanRun.trade_date)
    ).all()
    scores = [ScorePoint(trade_date=d, score=r.score, rank=r.rank) for r, d in rows]
    latest_scan = None
    if rows:
        r, d = rows[-1]
        latest_scan = {
            "trade_date": d,
            "score": r.score,
            "rank": r.rank,
            "in_nifty500": r.in_nifty500,
            "components": r.components,
            "indicators": r.indicators,
        }

    accounts = {a.id: a for a in session.scalars(select(PaperAccount))}
    signals = []
    for rec in session.scalars(
        select(SignalRecord)
        .where(SignalRecord.ticker == symbol)
        .order_by(SignalRecord.signal_date.desc(), SignalRecord.account_id)
    ):
        info = SignalInfo(
            rec.signal_id,
            rec.ticker,
            rec.signal_date,
            accounts[rec.account_id].strategy_key,
            rec.research_only,
            rec.payload,
        )
        b = brief(info)
        f = factor_on.get(rec.signal_date, Decimal(1))
        levels = {
            "entry_low": b.entry_low,
            "entry_high": b.entry_high,
            "stop": b.stop,
            "t1": b.t1,
            "t2": b.t2,
        }
        chart = {k: (v * f).quantize(Decimal("0.01")) for k, v in levels.items()}
        signals.append(StockSignal(signal=b, chart=chart, payload=rec.payload))

    trades = [
        StockPaperTrade(
            account_id=t.account_id,
            strategy_key=accounts[t.account_id].strategy_key,
            status=t.status,
            entry_date=t.entry_date,
            entry_price=t.entry_price,
            exit_date=t.exit_date,
            exit_price=t.exit_price,
            exit_reason=t.exit_reason,
            r_multiple=t.r_multiple,
        )
        for t in session.scalars(
            select(PaperTrade)
            .where(PaperTrade.ticker == symbol)
            .order_by(PaperTrade.entry_date.desc())
        )
    ]
    entries = session.scalars(
        select(JournalEntry)
        .where(JournalEntry.ticker == symbol)
        .order_by(JournalEntry.created_at.desc())
    ).all()
    return StockView(
        symbol=symbol,
        name=instrument.name,
        series=instrument.series,
        sector=instrument.sector,
        industry=instrument.industry,
        candles=candles,
        scores=scores,
        latest_scan=latest_scan,
        signals=signals,
        paper_trades=trades,
        journal=[entry_out(v) for v in service.entry_views(session, entries)],
    )
