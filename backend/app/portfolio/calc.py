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
  never says to hold past a stop. Days count from the first buy. The long-term note
  gives the rupee tax of selling now (20% short-term) against selling after the mark
  (12.5% on the gain above the long-term exemption left in the financial year the sale
  would fall in).
- long-term exemption used (roadmap item 6): the first ₹1.25 lakh of net long-term gains
  in a financial year is tax free. Realised sales come from the journal's fills, lots
  matched first in, first out (as the tax law does) with each fill's charges in its cost
  or proceeds; this year's short-term losses are set off against long-term gains first.
  An estimate for planning, not a tax computation: other accounts and income are not
  known to Jeron.

- the account's guardrails (docs/plans/platform-audit-v1.md, slice 3): equity =
  capital + every realised sale's gain (lots first in, first out, after charges) + the
  open positions marked at the last close. The peak is the highest of capital plus the
  running realised total on each sale day, and today's equity. Open profit on past days
  is not known (there is no daily mark of the journal), so a peak reached only on paper
  and given back before selling is missed: the drawdown can read lower than a broker's.
  Spec section 5: at 10% below the peak risk per trade is halved, at 15% new entries
  stop. Realised today / this week (Monday to `as_of`) and first buys this week feed
  the daily and weekly loss limits and the weekly entries cap.

Capital is `JERON_CAPITAL`: the journal does not know the account's cash, deposits or
withdrawals.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.backtest.costs import TaxRules, financial_year
from app.journal.calc import Fill

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
    tier: str | None = None  # the signal's tier; swing rules for a trade without one

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
    exemption: "LongTermExemption | None" = None  # None without a day


@dataclass(frozen=True)
class Sale:
    """Shares of one lot sold: the gain after the lot's share of charges."""

    ticker: str
    sell_date: date
    shares: int
    gain: Decimal
    held_days: int

    @property
    def long_term(self) -> bool:
        return self.held_days > TAX.long_term_days


def realised_sales(ticker: str, fills: Sequence[Fill]) -> list[Sale]:
    """One position's sales matched first in, first out against its buys. A buy's
    charges are spread over its shares, and so are a sale's."""
    lots: list[list[Any]] = []  # [buy date, shares left, cost per share incl. charges]
    sales = []
    for f in sorted(fills, key=lambda f: (f.trade_date, f.side != "buy")):
        if f.shares <= 0:
            continue
        if f.side == "buy":
            lots.append([f.trade_date, f.shares, f.price + f.charges / f.shares])
            continue
        net = f.price - f.charges / f.shares
        left = f.shares
        while left and lots:
            lot = lots[0]
            n = min(left, lot[1])
            sales.append(
                Sale(ticker, f.trade_date, n, _q((net - lot[2]) * n), (f.trade_date - lot[0]).days)
            )
            lot[1] -= n
            left -= n
            if not lot[1]:
                lots.pop(0)
    return sales


@dataclass(frozen=True)
class LongTermExemption:
    """This financial year's long-term gains against the yearly exemption."""

    year: int  # the financial year, named by its starting year (2026 = 2026-27)
    long_term: Decimal  # net long-term gains realised
    short_term: Decimal  # net short-term gains realised (negative: a loss)
    exemption: Decimal
    used: Decimal
    left: Decimal

    @property
    def label(self) -> str:
        return f"{self.year}-{(self.year + 1) % 100:02d}"

    @property
    def line(self) -> str:
        if self.used >= self.exemption:
            return (
                f"FY {self.label}: the ₹{self.exemption:,.0f} long-term exemption is used up "
                f"(net long-term gains ₹{self.long_term:,.0f}); further long-term gains are "
                f"taxed at {_g(Decimal(str(TAX.ltcg_new_pct)))}%."
            )
        return (
            f"FY {self.label}: ₹{self.used:,.0f} of the ₹{self.exemption:,.0f} long-term "
            f"exemption used, ₹{self.left:,.0f} left. Long-term gains up to that are tax free "
            "this financial year."
        )


def long_term_exemption(sales: Iterable[Sale], as_of: date) -> LongTermExemption:
    """How much of `as_of`'s financial year's long-term exemption the journal's sales
    used: net long-term gains after this year's short-term losses, up to the exemption."""
    year = financial_year(as_of)
    st = lt = ZERO
    for s in sales:
        if financial_year(s.sell_date) != year or s.sell_date > as_of:
            continue
        if s.long_term:
            lt += s.gain
        else:
            st += s.gain
    exemption = Decimal(str(TAX.ltcg_exempt_new))
    taxable_lt = max(ZERO, lt - max(ZERO, -st))
    used = min(exemption, taxable_lt)
    return LongTermExemption(year, _q(lt), _q(st), exemption, _q(used), _q(exemption - used))


