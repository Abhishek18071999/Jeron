"""value-trend-v1 (docs/plans/value-trend-v1.md): the point-in-time earnings yield, the
value rank, entries in the cheapest fifth with a positive 12-1 return, the exit above the
median."""

from dataclasses import replace
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from app.backtest.market import _IST, earnings_yields, value_ranks
from app.backtest.strategies import (
    STRATEGIES,
    VALUE_EXIT_ABOVE,
    VALUE_MAX_RANK,
    VALUE_TREND,
    Tier,
    rebalance_days,
)
from app.fundamentals.score import Quarter
from tests.backtest_helpers import market_of

DAYS = [date(2024, 1, 1) + timedelta(days=i) for i in range(400)]
ENDS = [date(2023, 3, 31), date(2023, 6, 30), date(2023, 9, 30), date(2023, 12, 31)]


def quarter(end: date, filed: date, profit: float, shares: float = 100.0) -> Quarter:
    return Quarter(
        period_end=end,
        disseminated_at=datetime(filed.year, filed.month, filed.day, 18, 0, tzinfo=_IST),
        consolidated=True,
        revenue=profit * 10,
        net_profit=profit,
        eps=profit / shares,
        finance_costs=0.0,
        depreciation=0.0,
        profit_before_tax=profit,
        other_income=0.0,
        shares=shares,
    )


def filings(last_filed: date, profit: float = 250.0) -> list[Quarter]:
    early = date(2023, 12, 1)
    return [quarter(e, early, profit) for e in ENDS[:3]] + [quarter(ENDS[3], last_filed, profit)]


def test_the_yield_is_known_only_after_the_filing_is_published():
    filed = DAYS[30]
    raw = np.full((1, len(DAYS)), 100.0)
    ey = earnings_yields(DAYS, ["A"], {"A": filings(filed)}, raw, raw)
    assert ey is not None
    # Three quarters are not a year of profit: nothing until the fourth is published.
    assert np.all(np.isnan(ey[0, :31]))
    # Four quarters of 250 on 100 shares is 10 a share; at a price of 100 that is 10%.
    assert ey[0, 31] == pytest.approx(0.10)


def test_the_yield_moves_with_the_price_and_survives_a_split():
    filed = DAYS[30]
    raw = np.full((1, len(DAYS)), 100.0)
    raw[0, 60:] = 50.0  # a 1:1 bonus on day 60: the raw price halves
    adjusted = np.full((1, len(DAYS)), 50.0)  # the adjusted price never moved
    adjusted[0, 90:] = 100.0  # then the stock really doubles
    ey = earnings_yields(DAYS, ["A"], {"A": filings(filed)}, raw, adjusted)
    assert ey is not None
    assert ey[0, 59] == pytest.approx(0.10) and ey[0, 61] == pytest.approx(0.10)
    assert ey[0, 95] == pytest.approx(0.05)


def test_a_loss_or_stale_results_have_no_yield():
    filed = DAYS[30]
    raw = np.full((2, len(DAYS)), 100.0)
    ey = earnings_yields(
        DAYS, ["A", "B"], {"A": filings(filed, profit=-5.0), "B": filings(filed)}, raw, raw
    )
    assert ey is not None
    assert np.all(np.isnan(ey[0]))
    # The newest quarter ended 2023-12-31: unknown again more than 200 days later.
    assert not np.isnan(ey[1, 150]) and np.isnan(ey[1, 250])
    assert earnings_yields(DAYS, ["A"], None, raw[:1], raw[:1]) is None


def test_the_cheapest_stock_ranks_first_and_unknowns_are_left_out():
    ey = np.array([[0.12], [0.06], [0.03], [np.nan], [0.20]])
    universe = np.array([[True], [True], [True], [True], [False]])
    rank = value_ranks(ey, universe)
    assert rank[:3, 0].tolist() == [0.0, 0.5, 1.0]
    assert np.isnan(rank[3, 0]) and np.isnan(rank[4, 0])


def cheap(n: int = 70):
    bars = [(100.0, 101.0, 99.0, 100.0)] * n
    m = market_of({"A": bars, "B": bars, "C": bars, "D": bars})
    m.value_rank = np.array([[0.05] * n, [0.05] * n, [0.3] * n, [0.8] * n])
    m.earnings_yield = np.full((4, n), 0.08)
    m.mom_return = np.array([[0.2] * n, [-0.1] * n, [0.2] * n, [0.2] * n])
    return m


def test_entries_are_cheap_and_rising_on_rebalance_days():
    m = cheap()
    entries = VALUE_TREND.entries(m, VALUE_TREND.default)
    first = rebalance_days(m)[0]
    assert first.sum() >= 2
    assert entries[0].tolist() == first.tolist()
    assert not entries[1].any()  # cheap but falling
    assert not entries[2].any() and not entries[3].any()  # not cheap enough
    assert VALUE_MAX_RANK == 0.20


def test_the_exit_is_leaving_the_cheaper_half():
    m = cheap()
    m.value_rank[0, :] = np.nan  # unknown is not an exit
    exits = VALUE_TREND.exits(m, VALUE_TREND.default)
    assert exits is not None
    first = rebalance_days(m)[0]
    assert not exits.when[0].any() and not exits.when[2].any()
    assert exits.when[3].tolist() == first.tolist()
    assert VALUE_EXIT_ABOVE == 0.50


def test_a_new_invest_strategy_with_one_grid_point():
    s = STRATEGIES["value-trend"]
    assert s is VALUE_TREND and s.version == "value-trend-v1"
    assert s.tier is Tier.INVEST and s.grid == [s.default]
    assert s.registered_on == date(2026, 11, 11) and not s.single_regime
    with pytest.raises(ValueError, match="earnings yields"):
        s.entries(replace(cheap(), value_rank=None), s.default)
