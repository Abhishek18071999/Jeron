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

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

Price = Numeric(14, 4)


def pg_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """Store enum values ("split"), not member names ("SPLIT")."""
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"


class CorporateActionType(StrEnum):
    SPLIT = "split"
    BONUS = "bonus"
    RIGHTS = "rights"
    DIVIDEND = "dividend"
    OTHER = "other"


class QualityStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("exchange", "symbol", "series"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    exchange: Mapped[Exchange] = mapped_column(pg_enum(Exchange, "exchange"))
    symbol: Mapped[str] = mapped_column(String(32))
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
    __tablename__ = "corporate_actions"

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


class IndexMembership(Base):
    """Point-in-time index constituents. end_date is null while still a member."""

    __tablename__ = "index_memberships"

    id: Mapped[int] = mapped_column(primary_key=True)
    index_name: Mapped[str] = mapped_column(String(64), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)


class DataQualityReport(Base):
    __tablename__ = "data_quality_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[QualityStatus] = mapped_column(pg_enum(QualityStatus, "quality_status"))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
