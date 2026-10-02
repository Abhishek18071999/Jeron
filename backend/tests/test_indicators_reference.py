"""Indicators against TA-Lib, the reference library (spec M2 acceptance).

Run on a real NSE price series (RELIANCE, three years of daily bars, adjusted for the
2024 bonus) and on random walks. Indicators that are exact copies of TA-Lib's maths
(SMA, EMA, RSI, ATR) must match from their first value; MACD and ADX are seeded a
little differently by TA-Lib, which fades out after a warm-up, so they are compared
after `WARMUP` bars, which every scan has.
"""

import csv
import math
import random
from pathlib import Path

import numpy as np
import pytest

import app.indicators as ind

talib = pytest.importorskip("talib")

FIXTURE = Path(__file__).parent / "fixtures" / "reliance_daily.csv"
WARMUP = 250
TOLERANCE = 1e-6


def _real():
    with FIXTURE.open() as f:
        rows = list(csv.DictReader(f))
    return tuple([float(r[k]) for r in rows] for k in ("high", "low", "close", "volume"))


def _random_walk(seed: int, n: int = 600):
    rng = random.Random(seed)
    close, highs, lows, closes = 100.0, [], [], []
    for _ in range(n):
        close *= math.exp(rng.gauss(0, 0.02))
        highs.append(close * (1 + abs(rng.gauss(0, 0.01))))
        lows.append(close * (1 - abs(rng.gauss(0, 0.01))))
        closes.append(close)
    volumes = [float(rng.randint(1_000, 1_000_000)) for _ in range(n)]
    return highs, lows, closes, volumes


SERIES = {"reliance": _real(), "walk1": _random_walk(1), "walk2": _random_walk(2)}


def _compare(ours, reference, start=0):
    reference = list(reference)
    assert len(ours) == len(reference)
    checked = 0
    for i, (a, b) in enumerate(zip(ours, reference, strict=True)):
        if i < start or np.isnan(b):
            continue
        assert a is not None, f"index {i}: ours is None, TA-Lib has {b}"
        assert a == pytest.approx(b, rel=TOLERANCE, abs=TOLERANCE), f"index {i}"
        checked += 1
    assert checked > 100


def _first_defined(values):
    return next(i for i, v in enumerate(values) if v is not None)


@pytest.mark.parametrize("name", SERIES)
@pytest.mark.parametrize("period", [20, 50, 200])
def test_sma_and_ema_match_talib(name, period):
    _, _, closes, _ = SERIES[name]
    c = np.array(closes)
    _compare(ind.sma(closes, period), talib.SMA(c, period))
    ours = ind.ema(closes, period)
    _compare(ours, talib.EMA(c, period))
    assert _first_defined(ours) == period - 1


@pytest.mark.parametrize("name", SERIES)
def test_rsi_matches_talib(name):
    _, _, closes, _ = SERIES[name]
    ours = ind.rsi(closes, 14)
    _compare(ours, talib.RSI(np.array(closes), 14))
    assert _first_defined(ours) == 14


@pytest.mark.parametrize("name", SERIES)
def test_atr_matches_talib(name):
    h, lo, c, _ = (np.array(s) for s in SERIES[name])
    ours = ind.atr(list(h), list(lo), list(c), 14)
    _compare(ours, talib.ATR(h, lo, c, 14))
    assert _first_defined(ours) == 14


@pytest.mark.parametrize("name", SERIES)
def test_macd_matches_talib_after_warmup(name):
    _, _, closes, _ = SERIES[name]
    ours = ind.macd(closes)
    line, signal, hist = talib.MACD(np.array(closes), 12, 26, 9)
    _compare(ours.macd, line, WARMUP)
    _compare(ours.signal, signal, WARMUP)
    _compare(ours.histogram, hist, WARMUP)
    assert _first_defined(ours.signal) == 33  # same first bar as TA-Lib


@pytest.mark.parametrize("name", SERIES)
def test_adx_and_directional_indicators_match_talib_after_warmup(name):
    h, lo, c, _ = (np.array(s) for s in SERIES[name])
    ours = ind.adx(list(h), list(lo), list(c), 14)
    _compare(ours.plus_di, talib.PLUS_DI(h, lo, c, 14), WARMUP)
    _compare(ours.minus_di, talib.MINUS_DI(h, lo, c, 14), WARMUP)
    _compare(ours.adx, talib.ADX(h, lo, c, 14), WARMUP)
    assert _first_defined(ours.plus_di) == 14
    assert _first_defined(ours.adx) == 27  # same first bar as TA-Lib


@pytest.mark.parametrize("name", SERIES)
def test_rolling_max_and_rate_of_change_match_talib(name):
    h, _, c, _ = SERIES[name]
    _compare(ind.rolling_max(h, 252), talib.MAX(np.array(h), 252))
    _compare(ind.pct_change(c, 63), talib.ROCR(np.array(c), 63) - 1)


@pytest.mark.parametrize("name", SERIES)
def test_volume_ratio_uses_the_previous_20_days(name):
    _, _, _, v = SERIES[name]
    avg = talib.SMA(np.array(v), 20)
    expected = [np.nan] + [v[i] / avg[i - 1] for i in range(1, len(v))]
    _compare(ind.volume_ratio(v, 20), expected)
