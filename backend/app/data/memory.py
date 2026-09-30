"""An in-memory DataProvider, used in tests and as a reference implementation."""

from collections.abc import Iterable
from datetime import date

from app.data.provider import Bar, CorporateActionRecord, InstrumentRecord, validate_bar


class InMemoryProvider:
    name = "memory"

    def __init__(
        self,
        bars: Iterable[Bar] = (),
        actions: Iterable[CorporateActionRecord] = (),
        instruments: Iterable[InstrumentRecord] = (),
    ) -> None:
        self._bars = sorted(bars, key=lambda b: (b.symbol, b.trade_date))
        for bar in self._bars:
            validate_bar(bar)
        self._actions = list(actions)
        self._instruments = list(instruments)

    def daily_bars(self, trade_date: date) -> list[Bar]:
        return [b for b in self._bars if b.trade_date == trade_date]

    def history(self, symbol: str, start: date, end: date) -> list[Bar]:
        return [b for b in self._bars if b.symbol == symbol and start <= b.trade_date <= end]

    def corporate_actions(self, start: date, end: date) -> list[CorporateActionRecord]:
        return [a for a in self._actions if start <= a.ex_date <= end]

    def instruments(self) -> list[InstrumentRecord]:
        return list(self._instruments)
