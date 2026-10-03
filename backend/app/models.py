"""Database schema.

Design rules (see docs/spec.md, section 2):
- Prices are stored raw, one row per source, so two sources can be cross-checked.
  Adjusted series are derived from raw prices plus corporate_actions, never stored
  in place of raw data.
- Everything that changes over time is point-in-time: index membership has start/end
  dates, instruments keep their delisting date, fundamentals (later) are keyed by
  announcement date.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.enums import CorporateActionType, Exchange, QualityStatus

Price = Numeric(14, 4)


def pg_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """Store enum values ("split"), not member names ("SPLIT")."""
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("exchange", "symbol"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    exchange: Mapped[Exchange] = mapped_column(pg_enum(Exchange, "exchange"))
    symbol: Mapped[str] = mapped_column(String(32))
    # Latest series seen (EQ, BE, BZ). A stock keeps one instrument when it moves
    # between series; each bar records the series it traded in that day.
    series: Mapped[str] = mapped_column(String(4), default="EQ")
    isin: Mapped[str | None] = mapped_column(String(12), index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    listing_date: Mapped[date | None] = mapped_column(Date)
    delisting_date: Mapped[date | None] = mapped_column(Date)


class DailyBar(Base):
    """One day of raw (unadjusted) OHLCV for one instrument from one source."""

    __tablename__ = "daily_bars"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    series: Mapped[str | None] = mapped_column(String(4))
    open: Mapped[Decimal] = mapped_column(Price)
    high: Mapped[Decimal] = mapped_column(Price)
    low: Mapped[Decimal] = mapped_column(Price)
    close: Mapped[Decimal] = mapped_column(Price)
    prev_close: Mapped[Decimal | None] = mapped_column(Price)
    volume: Mapped[int] = mapped_column(BigInteger)
    turnover: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


Index("ix_daily_bars_trade_date", DailyBar.trade_date)


class CorporateAction(Base):
    """A corporate action as one source reported it. The same action from NSE and
    from the cross-check source is stored twice, once per source."""

    __tablename__ = "corporate_actions"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "source",
            "ex_date",
            "action_type",
            "raw_text",
            name="uq_corporate_actions_identity",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    ex_date: Mapped[date] = mapped_column(Date, index=True)
    action_type: Mapped[CorporateActionType] = mapped_column(
        pg_enum(CorporateActionType, "corporate_action_type")
    )
    # For splits and bonuses: shares after / shares before (e.g. 1:1 bonus = 2/1).
    ratio_new: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    ratio_old: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    # Cash amount per share for dividends.
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    source: Mapped[str] = mapped_column(String(32))
    raw_text: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IndexMembership(Base):
    """Point-in-time index constituents. end_date is null while still a member."""

    __tablename__ = "index_memberships"
    __table_args__ = (
        UniqueConstraint(
            "index_name", "instrument_id", "start_date", name="uq_index_memberships_period"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    index_name: Mapped[str] = mapped_column(String(64), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)


class SourceFile(Base):
    """What happened when a source's data for one day was fetched.

    status: "ok", "not_published" (the source has no file: a holiday),
    "not_fetched" (the download failed; retried on the next run) or "unreadable"
    (downloaded but the parser could not read it; re-read on the next run).
    """

    __tablename__ = "source_files"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    url: Mapped[str | None] = mapped_column(String(300))
    sha256: Mapped[str | None] = mapped_column(String(64))
    rows: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DataQualityReport(Base):
    """One report per trading day; re-running the checks replaces it."""

    __tablename__ = "data_quality_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True, unique=True)
    status: Mapped[QualityStatus] = mapped_column(pg_enum(QualityStatus, "quality_status"))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IndexBar(Base):
    """One day of an index (Nifty 500, Nifty 50, India VIX, ...) as NSE published it."""

    __tablename__ = "index_bars"

    index_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal | None] = mapped_column(Price)
    high: Mapped[Decimal | None] = mapped_column(Price)
    low: Mapped[Decimal | None] = mapped_column(Price)
    close: Mapped[Decimal] = mapped_column(Price)


class SecurityStatus(Base):
    """A stock's price band and surveillance stage on one day, from NSE's security
    list. Kept per day (point in time); never overwritten by later days."""

    __tablename__ = "security_status"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    series: Mapped[str] = mapped_column(String(4))
    # Percent band (2, 5, 10, 20); null for "No Band" (stocks with F&O).
    price_band: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    remarks: Mapped[str | None] = mapped_column(String(200))
    gsm_stage: Mapped[str | None] = mapped_column(String(32))


class SurveillanceFlag(Base):
    """A period during which a stock was on a surveillance list (ASM). end_date is
    null while it still is."""

    __tablename__ = "surveillance_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    measure: Mapped[str] = mapped_column(String(16))
    stage: Mapped[str | None] = mapped_column(String(64))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32))


class BoardMeeting(Base):
    """A board meeting NSE announced (results, dividend, fund raising...). Rows are
    added, never changed: `announced_at` is when NSE published it and `first_seen` when
    Jeron first stored it, so a backtest only knows a date from the day it was public."""

    __tablename__ = "board_meetings"
    __table_args__ = (UniqueConstraint("symbol", "meeting_date", "purpose"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    meeting_date: Mapped[date] = mapped_column(Date, index=True)
    purpose: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(String(2000), default="")
    is_results: Mapped[bool] = mapped_column(Boolean, default=False)
    announced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str] = mapped_column(String(32))


class SymbolChange(Base):
    """NSE symbol renames, used to join a company's history across its symbols."""

    __tablename__ = "symbol_changes"
    __table_args__ = (UniqueConstraint("old_symbol", "new_symbol", "change_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    old_symbol: Mapped[str] = mapped_column(String(32), index=True)
    new_symbol: Mapped[str] = mapped_column(String(32), index=True)
    change_date: Mapped[date] = mapped_column(Date)
    company_name: Mapped[str | None] = mapped_column(String(200))


class ScanRun(Base):
    """One run of the daily scan. A blocked run records why it did not run."""

    __tablename__ = "scan_runs"
    __table_args__ = (UniqueConstraint("trade_date", "score_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    score_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))  # "ok" or "blocked"
    universe_size: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScanResult(Base):
    """One stock in a scan's universe with its technical score and the inputs."""

    __tablename__ = "scan_results"

    run_id: Mapped[int] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="CASCADE"), primary_key=True
    )
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32))
    rank: Mapped[int] = mapped_column(Integer)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    close: Mapped[Decimal] = mapped_column(Price)
    in_nifty500: Mapped[bool] = mapped_column(Boolean, default=False)
    sector: Mapped[str | None] = mapped_column(String(100))
    components: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    indicators: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class BacktestRun(Base):
    """One walk-forward evaluation of one strategy. Runs are never overwritten, so
    every evaluation ever made stays on record."""

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_key: Mapped[str] = mapped_column(String(64), index=True)
    strategy_version: Mapped[str] = mapped_column(String(64))
    strategy_name: Mapped[str] = mapped_column(String(200))
    tier: Mapped[str] = mapped_column(String(16))
    data_start: Mapped[date] = mapped_column(Date)
    data_end: Mapped[date] = mapped_column(Date)
    oos_start: Mapped[date] = mapped_column(Date)
    holdout_start: Mapped[date] = mapped_column(Date)
    live_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    # Hash of the prices, universe and scores used; equal hashes mean equal inputs.
    fingerprint: Mapped[str] = mapped_column(String(32))
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Daily equity, drawdown and benchmark from the out-of-sample start.
    equity: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BacktestTrade(Base):
    """One out-of-sample or holdout trade of a backtest run. Prices are adjusted for
    splits and bonuses as of the run's last data date; shares are raw at entry."""

    __tablename__ = "backtest_trades"

    run_id: Mapped[int] = mapped_column(
        ForeignKey("backtest_runs.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    segment: Mapped[str] = mapped_column(String(16))  # "oos" or "holdout"
    symbol: Mapped[str] = mapped_column(String(32))
    variant: Mapped[str] = mapped_column(String(200))
    signal_date: Mapped[date] = mapped_column(Date)
    entry_date: Mapped[date] = mapped_column(Date)
    exit_date: Mapped[date] = mapped_column(Date)
    entry_price: Mapped[Decimal] = mapped_column(Price)
    stop_price: Mapped[Decimal] = mapped_column(Price)
    target_price: Mapped[Decimal] = mapped_column(Price)
    exit_price: Mapped[Decimal] = mapped_column(Price)
    shares: Mapped[int] = mapped_column(Integer)
    exit_reason: Mapped[str] = mapped_column(String(100))
    gross_pnl: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    charges: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    dividends: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    r_multiple: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    regime: Mapped[str] = mapped_column(String(16))
    score: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    sessions: Mapped[int] = mapped_column(Integer)
    open_at_end: Mapped[bool] = mapped_column(Boolean, default=False)


class BacktestVariant(Base):
    """Every grid point tried for every walk-forward window, with its training
    numbers and whether it was chosen (spec: log every variant tried)."""

    __tablename__ = "backtest_variants"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("backtest_runs.id", ondelete="CASCADE"), index=True
    )
    window: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(200))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    train_start: Mapped[date] = mapped_column(Date)
    train_end: Mapped[date] = mapped_column(Date)
    trades: Mapped[int] = mapped_column(Integer)
    expectancy_r: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    sharpe: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    chosen: Mapped[bool] = mapped_column(Boolean, default=False)


