import pytest

from app.indicators import atr, ema, rsi, sma

# Wilder's RSI example data as published by StockCharts (first RSI(14) = 70.53).
CLOSES = [
    44.3389, 44.0902, 44.1497, 43.6124, 44.3278, 44.8264, 45.0955, 45.4245, 45.8433,
    46.0826, 45.8931, 46.0328, 45.6140, 46.2820, 46.2820, 46.0028, 46.0328, 46.4116,
    46.2222, 45.6439,
]  # fmt: skip


def test_sma_and_ema():
    assert sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]
    values = ema([1, 2, 3, 4, 5], 3)
    assert values[:2] == [None, None]
    assert values[2] == 2.0  # seeded with the simple average
    assert values[3] == pytest.approx(3.0)  # 4 * 0.5 + 2 * 0.5
    assert ema([1, 2], 3) == [None, None]


def test_rsi_matches_wilders_example():
    values = rsi(CLOSES, 14)
    assert values[13] is None
    assert values[14] == pytest.approx(70.53, abs=0.01)
    assert values[15] == pytest.approx(66.32, abs=0.01)


def test_rsi_all_gains_is_100():
    assert rsi(list(range(1, 17)), 14)[-1] == 100.0


def test_atr_uses_true_range_and_wilder_smoothing():
    highs = [10.0, 11.0, 12.0, 13.0]
    lows = [9.0, 10.0, 11.0, 10.0]
    closes = [9.5, 10.5, 11.5, 12.5]
    # True ranges from day 2: 1.5, 1.5, 3.0; ATR(2) starts at mean(1.5, 1.5).
    assert atr(highs, lows, closes, 2) == [None, None, 1.5, 2.25]
