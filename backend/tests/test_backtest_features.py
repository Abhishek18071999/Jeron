"""The backtester's indicator and score series must equal the daily scan's values."""

import math
import random
from datetime import date, timedelta

import numpy as np
import pytest

from app.backtest.features import percentile_ranks, stock_features
from app.scan.score import PriceHistory, score, snapshot
from app.scan.score import percentile_ranks as scan_percentiles


def random_history(seed: int, n: int):
    rng = random.Random(seed)
    dates = [date(2020, 1, 1) + timedelta(days=i) for i in range(n)]
    closes, highs, lows, volumes = [], [], [], []
    price = 100.0
    for _ in range(n):
        price *= math.exp(rng.gauss(0.0005, 0.02))
        closes.append(price)
        highs.append(price * (1 + abs(rng.gauss(0, 0.01))))
        lows.append(price * (1 - abs(rng.gauss(0, 0.01))))
        volumes.append(float(rng.randint(50_000, 500_000)))
    index = {d: 1000 * math.exp(0.0003 * i + 0.05 * math.sin(i / 20)) for i, d in enumerate(dates)}
    # A few index gaps, so relative strength is sometimes undefined.
    for d in dates[::97]:
        index.pop(d)
    return dates, highs, lows, closes, volumes, index


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_series_match_the_scan_snapshot_every_day(seed):
    dates, highs, lows, closes, volumes, index = random_history(seed, 420)
    f = stock_features(dates, highs, lows, closes, volumes, index)
    for t in [210, 260, 300, 333, 380, 419]:
        h = PriceHistory(
            dates[: t + 1], highs[: t + 1], lows[: t + 1], closes[: t + 1], volumes[: t + 1]
        )
        snap = snapshot(h, index)
        for name in (
            "ema20",
            "ema50",
            "ema200",
            "rsi14",
            "atr14",
            "adx14",
            "volume_ratio",
            "avg_volume20",
            "high_52w",
            "rs_3m",
            "rs_6m",
            "last_swing_high",
            "last_swing_low",
        ):
            expected = getattr(snap, name)
            got = getattr(f, name)[t]
            if expected is None:
                assert np.isnan(got), (name, t)
            else:
                assert got == pytest.approx(expected, rel=1e-12), (name, t)
        # Points without relative strength: score() with no percentiles.
        expected_base = sum(c.points for c in score(snap, None, None))
        assert f.base_points[t] == pytest.approx(expected_base), t
        # With relative-strength percentiles the totals agree too.
        full = sum(c.points for c in score(snap, 0.25, 0.75))
        assert f.base_points[t] + 7.5 * 0.25 + 7.5 * 0.75 == pytest.approx(full)


def test_prior_high_excludes_today():
    dates, highs, lows, closes, volumes, index = random_history(5, 300)
    f = stock_features(dates, highs, lows, closes, volumes, index)
    assert f.prior_high_52w[0] != f.prior_high_52w[0]  # NaN on the first day
    assert f.prior_high_52w[299] == max(highs[299 - 252 : 299])


def test_percentile_ranks_match_the_scan():
    rng = random.Random(7)
    values = {f"S{i}": float(rng.choice([1, 2, 2, 3, 5, 8, 8, 8])) for i in range(30)}
    values["NONE"] = None
    expected = scan_percentiles(values)
    keys = list(values)
    arr = np.array([np.nan if values[k] is None else values[k] for k in keys])
    got = percentile_ranks(arr)
    for k, v in zip(keys, got, strict=True):
        if k == "NONE":
            assert np.isnan(v)
        else:
            assert v == pytest.approx(expected[k])
    single = percentile_ranks(np.array([np.nan, 4.0]))
    assert single[1] == 0.5
