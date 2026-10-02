"""Indian trading costs for equity delivery (spec section 5), and an estimated tax view.

Every rate is a field of `CostModel`, so a different broker or a rate change is a new
model, not a code change. Defaults are Zerodha's equity-delivery charges on NSE as
published in 2026:

| Charge | Rate |
|---|---|
| Brokerage | ₹0 on delivery |
| STT | 0.1% of value, buy and sell |
| Exchange transaction charge (NSE) | 0.00297% of value, buy and sell |
| SEBI fee | ₹10 per crore (0.0001%), buy and sell |
| Stamp duty | 0.015% of value, buy only |
| GST | 18% of brokerage + exchange charge + SEBI fee |
| DP charge | ₹15.34 per stock per day with a sale (incl. GST) |

Slippage is a percentage of the price per side, by the stock's 20-day median
turnover (thinner stocks cost more to trade):

| 20-day median turnover | Slippage per side |
|---|---|
| ₹100 crore and above | 0.05% |
| ₹20-100 crore | 0.10% |
| ₹5-20 crore | 0.20% |
| below ₹5 crore | 0.50% |

Money is computed in float here: these are estimates for a simulation, rounded to
paise when stored, and the backtester's prices are adjusted floats anyway.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

CRORE = 10_000_000.0


@dataclass(frozen=True)
class CostModel:
    name: str = "zerodha-delivery-2026"
    brokerage_pct: float = 0.0
    brokerage_max: float = 0.0  # cap per order in rupees (0 = no cap)
    stt_pct: float = 0.1
    exchange_pct: float = 0.00297
    sebi_per_crore: float = 10.0
    stamp_buy_pct: float = 0.015
    gst_pct: float = 18.0
    dp_per_sale: float = 15.34
    # (minimum 20-day median turnover in rupees, slippage % per side), highest first.
    slippage_buckets: tuple[tuple[float, float], ...] = (
        (100 * CRORE, 0.05),
        (20 * CRORE, 0.10),
        (5 * CRORE, 0.20),
        (0.0, 0.50),
    )

    def slippage_pct(self, median_turnover: float) -> float:
        for floor, pct in self.slippage_buckets:
            if median_turnover >= floor:
                return pct
        return self.slippage_buckets[-1][1]

    def charges(self, value: float, side: str) -> "Charges":
        """Charges for one order of `value` rupees. side is "buy" or "sell"."""
        brokerage = value * self.brokerage_pct / 100
        if self.brokerage_max:
            brokerage = min(brokerage, self.brokerage_max)
        stt = value * self.stt_pct / 100
        exchange = value * self.exchange_pct / 100
        sebi = value * self.sebi_per_crore / CRORE
        stamp = value * self.stamp_buy_pct / 100 if side == "buy" else 0.0
        gst = (brokerage + exchange + sebi) * self.gst_pct / 100
        dp = self.dp_per_sale if side == "sell" else 0.0
        return Charges(brokerage, stt, exchange, sebi, stamp, gst, dp)


@dataclass(frozen=True)
class Charges:
    brokerage: float
    stt: float
    exchange: float
    sebi: float
    stamp: float
    gst: float
    dp: float

    @property
    def total(self) -> float:
        return (
            self.brokerage + self.stt + self.exchange + self.sebi + self.stamp + self.gst + self.dp
        )


# --- Estimated tax (post-tax view) -----------------------------------------------------

# Budget 2024 changed capital-gains rates for sales from 23 July 2024.
TAX_CHANGE = date(2024, 7, 23)


@dataclass(frozen=True)
class TaxRules:
    stcg_old_pct: float = 15.0
    stcg_new_pct: float = 20.0
    ltcg_old_pct: float = 10.0
    ltcg_new_pct: float = 12.5
    ltcg_exempt_old: float = 100_000.0
    ltcg_exempt_new: float = 125_000.0
    # Dividends are taxed at your income slab; 30% is assumed.
    dividend_slab_pct: float = 30.0
    long_term_days: int = 365


@dataclass(frozen=True)
class Realised:
    """One sale's gain (after costs) for the tax estimate."""

    sell_date: date
    gain: float
    held_days: int


def financial_year(day: date) -> int:
    """The Indian financial year a date falls in, named by its starting year."""
    return day.year if day.month >= 4 else day.year - 1


@dataclass
class TaxYear:
    year: int
    stcg: float = 0.0
    ltcg: float = 0.0
    dividends: float = 0.0
    tax: float = 0.0
    loss_carried: float = 0.0


@dataclass
class TaxEstimate:
    years: list[TaxYear] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(y.tax for y in self.years)


def estimate_tax(
    sales: Iterable[Realised],
    dividends: Iterable[tuple[date, float]] = (),
    rules: TaxRules | None = None,
) -> TaxEstimate:
    """A simple estimate: per financial year, short-term losses offset short- then
    long-term gains, long-term losses offset long-term gains, net losses carry
    forward (eight years in law; here, until used). Each year's rate is the one in
    force at the year's last sale (the 2024 change applied from 23 July). Dividends
    are taxed at the assumed slab rate. Surcharge and cess are left out."""
    rules = rules or TaxRules()
    by_year: dict[int, TaxYear] = {}
    last_sale: dict[int, date] = {}
    for s in sales:
        fy = financial_year(s.sell_date)
        year = by_year.setdefault(fy, TaxYear(fy))
        if s.held_days > rules.long_term_days:
            year.ltcg += s.gain
        else:
            year.stcg += s.gain
        last_sale[fy] = max(last_sale.get(fy, s.sell_date), s.sell_date)
    for day, amount in dividends:
        fy = financial_year(day)
        by_year.setdefault(fy, TaxYear(fy)).dividends += amount
    carried: dict[str, float] = defaultdict(float)  # "st" / "lt" losses brought forward
    for fy in sorted(by_year):
        year = by_year[fy]
        new_rates = last_sale.get(fy, date(fy + 1, 3, 31)) >= TAX_CHANGE
        st_rate = rules.stcg_new_pct if new_rates else rules.stcg_old_pct
        lt_rate = rules.ltcg_new_pct if new_rates else rules.ltcg_old_pct
        exempt = rules.ltcg_exempt_new if new_rates else rules.ltcg_exempt_old
        st, lt = year.stcg, year.ltcg
        # Short-term losses (this year's and brought forward) offset any gain.
        st_loss = carried["st"] + max(-st, 0.0)
        st = max(st, 0.0)
        used = min(st_loss, st)
        st, st_loss = st - used, st_loss - used
        lt_loss = carried["lt"] + max(-lt, 0.0)
        lt = max(lt, 0.0)
        used = min(st_loss, lt)
        lt, st_loss = lt - used, st_loss - used
        used = min(lt_loss, lt)
        lt, lt_loss = lt - used, lt_loss - used
        carried["st"], carried["lt"] = st_loss, lt_loss
        year.tax = (
            st * st_rate / 100
            + max(lt - exempt, 0.0) * lt_rate / 100
            + max(year.dividends, 0.0) * rules.dividend_slab_pct / 100
        )
        year.loss_carried = st_loss + lt_loss
    return TaxEstimate([by_year[fy] for fy in sorted(by_year)])