def sell_now_or_later(
    gain: Decimal, now: date, turns: date, exemption_left: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    """Tax on a `gain` sold `now` (short-term) against sold on `turns` (long-term),
    and the exemption the later sale could use: what is left this financial year, or a
    whole new one when the mark falls in the next. Before other gains and losses."""
    st_pct, lt_pct = Decimal(str(TAX.stcg_new_pct)), Decimal(str(TAX.ltcg_new_pct))
    if financial_year(turns) != financial_year(now):
        exemption_left = Decimal(str(TAX.ltcg_exempt_new))
    tax_now = max(ZERO, gain) * st_pct / 100
    tax_later = max(ZERO, gain - exemption_left) * lt_pct / 100
    return _q(tax_now, "1"), _q(tax_later, "1"), exemption_left


def tax_notes(
    holdings: Sequence[Holding], as_of: date, exemption_left: Decimal | None = None
) -> list[str]:
    """Tax timing notes for the open positions (see the module docstring).
    `exemption_left` is this financial year's unused long-term exemption (the whole of
    it when not given)."""
    long_after = TAX.long_term_days
    st_pct, lt_pct = Decimal(str(TAX.stcg_new_pct)), Decimal(str(TAX.ltcg_new_pct))
    left = Decimal(str(TAX.ltcg_exempt_new)) if exemption_left is None else exemption_left
    notes = []
    for h in holdings:
        if h.last_close is None:
            continue
        gain = (h.last_close - h.avg_entry) * h.shares
        held = h.days_held(as_of)
        if gain > 0 and long_after - LTCG_SOON_DAYS <= held <= long_after:
            turns = h.first_date + timedelta(days=long_after + 1)
            now, later, exempt = sell_now_or_later(gain, as_of, turns, left)
            which = (
                "next financial year's"
                if financial_year(turns) != financial_year(as_of)
                else "this financial year's"
            )
            notes.append(
                f"{h.ticker} becomes long-term on {turns:%d %b %Y} (in {(turns - as_of).days} "
                f"days): on today's ₹{gain:,.0f} gain, selling now costs about ₹{now:,.0f} in "
                f"tax ({_g(st_pct)}% short-term), selling after that about ₹{later:,.0f} "
                f"({_g(lt_pct)}% above the ₹{exempt:,.0f} of {which} exemption left), "
                f"₹{now - later:,.0f} less. Follow the exit plan if the stop is hit first."
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
    sales: Sequence[Sale] = (),
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
    exemption, notes = None, []
    if as_of is not None:
        exemption = long_term_exemption(sales, as_of)
        notes = tax_notes(holdings, as_of, exemption.left)
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
        tax_notes=notes,
        exemption=exemption,
    )


def week_start(day: date) -> date:
    """The Monday of `day`'s week."""
    return day - timedelta(days=day.weekday())


@dataclass(frozen=True)
class AccountState:
    """The real account from the journal, for the trade plan's guardrails."""

    capital: Decimal
    equity: Decimal
    peak: Decimal
    drawdown_pct: Decimal  # below the peak; 0 at the peak
    realised_today: Decimal  # net gain of sales on `as_of`, negative for a loss
    realised_week: Decimal  # Monday to `as_of`
    entries_week: int  # journal positions first bought Monday to `as_of`
    open_by_tier: dict[str, int]
    as_of: date


def account_state(
    capital: Decimal,
    sales: Iterable[Sale],
    first_buys: Iterable[date],
    holdings: Sequence[Holding],
    as_of: date,
) -> AccountState:
    """Equity, peak and drawdown, and this day's and week's results (module notes)."""
    by_day: dict[date, Decimal] = {}
    for sale in sales:
        if sale.sell_date <= as_of:
            by_day[sale.sell_date] = by_day.get(sale.sell_date, ZERO) + sale.gain
    running = peak_realised = ZERO
    for day in sorted(by_day):
        running += by_day[day]
        peak_realised = max(peak_realised, running)
    open_pnl = sum(
        ((h.last_close - h.avg_entry) * h.shares for h in holdings if h.last_close is not None),
        ZERO,
    )
    equity = capital + running + open_pnl
    peak = max(capital + peak_realised, equity)
    drawdown = (1 - equity / peak) * 100 if peak > 0 else ZERO
    monday = week_start(as_of)
    tiers: dict[str, int] = {}
    for h in holdings:
        tier = h.tier or "swing"
        tiers[tier] = tiers.get(tier, 0) + 1
    return AccountState(
        capital=capital,
        equity=_q(equity),
        peak=_q(peak),
        drawdown_pct=_q(max(drawdown, ZERO)),
        realised_today=_q(by_day.get(as_of, ZERO)),
        realised_week=_q(sum((g for d, g in by_day.items() if d >= monday), ZERO)),
        entries_week=sum(1 for d in first_buys if monday <= d <= as_of),
        open_by_tier=tiers,
        as_of=as_of,
    )
