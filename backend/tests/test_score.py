import math
import time
from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.scan.score import (
    MAX_POINTS,
    PriceHistory,
    Snapshot,
    percentile_ranks,
    score,
    snapshot,
    total,
)


def history(closes, volumes=None, start=date(2024, 1, 1)):
    dates = [start + timedelta(days=i) for i in range(len(closes))]
    return PriceHistory(
        dates=dates,
        highs=[c * 1.01 for c in closes],
        lows=[c * 0.99 for c in closes],
        closes=list(closes),
        volumes=volumes or [100_000.0] * len(closes),
    )


def flat_index(h, value=1000.0):
    return dict.fromkeys(h.dates, value)


def base_snapshot(**overrides) -> Snapshot:
    values = dict(
        sessions=300,
        close=110.0,
        prev_close=100.0,
        ema20=105.0,
        ema50=100.0,
        ema200=90.0,
        rsi14=60.0,
        macd=2.0,
        macd_signal=1.0,
        macd_hist=1.0,
        adx14=25.0,
        plus_di=30.0,
        minus_di=15.0,
        atr14=3.0,
        atr_pct=3.0,
        volume=200_000.0,
        avg_volume20=100_000.0,
        volume_ratio=2.0,
        high_52w=112.0,
        below_52w_high_pct=1.8,
        return_3m=0.2,
        return_6m=0.3,
        rs_3m=0.1,
        rs_6m=0.2,
        support=100.0,
        resistance=120.0,
        last_swing_high=108.0,
        last_swing_low=95.0,
    )
    return Snapshot(**(values | overrides))


def points(components):
    return {c.key: c.points for c in components}


def test_max_points_add_up_to_100():
    assert sum(MAX_POINTS.values()) == 100
    assert total(score(base_snapshot(), 1.0, 1.0)) == 100.0


@pytest.mark.parametrize(
    ("overrides", "key", "expected"),
    [
        ({"ema200": 120.0}, "trend_200", 0),
        ({"ema200": None}, "trend_200", 0),
        ({"ema20": 99.0}, "ema_stack", 0),
        ({"rsi14": 45.0}, "rsi", 5),
        ({"rsi14": 75.0}, "rsi", 5),
        ({"rsi14": 85.0}, "rsi", 0),
        ({"rsi14": 30.0}, "rsi", 0),
        ({"macd": 0.5}, "macd", 5),  # above zero, below signal
        ({"macd": -1.0, "macd_signal": -2.0}, "macd", 5),  # above signal, below zero
        ({"macd": -3.0}, "macd", 0),
        ({"adx14": 18.0}, "adx", 0),
        ({"plus_di": 10.0}, "adx", 0),  # trending, but down
        ({"volume_ratio": 1.4}, "volume", 0),
        ({"prev_close": 111.0}, "volume", 0),  # high volume on a down day
        ({"below_52w_high_pct": 10.0}, "near_high", 5),
        ({"below_52w_high_pct": 30.0}, "near_high", 0),
        ({"atr_pct": 0.5}, "atr", 0),
        ({"atr_pct": 9.0}, "atr", 0),
        ({"last_swing_high": 115.0}, "breakout", 0),
        ({"last_swing_high": None}, "breakout", 0),
    ],
)
def test_components(overrides, key, expected):
    assert points(score(base_snapshot(**overrides), 1.0, 1.0))[key] == expected


def test_relative_strength_points_follow_the_percentile():
    p = points(score(base_snapshot(), 0.5, 0.0))
    assert p["rs_3m"] == 3.75
    assert p["rs_6m"] == 0
    assert points(score(base_snapshot(), None, None))["rs_3m"] == 0


def test_percentile_ranks():
    assert percentile_ranks({}) == {}
    assert percentile_ranks({"A": 1.0}) == {"A": 0.5}
    assert percentile_ranks({"A": 1.0, "B": 2.0, "C": 3.0, "D": None}) == {
        "A": 0.0,
        "B": 0.5,
        "C": 1.0,
    }
    tied = percentile_ranks({"A": 1.0, "B": 1.0, "C": 3.0})
    assert tied["A"] == tied["B"] == 0.25


def test_snapshot_of_a_steady_uptrend():
    closes = [100 * 1.002**i for i in range(300)]
    h = history(closes)
    s = snapshot(h, flat_index(h))
    assert s.sessions == 300
    assert s.ema20 > s.ema50 > s.ema200
    assert s.close > s.ema200
    assert s.rsi14 == 100.0  # never a down day
    assert s.below_52w_high_pct == pytest.approx((1 - 1 / 1.01) * 100)
    assert s.return_3m == pytest.approx(1.002**63 - 1)
    assert s.rs_3m == pytest.approx(s.return_3m)  # the index is flat
    assert s.volume_ratio == pytest.approx(1.0)
    p = points(score(s, 1.0, 1.0))
    assert p["trend_200"] == 15 and p["ema_stack"] == 10 and p["near_high"] == 10
    assert p["rsi"] == 0  # RSI 100 is overbought


def test_relative_strength_uses_the_index_on_the_same_dates():
    closes = [100.0] * 200 + [110.0]
    h = history(closes)
    index = {d: 1000.0 for d in h.dates}
    index[h.dates[-1]] = 1100.0  # index also up 10%
    s = snapshot(h, index)
    assert s.return_3m == pytest.approx(0.1)
    assert s.rs_3m == pytest.approx(0.0)
    missing = snapshot(h, {})
    assert missing.rs_3m is None and missing.return_3m == pytest.approx(0.1)


def test_snapshot_values_are_json_friendly():
    h = history([100 + math.sin(i / 5) * 5 for i in range(260)])
    data = snapshot(h, flat_index(h)).to_dict()
    assert data["sessions"] == 260
    assert all(v is None or isinstance(v, int | float) for v in data.values())
    assert replace(base_snapshot(), close=1.23456789).to_dict()["close"] == 1.2346


def test_scoring_a_full_universe_is_fast():
    """Indicators and scores for 2,000 stocks x 450 sessions, the scan's compute part."""
    closes = [100 * math.exp(0.01 * math.sin(i / 7) + 0.0005 * i) for i in range(450)]
    h = history(closes)
    index = flat_index(h)
    started = time.perf_counter()
    snaps = [snapshot(h, index) for _ in range(2000)]
    ranks = percentile_ranks({str(i): s.rs_3m for i, s in enumerate(snaps)})
    for i, s in enumerate(snaps):
        score(s, ranks[str(i)], ranks[str(i)])
    assert time.perf_counter() - started < 120  # spec budget for the whole scan: 5 minutes
