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

- idle cash = capital - open positions at cost - the cost of the next session's live
  signals not yet taken. The backtests credit idle cash with a liquid-fund rate (6.5% a
  year, about 30% of rs-pullback's backtest gain), which a broker balance doesn't earn,
  so idle cash above `IDLE_CASH_MIN` gets a line saying to park it. With
  `JERON_IDLE_CASH_IN_INDEX` on, the line says a Nifty index fund instead: the backtests'
  dotted cash-sweep line (M8 part 2) shows what that did, more return in rising markets
  and much of the index's drawdown back. It is an allocation choice, not an edge.

- tax notes (roadmap item 6): a profitable position within `LTCG_SOON_DAYS` of being
  held a year, when selling turns from short-term (20%) to long-term (12.5%) tax; and in
  February and March, positions below cost whose loss would count against this
  financial year's gains if sold before 31 March. The exit plan still decides; a note
  never says to hold past a stop. Days count from the first buy.

Capital is `JERON_CAPITAL`: the journal does not know the account's cash.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.backtest.costs import TaxRules

ZERO = Decimal(0)
# Below this, idle cash isn't worth a reminder.
IDLE_CASH_MIN = Decimal("50000")
UNKNOWN_SECTOR = "Unknown"
# A profitable position this close to a year held gets a long-term tax note.
LTCG_SOON_DAYS = 60
TAX = TaxRules()


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
    def cost(self) -> Decimal:
        return _q(self.avg_entry * self.shares)

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
    invested: Decimal = ZERO  # open positions at cost
    pending_cost: Decimal = ZERO  # the next session's live signals not yet taken
    idle_cash: Decimal = ZERO
    cash_action: str | None = None  # park idle cash, or free some up
    tax_notes: list[str] = field(default_factory=list)


def tax_notes(holdings: Sequence[Holding], as_of: date) -> list[str]:
    """Tax timing notes for the open positions (see the module docstring)."""
    long_after = TAX.long_term_days
    st_pct, lt_pct = Decimal(str(TAX.stcg_new_pct)), Decimal(str(TAX.ltcg_new_pct))
    notes = []
    for h in holdings:
        if h.last_close is None:
            continue
        gain = (h.last_close - h.avg_entry) * h.shares
        held = h.days_held(as_of)
        if gain > 0 and long_after - LTCG_SOON_DAYS <= held <= long_after:
            turns = h.first_date + timedelta(days=long_after + 1)
            saving = gain * (st_pct - lt_pct) / 100
            notes.append(
                f"{h.ticker} becomes long-term on {turns:%d %b %Y} (in {(turns - as_of).days} "
                f"days): sold after that, today's ₹{gain:,.0f} gain is taxed at {_g(lt_pct)}% "
                f"instead of {_g(st_pct)}%, up to ₹{saving:,.0f} less. Follow the exit plan "
                "if the stop is hit first."
            )
        if gain < 0 and as_of.month in (2, 3):
            notes.append(
                f"{h.ticker} is ₹{-gain:,.0f} below cost. If you would sell it anyway, selling "
                "before 31 March counts the loss against this financial year's gains; unused "
                "losses carry forward 8 years."
            )
    return notes


def idle_cash_line(idle: Decimal, in_index: bool = False) -> str | None:
    """What to do with idle cash: park it in a liquid fund (or, `in_index`, a Nifty
    index fund), or free some up."""
    fund = "index fund" if in_index else "liquid fund"
    if idle >= IDLE_CASH_MIN:
        if in_index:
            return (
                f"₹{idle:,.0f} is idle: park it in a Nifty 50 or Nifty 500 index fund or ETF "
                "(such as NIFTYBEES), as you chose in Settings. It rises and falls with the "
                "market; the backtest's dotted cash-sweep line shows what that did."
            )
        return (
            f"₹{idle:,.0f} is idle: park it in a liquid fund or liquid ETF (such as "
            "LIQUIDBEES). The backtests assume idle cash earns 6.5% a year."
        )
    if idle < 0:
        return (
            f"Open positions and the next session's signals need ₹{-idle:,.0f} more than "
            f"capital: sell that much of the {fund} before buying, or skip a signal."
        )
    return None


def totals(
    holdings: Sequence[Holding],
    capital: Decimal,
    heat_warn_pct: Decimal,
    heat_block_pct: Decimal,
    sector_cap_pct: Decimal,
    pending_cost: Decimal = ZERO,
    idle_in_index: bool = False,
    as_of: date | None = None,
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
    invested = sum((h.cost for h in holdings), ZERO)
    idle = capital - invested - pending_cost
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
        invested=_q(invested),
        pending_cost=_q(pending_cost),
        idle_cash=_q(idle),
        cash_action=idle_cash_line(idle, idle_in_index),
        tax_notes=[] if as_of is None else tax_notes(holdings, as_of),
    )
