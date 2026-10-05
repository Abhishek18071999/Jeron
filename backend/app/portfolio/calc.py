"""My real portfolio from the journal: per-position risk numbers, portfolio heat and
sector exposure, measured against the spec section 5 limits. Pure: no database.

Definitions (the engine's, `app.backtest.engine`):
- open risk of a position = max(0, entry - today's stop) x shares held. Once the stop
  is at breakeven or above, the position adds nothing.
- portfolio heat = total open risk as a % of capital; warned at 5%, new entries blocked
  above 6% (`PortfolioRules.heat_warn_pct`, `heat_block_pct`).
- give-back = max(0, last close - today's stop) x shares held: what hitting every stop
  would cost from today's close.
- sector exposure = shares x last close per sector, as a % of capital; the sector cap is
  `JERON_SECTOR_CAP_PCT`. Stocks without a known sector are grouped as "Unknown".

Capital is `JERON_CAPITAL`: the journal does not know the account's cash.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

ZERO = Decimal(0)
UNKNOWN_SECTOR = "Unknown"


def _q(value: Decimal, places: str = "0.01") -> Decimal:
    return value.quantize(Decimal(places))


def _g(value: Decimal) -> str:
    """30.0 -> "30", 5.5 -> "5.5"."""
    return f"{float(value):g}"


@dataclass(frozen=True)
class Holding:
    """One open journal position. Prices are rupees on today's basis (after any split
    since the buy, the exit plan's adjusted prices)."""

    entry_id: int
    ticker: str
    strategy_key: str | None
    sector: str | None
    shares: int
    avg_entry: Decimal
    last_close: Decimal | None
    last_close_date: date | None
    stop: Decimal | None  # today's stop: the plan's (breakeven, raised) or the journal's
    initial_stop: Decimal | None
    pnl: Decimal | None  # realised + open, after charges
    r_multiple: Decimal | None
    first_date: date
    sessions_held: int | None
    action: str | None  # "hold" / "sell half" / "sell all"; None = no plan
    reason: str | None
    problem: str | None = None
    events: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def value(self) -> Decimal | None:
        return None if self.last_close is None else _q(self.last_close * self.shares)

    @property
    def open_risk(self) -> Decimal | None:
        if self.stop is None:
            return None
        return _q(max(ZERO, self.avg_entry - self.stop) * self.shares)

    @property
    def give_back(self) -> Decimal | None:
        if self.stop is None or self.last_close is None:
            return None
        return _q(max(ZERO, self.last_close - self.stop) * self.shares)

    @property
    def stop_distance_pct(self) -> Decimal | None:
        """How far the last close is above the stop, in %. Negative: below it."""
        if self.stop is None or not self.last_close:
            return None
        return _q((self.last_close - self.stop) / self.last_close * 100)

    def days_held(self, as_of: date) -> int:
        return (as_of - self.first_date).days


@dataclass(frozen=True)
class SectorExposure:
    sector: str
    positions: int
    value: Decimal
    pct_of_capital: Decimal
    over_cap: bool


@dataclass(frozen=True)
class PortfolioTotals:
    positions: int
    value: Decimal
    pnl: Decimal
    open_risk: Decimal
    heat_pct: Decimal
    give_back: Decimal
    # Positions with no stop: their risk is unknown and not in the totals.
    without_stop: int
    heat_warn_pct: Decimal
    heat_block_pct: Decimal
    sector_cap_pct: Decimal
    capital: Decimal
    sectors: list[SectorExposure]
    warnings: list[str]


def totals(
    holdings: Sequence[Holding],
    capital: Decimal,
    heat_warn_pct: Decimal,
    heat_block_pct: Decimal,
    sector_cap_pct: Decimal,
) -> PortfolioTotals:
    value = sum((h.value or ZERO for h in holdings), ZERO)
    pnl = sum((h.pnl or ZERO for h in holdings), ZERO)
    open_risk = sum((h.open_risk or ZERO for h in holdings), ZERO)
    give_back = sum((h.give_back or ZERO for h in holdings), ZERO)
    heat = open_risk / capital * 100 if capital > 0 else ZERO
    by_sector: dict[str, list[Holding]] = {}
    for h in holdings:
        by_sector.setdefault(h.sector or UNKNOWN_SECTOR, []).append(h)
    sectors = []
    for name, members in by_sector.items():
        worth = sum((h.value or ZERO for h in members), ZERO)
        pct = worth / capital * 100 if capital > 0 else ZERO
        sectors.append(
            SectorExposure(
                name,
                len(members),
                _q(worth),
                _q(pct),
                name != UNKNOWN_SECTOR and pct > sector_cap_pct,
            )
        )
    sectors.sort(key=lambda s: (-s.value, s.sector))
    warnings = []
    if heat > heat_block_pct:
        warnings.append(
            f"Portfolio heat {heat:.1f}% is above {_g(heat_block_pct)}%: no new entries "
            "until risk comes down."
        )
    elif heat >= heat_warn_pct:
        warnings.append(
            f"Portfolio heat {heat:.1f}% is at the {_g(heat_warn_pct)}% warning level "
            f"(new entries blocked above {_g(heat_block_pct)}%)."
        )
    for s in sectors:
        if s.over_cap:
            warnings.append(
                f"{s.sector} is {s.pct_of_capital:.1f}% of capital, above the "
                f"{_g(sector_cap_pct)}% sector cap."
            )
    without_stop = sum(1 for h in holdings if h.stop is None)
    if without_stop:
        warnings.append(
            f"{without_stop} open position{'s' if without_stop > 1 else ''} without a stop: "
            "its risk is unknown. Add a stop in the journal."
        )
    return PortfolioTotals(
        positions=len(holdings),
        value=_q(value),
        pnl=_q(pnl),
        open_risk=_q(open_risk),
        heat_pct=_q(heat),
        give_back=_q(give_back),
        without_stop=without_stop,
        heat_warn_pct=heat_warn_pct,
        heat_block_pct=heat_block_pct,
        sector_cap_pct=sector_cap_pct,
        capital=capital,
        sectors=sectors,
        warnings=warnings,
    )
