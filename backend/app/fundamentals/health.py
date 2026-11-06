"""Balance sheet, cash flow and valuation beside the fundamental score
(docs/plans/fundamentals-v2.md): ROE, ROCE, debt/equity, operating cash flow against
profit by financial year, and EV/EBITDA. Shown on the stock page, not scored: fund-v1 is
unchanged.

The balance sheet and the cash-flow statement come with the half-yearly and annual
filings only (September and March quarters), so the balance sheet used is the latest
one, dated; one older than `BALANCE_STALE_DAYS` is treated as unknown. Banks and NBFCs
file a different form, and borrowing is their business: for them only ROE is given.

Pure module: no database.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from app.fundamentals.score import Quarter, ttm, units_mismatch

BALANCE_STALE_DAYS = 400
CASH_FLOW_YEARS = 3
# A ratio this far out means a filing in the wrong units, not a business.
MAX_RETURN = 2.0


@dataclass(frozen=True)
class CashFlowYear:
    year_end: date  # the March quarter that closes the financial year
    operating_cash_flow: float
    profit: float | None  # the four quarters to that March


@dataclass
class Health:
    balance_sheet_as_of: date | None
    roe: float | None
    roce: float | None
    debt_equity: float | None
    ev_ebitda: float | None
    equity: float | None
    debt: float | None
    cash: float | None
    cash_flow: list[CashFlowYear] = field(default_factory=list)  # newest first
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _sane(value: float | None) -> float | None:
    return value if value is not None and abs(value) <= MAX_RETURN else None


def cash_flow_years(quarters: Sequence[Quarter]) -> list[CashFlowYear]:
    """Operating cash flow of each financial year (from its March filing) and the
    profit of the four quarters to that March, newest first."""
    out = []
    for i, q in enumerate(quarters):
        if q.period_end.month != 3 or q.ocf_ytd is None:
            continue
        out.append(CashFlowYear(q.period_end, q.ocf_ytd, ttm(quarters[: i + 1], "net_profit")))
    return sorted(out, key=lambda y: y.year_end, reverse=True)


def health(quarters: Sequence[Quarter], as_of: date, price: float | None) -> Health:
    """The measures as known on `as_of` from `quarters` (oldest first, as known then)."""
    years = cash_flow_years(quarters)[:CASH_FLOW_YEARS]
    with_balance = [q for q in quarters if q.equity is not None]
    latest = with_balance[-1] if with_balance else None
    out = Health(None, None, None, None, None, None, None, None, cash_flow=years)
    financial = bool(quarters) and quarters[-1].financial
    if latest is None or (as_of - latest.period_end).days > BALANCE_STALE_DAYS:
        out.notes.append(
            "No balance sheet in the last 400 days: it comes with the half-yearly and "
            "annual results (September and March quarters)."
            if latest is None or not quarters
            else f"The latest balance sheet ({latest.period_end}) is over 400 days old."
        )
    else:
        out.balance_sheet_as_of = latest.period_end
        out.equity, out.debt, out.cash = latest.equity, latest.debt, latest.cash
        equity = latest.equity or 0.0
        recent = list(quarters[-4:])
        mismatch = any(units_mismatch(q) for q in recent)
        profit = ttm(quarters, "net_profit")
        if equity > 0 and profit is not None and not mismatch:
            out.roe = _sane(profit / equity)
        if equity <= 0:
            out.warnings.append(
                "Negative or zero shareholders' equity on the latest balance sheet."
            )
        if financial:
            out.notes.append(
                "Bank or NBFC: borrowing is the business, so ROCE, debt/equity and EV/EBITDA "
                "are not shown."
            )
        else:
            debt = latest.debt or 0.0
            pbt = ttm(quarters, "profit_before_tax")
            interest = ttm(quarters, "finance_costs")
            dep = ttm(quarters, "depreciation")
            if pbt is not None and interest is not None and equity + debt > 0 and not mismatch:
                out.roce = _sane((pbt + interest) / (equity + debt))
            if equity > 0 and latest.debt is not None:
                out.debt_equity = debt / equity
            shares = quarters[-1].shares
            if (
                price
                and shares
                and pbt is not None
                and interest is not None
                and dep is not None
                and not mismatch
            ):
                ebitda = pbt + interest + dep
                if ebitda > 0:
                    out.ev_ebitda = (price * shares + debt - (latest.cash or 0.0)) / ebitda
    if financial:
        if years:
            out.notes.append(
                "For a lender, operating cash flow includes the loans it makes, so a negative "
                "figure is normal and no cash-flow warning is given."
            )
    elif len(years) == CASH_FLOW_YEARS and all(y.operating_cash_flow < 0 for y in years):
        out.warnings.append(
            "Operating cash flow negative in each of the last three financial years "
            "(spec section 3's hard reject; shown here, not scored in fund-v1)."
        )
    elif (
        years
        and years[0].profit
        and years[0].profit > 0
        and years[0].operating_cash_flow < 0.5 * years[0].profit
    ):
        out.warnings.append(
            "Operating cash flow was under half the profit in the latest financial year: "
            "profit that isn't turning into cash."
        )
    out.notes.append(
        "Promoter holding and pledges need the shareholding-pattern filings, and valuation "
        "against the sector needs point-in-time sectors: neither is loaded yet."
    )
    return out
