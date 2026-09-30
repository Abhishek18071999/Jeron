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
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
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

    id: Mapped[int] = mapped_column(primary_key=True)
    index_name: Mapped[str] = mapped_column(String(64), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)


class SourceFile(Base):
    """What happened when a source's data for one day was fetched.

    status: "ok", "not_published" (the source has no file: a holiday) or
    "not_fetched" (the download failed; retried on the next run).
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