class PaperAccount(Base):
    """A strategy's paper-trading account (spec section 7, stage 2). It keeps the
    grid point and portfolio settings it opened with; new ones mean a new account."""

    __tablename__ = "paper_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_key: Mapped[str] = mapped_column(String(64), index=True)
    strategy_version: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    params_label: Mapped[str] = mapped_column(String(200))
    # The backtest run the parameters and the signals' backtest record come from.
    backtest_run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"))
    # False: the strategy failed section 6, so its signals are research only.
    live_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    start_date: Mapped[date] = mapped_column(Date)
    capital: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="active")  # "active" / "closed"
    last_date: Mapped[date | None] = mapped_column(Date)
    # The latest update's numbers (equity, cash, heat, open positions, notes).
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SignalRecord(Base):
    """A signal as issued (spec section 4). Never changed once stored; a change would
    be a new version."""

    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("account_id", "signal_date", "ticker", "version"),)

    signal_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    account_id: Mapped[int] = mapped_column(ForeignKey("paper_accounts.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(32))
    signal_date: Mapped[date] = mapped_column(Date, index=True)
    research_only: Mapped[bool] = mapped_column(Boolean)
    # Recorded after the day it was for (the paper job was catching up).
    late: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperTrade(Base):
    """A paper trade, open or closed. Re-derived on every update by replaying the
    account. Prices are raw rupees per share on the day they refer to."""

    __tablename__ = "paper_trades"

    account_id: Mapped[int] = mapped_column(
        ForeignKey("paper_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    ticker: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))  # "open" / "closed"
    signal_date: Mapped[date] = mapped_column(Date)
    entry_date: Mapped[date] = mapped_column(Date)
    entry_price: Mapped[Decimal] = mapped_column(Price)
    initial_stop: Mapped[Decimal] = mapped_column(Price)
    target_t1: Mapped[Decimal] = mapped_column(Price)
    shares: Mapped[int] = mapped_column(Integer)
    # Open trades: today's stop, close and shares still held (raw, today's basis).
    current_stop: Mapped[Decimal | None] = mapped_column(Price)
    last_close: Mapped[Decimal | None] = mapped_column(Price)
    shares_held: Mapped[int] = mapped_column(Integer, default=0)
    exit_date: Mapped[date | None] = mapped_column(Date)
    exit_price: Mapped[Decimal | None] = mapped_column(Price)
    exit_reason: Mapped[str | None] = mapped_column(String(100))
    charges: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    dividends: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    # Closed: realised after costs. Open: realised part plus the rest marked at the
    # close, before the costs of selling it.
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    r_multiple: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    sessions: Mapped[int] = mapped_column(Integer)
    exits: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class PaperDay(Base):
    """A paper account's state at one close. Re-derived on every update."""

    __tablename__ = "paper_days"

    account_id: Mapped[int] = mapped_column(
        ForeignKey("paper_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    equity: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    drawdown_pct: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    heat_pct: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    open_positions: Mapped[int] = mapped_column(Integer)


class Alert(Base):
    """A message sent (or tried) to me: one per key, so a re-run never sends twice.
    Keys: "signal:<signal_id>", "digest:<date>", "test:<timestamp>"."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[str] = mapped_column(String(16))  # "signal" / "digest" / "test"
    trade_date: Mapped[date | None] = mapped_column(Date, index=True)
    signal_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16))  # "sent" / "failed"
    # The channel that delivered it ("telegram" / "email"), or the last one tried.
    channel: Mapped[str | None] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(String)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JournalEntry(Base):
    """What I did with a signal (spec section 8), or a trade I took without one. Every
    signal without an entry counts as pending."""

    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Null for a trade taken without a signal.
    signal_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("signals.signal_id"), unique=True
    )
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    strategy_key: Mapped[str | None] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(16))  # "taken" / "skipped" / "modified"
    reason: Mapped[str] = mapped_column(String, default="")
    # My stop, when it differs from the signal's (raw rupees); R is measured against it.
    stop: Mapped[Decimal | None] = mapped_column(Price)
    followed_plan: Mapped[bool | None] = mapped_column(Boolean)
    notes: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class JournalFill(Base):
    """One buy or sell I made for a journal entry (raw rupees per share)."""

    __tablename__ = "journal_fills"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="CASCADE"), index=True
    )
    trade_date: Mapped[date] = mapped_column(Date)
    side: Mapped[str] = mapped_column(String(4))  # "buy" / "sell"
    shares: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Price)
    # Brokerage, taxes and fees for this fill, in rupees.
    charges: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal(0))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
