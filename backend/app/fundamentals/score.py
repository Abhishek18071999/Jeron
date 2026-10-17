"""The fundamental brain (spec section 3) from quarterly results: growth, consistency,
margins and interest cover for quality, and the price-to-earnings ratio against the
stock's own history for valuation. 0-100, versioned as FUND_SCORE_VERSION: changing the
points or rules means a new version.

What the quarterly filings can't give is said, not guessed: balance-sheet ratios (ROE,
ROCE, debt), operating cash flow and promoter pledges need the half-yearly and
shareholding filings, which are not loaded yet. Of the spec's hard rejects only a
qualified audit opinion can be checked.

Pure module: no database.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

FUND_SCORE_VERSION = "fund-v1"
# The newest quarter must have ended within this many days, else the data is stale
# (results are due 45 days after a quarter, 60 after the year).
STALE_DAYS = 200


@dataclass(frozen=True)
class Quarter:
    """One quarter of a stock's results as known on a day (rupees)."""

    period_end: date
    disseminated_at: datetime  # when NSE published the filing
    consolidated: bool
    revenue: float | None
    net_profit: float | None  # to the parent's owners when reported, else the total
    eps: float | None
    finance_costs: float | None
    depreciation: float | None
    profit_before_tax: float | None
    other_income: float | None
    financial: bool = False  # bank or NBFC form: interest is the business, not a cost
    audit_opinion: str | None = None
    shares: float | None = None  # paid-up capital / face value


def units_mismatch(q: Quarter) -> bool:
    """The filing's EPS and its profit per share differ by more than half: one of them
    was filed in the wrong units (it happens in about 3% of filings)."""
    if q.eps is None or q.net_profit is None or not q.shares or abs(q.eps) < 0.5:
        return False
    return abs(q.net_profit / q.shares / q.eps - 1) > 0.5


def pe_ratio(quarters: Sequence[Quarter], price: float | None) -> float | None:
    """Market value over the last four quarters' profit, with the share count of the
    newest filing (so a split doesn't distort it); EPS when the count is missing. None
    when a filing in the window looks to be in the wrong units."""
    if not price or not quarters or any(units_mismatch(q) for q in quarters[-4:]):
        return None
    profit = ttm(quarters, "net_profit")
    shares = quarters[-1].shares
    if profit is not None and shares:
        return price * shares / profit if profit > 0 else None
    eps = ttm(quarters, "eps")
    return price / eps if eps and eps > 0 else None


@dataclass
class FundScore:
    score: float | None  # None when there is too little data
    quality: float
    valuation: float
    rejected: str | None  # a hard reject, in words
    facts: dict[str, float | None] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    version: str = FUND_SCORE_VERSION


def _consecutive(quarters: Sequence[Quarter]) -> bool:
    """Each quarter ends about three months after the one before."""
    return all(
        80 <= (b.period_end - a.period_end).days <= 100
        for a, b in zip(quarters, quarters[1:], strict=False)
    )


def ttm(quarters: Sequence[Quarter], attr: str, back: int = 0) -> float | None:
    """The sum of four consecutive quarters, `back` quarters before the newest."""
    end = len(quarters) - back
    window = quarters[end - 4 : end] if end >= 4 else []
    if len(window) < 4 or not _consecutive(window):
        return None
    values = [getattr(q, attr) for q in window]
    if any(v is None for v in values):
        return None
    return float(sum(values))


def growth(now: float | None, before: float | None) -> float | None:
    """Fractional growth; None when the base isn't positive."""
    if now is None or before is None or before <= 0:
        return None
    return now / before - 1


def _steps(value: float | None, steps: Sequence[tuple[float, float]]) -> float:
    if value is None:
        return 0.0
    for threshold, points in steps:
        if value >= threshold:
            return points
    return 0.0


def percentile(value: float, history: Sequence[float]) -> float:
    """Share of `history` at or below `value`, 0 to 1."""
    return sum(1 for h in history if h <= value) / len(history)


