"""Watchlist alert rules. Pure.

An alert price is raw rupees, as the broker shows it. "above" is hit when the day's high
reaches it, "below" when the day's low does. Each item alerts once per direction and
price (the alert key); changing the price arms it again.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

DIRECTIONS = ("above", "below")


def alert_key(item_id: int, direction: str, price: Decimal) -> str:
    return f"watch:{item_id}:{direction}:{price.normalize():f}"


def is_hit(direction: str, price: Decimal, high: Decimal, low: Decimal) -> bool:
    if direction == "above":
        return high >= price
    if direction == "below":
        return low <= price
    raise ValueError(f"direction must be above or below, not {direction!r}")


def pct_to_alert(price: Decimal, close: Decimal) -> Decimal | None:
    """How far the close must move to reach the alert price, in % (+ up, - down)."""
    if close <= 0:
        return None
    return ((price / close - 1) * 100).quantize(Decimal("0.01"))


@dataclass(frozen=True)
class Hit:
    item_id: int
    ticker: str
    direction: str
    price: Decimal
    day: date
    high: Decimal
    low: Decimal
    close: Decimal
    note: str

    @property
    def key(self) -> str:
        return alert_key(self.item_id, self.direction, self.price)
