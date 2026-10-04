"""Zerodha's tradebook CSV (Console > Reports > Tradebook), read into broker trades.

Columns as Console exports them: symbol, isin, trade_date, exchange, segment, series,
trade_type, auction, quantity, price, trade_id, order_id, order_execution_time. Only
equity cash trades (segment EQ) are kept; F&O, currency and commodity rows are counted
and skipped. Charges aren't in the tradebook, so they are estimated with the
backtester's cost model (Zerodha delivery rates). Pure: no database.
"""

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.backtest.costs import CostModel

BROKER = "zerodha"
REQUIRED = ("symbol", "trade_date", "exchange", "segment", "trade_type", "quantity", "price")
EQUITY_SEGMENTS = frozenset({"EQ"})


@dataclass(frozen=True)
class BrokerTrade:
    symbol: str
    isin: str | None
    trade_date: date
    exchange: str
    side: str  # "buy" / "sell"
    shares: int
    price: Decimal
    trade_id: str
    order_id: str
    executed_at: datetime | None

    @property
    def key(self) -> str:
        """Unique per trade: Zerodha's trade ids are unique per exchange."""
        return f"{BROKER}:{self.exchange}:{self.trade_id}"


@dataclass
class Tradebook:
    trades: list[BrokerTrade] = field(default_factory=list)
    # Rows that aren't equity cash trades, counted by segment.
    skipped: dict[str, int] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


def _date(text: str) -> date:
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"unknown date {text!r}")


def _time(text: str) -> datetime | None:
    text = text.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def parse_tradebook(text: str) -> Tradebook:
    book = Tradebook()
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    columns = {(c or "").strip().lower() for c in reader.fieldnames or []}
    missing = [c for c in REQUIRED if c not in columns]
    if missing:
        book.problems.append(
            "Not a Zerodha tradebook: missing column(s) " + ", ".join(missing) + ". "
            "Download it from Console > Reports > Tradebook (Equity)."
        )
        return book
    for n, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if not any(row.values()):
            continue
        segment = row["segment"].upper()
        if segment not in EQUITY_SEGMENTS:
            book.skipped[segment or "blank"] = book.skipped.get(segment or "blank", 0) + 1
            continue
        try:
            side = row["trade_type"].lower()
            if side not in ("buy", "sell"):
                raise ValueError(f"trade_type {row['trade_type']!r}")
            quantity = Decimal(row["quantity"])
            if quantity <= 0 or quantity != quantity.to_integral_value():
                raise ValueError(f"quantity {row['quantity']!r}")
            price = Decimal(row["price"])
            if price <= 0:
                raise ValueError(f"price {row['price']!r}")
            trade_id = row.get("trade_id", "") or f"row{n}"
            book.trades.append(
                BrokerTrade(
                    symbol=row["symbol"].upper(),
                    isin=row.get("isin") or None,
                    trade_date=_date(row["trade_date"]),
                    exchange=row["exchange"].upper(),
                    side=side,
                    shares=int(quantity),
                    price=price,
                    trade_id=trade_id,
                    order_id=row.get("order_id", ""),
                    executed_at=_time(row.get("order_execution_time", "")),
                )
            )
        except (ValueError, InvalidOperation) as e:
            book.problems.append(f"Row {n}: {e}")
    book.trades.sort(key=lambda t: (t.trade_date, t.executed_at or datetime.min, t.trade_id))
    return book


def estimate_charges(
    trades: Sequence[BrokerTrade], costs: CostModel | None = None
) -> dict[str, Decimal]:
    """Estimated charges per trade (by key). DP charges are per stock per day of
    selling, so they go on the first sell of each stock and day."""
    costs = costs or CostModel()
    out: dict[str, Decimal] = {}
    dp_charged: set[tuple[str, date]] = set()
    for t in trades:
        c = costs.charges(float(t.price * t.shares), t.side)
        total = c.total - c.dp
        if t.side == "sell" and (t.symbol, t.trade_date) not in dp_charged:
            dp_charged.add((t.symbol, t.trade_date))
            total += c.dp
        out[t.key] = Decimal(f"{total:.2f}")
    return out
