import pytest

from app.indicators import (
    Pivot,
    adx,
    atr,
    ema,
    pct_change,
    rolling_max,
    rsi,
    sma,
    support_resistance,
    swing_pivots,
    true_range,
    volume_ratio,
)
from app.indicators import macd as ind_macd

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


def test_short_inputs_give_none_not_errors():
    assert ind_macd([1.0] * 10).signal == [None] * 10
    result = adx([2.0] * 5, [1.0] * 5, [1.5] * 5, 14)
    assert result.adx == [None] * 5 and result.plus_di == [None] * 5
    assert true_range([], [], []) == []


def test_adx_of_a_steady_rise_is_strongly_up():
    highs = [10.0 + i for i in range(60)]
    lows = [9.0 + i for i in range(60)]
    closes = [9.5 + i for i in range(60)]
    result = adx(highs, lows, closes, 14)
    assert result.minus_di[-1] == 0.0
    assert result.plus_di[-1] > 40
    assert result.adx[-1] == pytest.approx(100.0)


def test_macd_line_is_fast_minus_slow_ema():
    closes = [100 + (i % 7) * 1.5 + i * 0.2 for i in range(80)]
    result = ind_macd(closes, 12, 26, 9)
    fast, slow = ema(closes, 12), ema(closes, 26)
    assert result.macd[24] is None
    assert result.macd[-1] == pytest.approx(fast[-1] - slow[-1])
    assert result.histogram[-1] == pytest.approx(result.macd[-1] - result.signal[-1])


def test_rolling_max_pct_change_and_volume_ratio():
    assert rolling_max([3, 1, 2, 5, 4], 2) == [3, 3, 2, 5, 5]
    assert pct_change([100, 110, 121], 1) == [None, pytest.approx(0.1), pytest.approx(0.1)]
    volumes = [100.0] * 20 + [300.0]
    ratios = volume_ratio(volumes, 20)
    assert ratios[19] is None  # needs 20 earlier days
    assert ratios[20] == pytest.approx(3.0)


def test_swing_pivots_need_confirmation():
    highs = [1, 2, 3, 9, 3, 2, 1, 2, 3, 4]
    lows = [h - 0.5 for h in highs]
    pivots = swing_pivots(highs, lows, strength=3)
    assert pivots.highs == [Pivot(3, 9)]
    assert pivots.lows == [Pivot(6, 0.5)]
    # Without three bars after it, the same peak is not yet a pivot.
    assert swing_pivots(highs[:6], lows[:6], strength=3).highs == []


def test_support_and_resistance():
    highs = [10, 11, 12, 15, 12, 11, 10, 9, 8, 9, 10, 11, 12, 13, 12.5]
    lows = [h - 1 for h in highs]
    levels = support_resistance(highs, lows, close=12.0, strength=2)
    assert levels.resistance == 15
    assert levels.support == 7
    assert levels.last_swing_high == 15
    assert levels.last_swing_low == 7
    above = support_resistance(highs, lows, close=16.0, strength=2)
    assert above.resistance is None
