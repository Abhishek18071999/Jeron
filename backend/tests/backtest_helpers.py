"""Hand-built markets for backtest tests."""

from datetime import date, timedelta

import numpy as np

from app.backtest.costs import CostModel
from app.backtest.engine import Variant
from app.backtest.market import Market, Regime

NO_COSTS = CostModel(
    name="none",
    stt_pct=0.0,
    exchange_pct=0.0,
    sebi_per_crore=0.0,
    stamp_buy_pct=0.0,
    gst_pct=0.0,
    dp_per_sale=0.0,
    slippage_buckets=((0.0, 0.0),),
)


def weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def one_stock_market(
    bars: list[tuple[float, float, float, float]],
    *,
    atr: float = 2.0,
    band_pct: float = float("nan"),
    median_turnover: float = 2e9,
    avg_volume: float = 1e9,
    symbol: str = "AAA",
) -> Market:
    """A market with one stock whose bars are (open, high, low, close), in the
    universe every day, with a constant ATR and score 90."""
    n = len(bars)
    days = weekdays(date(2024, 1, 1), n)
    o, h, lo, c = (np.array([[b[i] for b in bars]], dtype=float) for i in range(4))

    def full(value: float) -> np.ndarray:
        return np.full((1, n), value)

    return Market(
        days=days,
        symbols=[symbol],
        sectors=[None],
        open=o,
        high=h,
        low=lo,
        close=c,
        factor=full(1.0),
        volume=full(1e6),
        avg_volume20=full(avg_volume),
        median_turnover=full(median_turnover),
        band_pct=full(band_pct),
        dividend=full(0.0),
        universe=np.ones((1, n), dtype=bool),
        score=full(90.0),
        atr14=full(atr),
        ema20=full(np.nan),
        ema50=full(np.nan),
        ema200=full(np.nan),
        rsi14=full(np.nan),
        adx14=full(np.nan),
        plus_di=full(np.nan),
        minus_di=full(np.nan),
        volume_ratio=full(np.nan),
        prior_high_52w=full(np.nan),
        last_swing_low=full(np.nan),
        last_day=np.array([n - 1]),
        nifty500=np.linspace(100, 110, n),
        regime=[Regime.BULL] * n,
        risk_off=np.zeros(n, dtype=bool),
        quality_fail=np.zeros(n, dtype=bool),
        security_list_known=np.ones(n, dtype=bool),
    )


def signal_on(market: Market, *days: int, stop_atr: float = 2.0) -> Variant:
    entries = np.zeros_like(market.universe)
    for d in days:
        entries[0, d] = True
    return Variant("test", {"stop_atr": stop_atr}, entries)


def market_of(
    stocks: dict[str, list[tuple[float, float, float, float]]],
    *,
    sectors: dict[str, str | None] | None = None,
    atr: float = 2.0,
) -> Market:
    """Several stocks on the same days, each like `one_stock_market`'s (constant ATR,
    score 90, always in the universe). `sectors` maps symbol to sector."""
    symbols = list(stocks)
    first = one_stock_market(stocks[symbols[0]], atr=atr, symbol=symbols[0])
    k, n = len(symbols), len(first.days)

    def rows(i: int) -> np.ndarray:
        return np.array([[b[i] for b in stocks[s]] for s in symbols], dtype=float)

    def full(value: float) -> np.ndarray:
        return np.full((k, n), value)

    first.symbols = symbols
    first.sectors = [(sectors or {}).get(s) for s in symbols]
    first.open, first.high, first.low, first.close = rows(0), rows(1), rows(2), rows(3)
    for name in (
        "factor",
        "volume",
        "avg_volume20",
        "median_turnover",
        "band_pct",
        "dividend",
        "score",
        "atr14",
        "ema20",
        "ema50",
        "ema200",
        "rsi14",
        "adx14",
        "plus_di",
        "minus_di",
        "volume_ratio",
        "prior_high_52w",
        "last_swing_low",
    ):
        setattr(first, name, full(float(getattr(first, name)[0, 0])))
    first.universe = np.ones((k, n), dtype=bool)
    first.last_day = np.full(k, n - 1)
    return first


def signals_on(market: Market, day: int, stop_atr: float = 2.0) -> Variant:
    """Every stock signals on `day`."""
    entries = np.zeros_like(market.universe)
    entries[:, day] = True
    return Variant("test", {"stop_atr": stop_atr}, entries)
