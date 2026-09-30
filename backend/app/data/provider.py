"""The DataProvider interface.

Every market-data source (NSE bhavcopy, yfinance, a broker API) implements this
protocol, so sources can be swapped or cross-checked without touching the rest of
the app. Prices returned here are always raw (unadjusted); adjustment happens later
from corporate actions.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

from app.models import CorporateActionType


@dataclass(frozen=True)
class Bar:
    symbol: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    prev_close: Decimal | None = None
    turnover: Decimal | None = None


@dataclass(frozen=True)
class CorporateActionRecord:
    symbol: str
    ex_date: date
    action_type: CorporateActionType
    ratio_new: Decimal | None = None
    ratio_old: Decimal | None = None
    amount: Decimal | None = None
    raw_text: str | None = None


@dataclass(frozen=True)
class InstrumentRecord:
    symbol: str
    isin: str | None
    name: str | None
    series: str = "EQ"
    listing_date: date | None = None


class BarValidationError(ValueError):
    pass


def validate_bar(bar: Bar) -> None:
    """Reject bars that cannot be real. Raises BarValidationError."""
    if min(bar.open, bar.high, bar.low, bar.close) <= 0:
        raise BarValidationError(f"{bar.symbol} {bar.trade_date}: non-positive price")
    if bar.high < max(bar.open, bar.close, bar.low):
        raise BarValidationError(f"{bar.symbol} {bar.trade_date}: high below open/close/low")
    if bar.low > min(bar.open, bar.close):
        raise BarValidationError(f"{bar.symbol} {bar.trade_date}: low above open/close")
    if bar.volume < 0:
        raise BarValidationError(f"{bar.symbol} {bar.trade_date}: negative volume")


@runtime_checkable
class DataProvider(Protocol):
    """A source of end-of-day market data."""

    #: Short identifier stored in daily_bars.source, e.g. "nse_bhavcopy".
    name: str

    def daily_bars(self, trade_date: date) -> list[Bar]:
        """All equity bars for one trading day."""
        ...

    def history(self, symbol: str, start: date, end: date) -> list[Bar]:
        """Bars for one symbol, start and end inclusive, oldest first."""
        ...

    def corporate_actions(self, start: date, end: date) -> list[CorporateActionRecord]:
        """Corporate actions with ex-dates between start and end inclusive."""
        ...

    def instruments(self) -> list[InstrumentRecord]:
        """Currently listed equity instruments."""
        ...
