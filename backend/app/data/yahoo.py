"""Yahoo Finance daily history, used as the second source for cross-checking.

Yahoo's chart API returns prices already adjusted for splits (and bonuses, which it
records as splits), but not for dividends. To compare like with like, this module
undoes Yahoo's split adjustment using Yahoo's own split events, giving raw prices
that should match NSE's bhavcopy.
"""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from app.data.http import Fetcher
from app.data.provider import Bar, CorporateActionRecord
from app.enums import CorporateActionType

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
IST_OFFSET_SECONDS = 19800
_CENTS = Decimal("0.01")


def yahoo_ticker(nse_symbol: str) -> str:
    return f"{nse_symbol}.NS"


@dataclass
class YahooHistory:
    symbol: str
    bars: list[Bar]
    actions: list[CorporateActionRecord]


def _day(timestamp: int, offset: int) -> date:
    return datetime.fromtimestamp(timestamp + offset, tz=UTC).date()


def _price(value: float, factor: Decimal) -> Decimal:
    # Yahoo sends float32-style values (1197.5999755859375); NSE prices have 2 dp.
    return (Decimal(repr(value)) * factor).quantize(_CENTS)


def parse_chart(symbol: str, payload: dict[str, Any]) -> YahooHistory:
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise ValueError(f"Yahoo error for {symbol}: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        return YahooHistory(symbol, [], [])
    result = results[0]
    offset = int(result.get("meta", {}).get("gmtoffset", IST_OFFSET_SECONDS))
    events = result.get("events") or {}

    actions: list[CorporateActionRecord] = []
    splits: list[tuple[date, Decimal]] = []
    for split in (events.get("splits") or {}).values():
        num, den = Decimal(str(split["numerator"])), Decimal(str(split["denominator"]))
        if num <= 0 or den <= 0:
            continue
        ex_date = _day(int(split["date"]), offset)
        splits.append((ex_date, num / den))
        actions.append(
            CorporateActionRecord(
                symbol,
                ex_date,
                CorporateActionType.SPLIT,
                ratio_new=num,
                ratio_old=den,
                raw_text=f"split {split.get('splitRatio') or f'{num}:{den}'}",
            )
        )
    for dividend in (events.get("dividends") or {}).values():
        amount = Decimal(repr(float(dividend["amount"]))).quantize(Decimal("0.0001"))
        actions.append(
            CorporateActionRecord(
                symbol,
                _day(int(dividend["date"]), offset),
                CorporateActionType.DIVIDEND,
                amount=amount,
                raw_text=f"dividend {amount}",
            )
        )

    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    bars = []
    for i, ts in enumerate(result.get("timestamp") or []):
        values = [quote.get(k, [None] * (i + 1))[i] for k in ("open", "high", "low", "close")]
        volume = quote.get("volume", [None] * (i + 1))[i]
        if any(v is None for v in values) or volume is None:
            continue
        day = _day(int(ts), offset)
        # Undo Yahoo's split adjustment: multiply by every later split's ratio.
        factor = Decimal(1)
        for split_day, ratio in splits:
            if split_day > day:
                factor *= ratio
        o, h, lo, c = (_price(float(v), factor) for v in values)
        if min(o, h, lo, c) <= 0:
            continue
        bars.append(
            Bar(
                symbol=symbol,
                trade_date=day,
                open=o,
                high=h,
                low=lo,
                close=c,
                volume=round(Decimal(int(volume)) / factor),
            )
        )
    return YahooHistory(symbol, bars, sorted(actions, key=lambda a: a.ex_date))


class YahooClient:
    name = "yahoo"

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    def history(self, symbol: str, start: date, end: date) -> YahooHistory:
        period1 = int(datetime.combine(start, time(0), tzinfo=UTC).timestamp())
        period2 = int(datetime.combine(end + timedelta(days=1), time(0), tzinfo=UTC).timestamp())
        content = self.fetcher.get(
            CHART_URL.format(ticker=yahoo_ticker(symbol)),
            params={
                "period1": str(period1),
                "period2": str(period2),
                "interval": "1d",
                "events": "div,splits",
                "includeAdjustedClose": "false",
            },
        )
        history = parse_chart(symbol, json.loads(content))
        history.bars = [b for b in history.bars if start <= b.trade_date <= end]
        return history