def fund_score(
    quarters: Sequence[Quarter],
    as_of: date,
    price: float | None,
    pe_history: Sequence[float] = (),
) -> FundScore:
    """Score a stock on `as_of` from the quarters known then (oldest first). `pe_history`
    is its P/E at past quarter ends (up to five years) for the valuation part."""
    notes: list[str] = []
    if not quarters:
        return FundScore(None, 0, 0, None, notes=["No results loaded."])
    newest = quarters[-1]
    if (as_of - newest.period_end).days > STALE_DAYS:
        return FundScore(
            None, 0, 0, None, notes=[f"Newest results are for {newest.period_end}: stale."]
        )
    rejected = None
    for q in quarters[-4:]:
        opinion = (q.audit_opinion or "").lower()
        if "qualif" in opinion and "unqualif" not in opinion and "unmodified" not in opinion:
            rejected = f"Qualified audit opinion on the {q.period_end} results."
    sales = ttm(quarters, "revenue")
    sales_1y = ttm(quarters, "revenue", 4)
    sales_3y = ttm(quarters, "revenue", 12)
    profit = ttm(quarters, "net_profit")
    profit_1y = ttm(quarters, "net_profit", 4)
    eps = ttm(quarters, "eps")
    eps_1y = ttm(quarters, "eps", 4)
    if sales is None or profit is None:
        return FundScore(
            None, 0, 0, rejected, notes=["Fewer than four consecutive quarters loaded."]
        )
    facts: dict[str, float | None] = {
        "sales_ttm": sales,
        "profit_ttm": profit,
        "eps_ttm": eps,
        "sales_growth": growth(sales, sales_1y),
        "eps_growth": growth(eps, eps_1y),
        "sales_cagr_3y": None,
        "margin": profit / sales if sales > 0 else None,
        "margin_1y": profit_1y / sales_1y if profit_1y is not None and sales_1y else None,
        "interest_cover": None,
        "pe": pe_ratio(quarters, price),
    }
    if sales_3y and sales_3y > 0 and sales > 0:
        facts["sales_cagr_3y"] = (sales / sales_3y) ** (1 / 3) - 1
    if sales_1y is None:
        notes.append("Less than two years of results: growth isn't scored.")

    quality = 0.0
    quality += _steps(facts["sales_growth"], [(0.20, 15), (0.10, 10), (0.0, 5)])
    quality += _steps(facts["eps_growth"], [(0.20, 15), (0.10, 10), (0.0, 5)])
    quality += _steps(facts["sales_cagr_3y"], [(0.15, 10), (0.08, 6), (0.0, 3)])
    recent = quarters[-8:]
    profitable = sum(1 for q in recent if q.net_profit is not None and q.net_profit > 0)
    facts["profitable_quarters"] = float(profitable)
    quality += {8: 15.0, 7: 10.0, 6: 5.0}.get(profitable, 0.0) if len(recent) == 8 else 0.0
    if facts["margin"] is not None and facts["margin_1y"] is not None:
        drop = facts["margin_1y"] - facts["margin"]
        quality += 10 if drop <= 0 else 5 if drop <= 0.01 else 0
    if newest.financial:
        quality += 5  # interest is a bank's or lender's business, not a burden
    else:
        finance = ttm(quarters, "finance_costs")
        pbt = ttm(quarters, "profit_before_tax")
        if finance is not None and pbt is not None:
            cover = (pbt + finance) / finance if finance > 0 else None
            facts["interest_cover"] = cover
            quality += 5 if cover is None or cover >= 5 else 2 if cover >= 2 else 0

    valuation = 0.0
    pe = facts["pe"]
    if pe is None and any(units_mismatch(q) for q in quarters[-4:]):
        notes.append(
            "A recent filing's EPS and profit per share disagree (wrong units in the "
            "filing?): P/E not used, no valuation points."
        )
    elif pe is None:
        notes.append("No positive earnings: no valuation points.")
    elif len(pe_history) < 8:
        valuation = 15.0
        notes.append("Under two years of P/E history: valuation scored as average.")
    else:
        p = percentile(pe, pe_history)
        facts["pe_percentile"] = p
        valuation = _steps(-p, [(-0.2, 30), (-0.4, 22), (-0.6, 15), (-0.8, 8)])
    notes.append("Not covered yet: ROE, ROCE, debt, cash flow and pledges.")
    score = round(quality + valuation, 1)
    return FundScore(score, quality, valuation, rejected, facts, notes)


def known_quarters(filings: Sequence[Quarter], before: datetime) -> list[Quarter]:
    """The quarters known at `before`: per quarter the latest filing published before
    it, consolidated preferred over standalone. `filings` are oldest published first;
    the result is oldest quarter first."""
    best: dict[date, Quarter] = {}
    for q in filings:
        if q.disseminated_at >= before:
            continue
        old = best.get(q.period_end)
        if old is None or q.consolidated >= old.consolidated:
            best[q.period_end] = q
    return [best[k] for k in sorted(best)]


def score_with_history(
    quarters: Sequence[Quarter], as_of: date, close_on: dict[date, float]
) -> FundScore:
    """fund-v1 on `as_of` from `quarters` (as `known_quarters` gives them), with the
    P/E at each earlier filing (five years at most) from the raw close on its
    publication day (`close_on`, by date) as the valuation history. The stock page and
    the backtest's point-in-time series both score this way."""
    filed = [q.disseminated_at.date() for q in quarters]
    history = []
    for i in range(max(3, len(quarters) - 20), len(quarters) - 1):
        pe = pe_ratio(quarters[: i + 1], close_on.get(filed[i]))
        if pe is not None:
            history.append(pe)
    return fund_score(quarters, as_of, close_on.get(as_of), history)
