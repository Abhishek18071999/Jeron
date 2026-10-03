from datetime import date

import pytest

from app.backtest.costs import CRORE, CostModel, Realised, estimate_tax, financial_year


def test_delivery_charges_on_one_lakh():
    model = CostModel()
    buy = model.charges(100_000, "buy")
    assert buy.stt == pytest.approx(100.0)
    assert buy.exchange == pytest.approx(2.97)
    assert buy.sebi == pytest.approx(0.10)
    assert buy.stamp == pytest.approx(15.0)
    assert buy.gst == pytest.approx(0.18 * (2.97 + 0.10))
    assert buy.dp == 0
    assert buy.total == pytest.approx(118.6226)
    sell = model.charges(100_000, "sell")
    assert sell.stamp == 0
    assert sell.dp == pytest.approx(15.34)
    assert sell.total == pytest.approx(100 + 2.97 + 0.10 + 0.5526 + 15.34)


def test_brokerage_cap():
    model = CostModel(brokerage_pct=0.1, brokerage_max=20.0)
    assert model.charges(100_000, "buy").brokerage == 20.0
    assert model.charges(10_000, "buy").brokerage == pytest.approx(10.0)


def test_slippage_buckets():
    model = CostModel()
    assert model.slippage_pct(150 * CRORE) == 0.05
    assert model.slippage_pct(100 * CRORE) == 0.05
    assert model.slippage_pct(50 * CRORE) == 0.10
    assert model.slippage_pct(6 * CRORE) == 0.20
    assert model.slippage_pct(1 * CRORE) == 0.50


def test_financial_year():
    assert financial_year(date(2025, 3, 31)) == 2024
    assert financial_year(date(2025, 4, 1)) == 2025


def test_tax_estimate_rates_and_set_off():
    sales = [
        Realised(date(2023, 6, 1), 50_000, 30),  # FY2023 short-term gain, 15%
        Realised(date(2023, 7, 1), -20_000, 30),  # short-term loss offsets it
        Realised(date(2024, 9, 1), 200_000, 400),  # FY2024 long-term, after the change
        Realised(date(2024, 10, 1), 10_000, 10),  # FY2024 short-term at 20%
    ]
    est = estimate_tax(sales, [(date(2024, 8, 1), 1_000.0)])
    y2023, y2024 = est.years
    assert y2023.tax == pytest.approx(30_000 * 0.15)
    expected_2024 = 10_000 * 0.20 + (200_000 - 125_000) * 0.125 + 1_000 * 0.30
    assert y2024.tax == pytest.approx(expected_2024)
    assert est.total == pytest.approx(30_000 * 0.15 + expected_2024)


def test_losses_carry_forward():
    sales = [
        Realised(date(2022, 6, 1), -40_000, 30),
        Realised(date(2023, 6, 1), 30_000, 30),
        Realised(date(2024, 6, 1), 30_000, 30),
    ]
    years = estimate_tax(sales).years
    assert years[0].tax == 0 and years[0].loss_carried == 40_000
    assert years[1].tax == 0 and years[1].loss_carried == 10_000
    assert years[2].tax == pytest.approx(20_000 * 0.15)  # sold before 23 July 2024


def test_interest_on_idle_cash_is_taxed_at_the_slab():
    est = estimate_tax([], interest=[(date(2024, 5, 1), 10_000.0), (date(2025, 3, 1), 5_000.0)])
    (year,) = est.years
    assert year.interest == 15_000.0
    assert est.total == pytest.approx(4_500.0)
