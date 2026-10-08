"""Market data for a backtest, aligned on one calendar of NSE sessions.

Each stock's adjusted bars, indicator series, universe flag and tech-v1 score sit in
arrays shaped (stocks, days), with NaN on days the stock didn't trade. The universe
rules and the score are the daily scan's (`app.scan.universe`, `app.scan.score`),
applied to every day using only data up to that day, so a backtest trades the same
stocks the scan would have shown.

Pure module: the database job (`app.backtest.job`) builds the inputs.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum

import numpy as np

from app import indicators as ind
from app.backtest.features import NAN, Array, percentile_ranks, stock_features
from app.data.events import ResultsDate, blackout_signal_days
from app.news.labels import SCORE_HORIZON_HALF_LIVES, SCORE_SCALE, SCORE_WEIGHTS, DatedLabel
from app.scan.score import MAX_POINTS
from app.scan.universe import UniverseRules

# A security list counts for this many calendar days (as in the scan).
SECURITY_LIST_MAX_AGE_DAYS = 7
# VIX is "in its top decile" against this many sessions before the day.
VIX_LOOKBACK_SESSIONS = 1260
VIX_MIN_SESSIONS = 250
REGIME_SLOPE_SESSIONS = 20

# Strategies v3 (docs/plans/strategies-v3.md). NSE sectoral indices with history from
# 2016; a stock's sector is the one its excess returns follow most closely.
SECTOR_INDICES = (
    "Nifty Auto",
    "Nifty Financial Services",
    "Nifty PSU Bank",
    "Nifty Energy",
    "Nifty FMCG",
    "Nifty IT",
    "Nifty Media",
    "Nifty Metal",
    "Nifty Pharma",
    "Nifty Realty",
)
SECTOR_ASSIGN_EVERY = 21
SECTOR_LOOKBACK_SESSIONS = 252
SECTOR_MIN_RETURNS = 200
SECTOR_MIN_CORRELATION = 0.2
SECTOR_STRENGTH_SESSIONS = 63


class Regime(StrEnum):
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"


REGIME_RULES = {
    Regime.BULL: "Nifty 500 above its 200-day EMA and the EMA higher than 20 sessions before",
    Regime.BEAR: "Nifty 500 below its 200-day EMA and the EMA lower than 20 sessions before",
    Regime.SIDEWAYS: "Anything else",
}


@dataclass
class StockData:
    """One stock's bars on its own sessions (oldest first). Prices and volumes are
    split- and bonus-adjusted; raw price = adjusted price / factor."""

    symbol: str
    dates: list[date]
    open: Array
    high: Array
    low: Array
    close: Array
    volume: Array
    factor: Array
    turnover: Array  # rupees, raw; NaN if not reported
    eq_series: Array  # bool: traded in the EQ series that day
    dividends: dict[date, float] = field(default_factory=dict)  # raw rupees per share
    sector: str | None = None


@dataclass
class SecurityStatusDay:
    band_pct: float | None  # None = no band
    gsm: bool


@dataclass
class MarketInputs:
    days: list[date]
    stocks: list[StockData]
    nifty500: Mapping[date, float]
    nifty50: Mapping[date, float]
    vix: Mapping[date, float]
    # Security list days (dates NSE published one) and each stock's status on them.
    security_list_days: Sequence[date] = ()
    security_status: Mapping[str, Mapping[date, SecurityStatusDay]] = field(default_factory=dict)
    # ASM periods per symbol: (start, end or None).
    asm: Mapping[str, Sequence[tuple[date, date | None]]] = field(default_factory=dict)
    quality_fail_days: frozenset[date] = frozenset()
    # Results board meetings per symbol; None = the results calendar isn't loaded.
    results: Mapping[str, Sequence[ResultsDate]] | None = None
    # The last day upcoming meetings were downloaded.
    results_updated: date | None = None
    # News labels with a sentiment per symbol, from `news_labeller`; None = no labels.
    news: Mapping[str, Sequence[DatedLabel]] | None = None
    news_labeller: str | None = None
    # Closes of the sectoral indices in `SECTOR_INDICES`, by index name.
    sector_indices: Mapping[str, Mapping[date, float]] = field(default_factory=dict)


@dataclass
class Market:
    days: list[date]
    symbols: list[str]
    sectors: list[str | None]
    open: Array
    high: Array
    low: Array
    close: Array
    factor: Array
    volume: Array
    avg_volume20: Array
    median_turnover: Array
    band_pct: Array  # NaN = unknown or no band
    dividend: Array  # rupees per adjusted share on ex-dates, else 0
    universe: Array  # bool
    score: Array  # tech-v1, NaN outside the universe
    atr14: Array
    ema20: Array
    ema50: Array
    ema200: Array
    rsi14: Array
    adx14: Array
    plus_di: Array
    minus_di: Array
    volume_ratio: Array
    prior_high_52w: Array
    last_swing_low: Array
    last_day: Array  # index of each stock's last session (int)
    nifty500: Array
    regime: list[Regime]
    risk_off: Array  # bool per day: Nifty 50 below 200-EMA or VIX in its top decile
    quality_fail: Array  # bool per day
    security_list_known: Array  # bool per day
    exclusions: dict[str, int] = field(default_factory=dict)
    # 6-month relative strength as a percentile (0-1) among the universe that day, the
    # ranking behind tech-v1's RS points. NaN outside the universe.
    rs6_rank: Array | None = None
    # bool (stocks, days): a signal that day would fill in a results blackout. None =
    # the results calendar isn't loaded.
    results_blackout: Array | None = None
    results: Mapping[str, Sequence[ResultsDate]] | None = None
    results_updated: date | None = None
    # News score 0-100 (50 = no news) per stock and day; None = no news labels.
    news_score: Array | None = None
    news_labeller: str | None = None
    # Strategies v3. Highest high of the 50 sessions before each day.
    prior_high_50: Array | None = None
    # Rank (1 = strongest) of the stock's measured sector that day; NaN = no sector.
    sector_rank: Array | None = None
    # On the session after a results meeting: the stock's return from the close before
    # the meeting session, minus Nifty 500's (`results_reactions`). NaN on other days.
    results_reaction: Array | None = None
    # The higher volume ratio of the meeting session and the session after it.
    results_volume_ratio: Array | None = None

    @property
    def traded(self) -> Array:
        return ~np.isnan(self.close)

    def regime_is(self, *regimes: Regime) -> Array:
        """Bool per day, shaped (1, days) to broadcast over stocks."""
        return np.array([[r in regimes for r in self.regime]], dtype=bool)

    def day_index(self, day: date) -> int:
        """Index of the first session on or after `day`."""
        return int(np.searchsorted(np.array(self.days, dtype="datetime64[D]"), np.datetime64(day)))


def _aligned(index: dict[date, int], dates: Sequence[date], values: Array, n: int) -> Array:
    out = np.full(n, NAN)
    pos = [index[d] for d in dates]
    out[pos] = values
    return out


def _ffill(values: Array) -> Array:
    out = values.copy()
    last = NAN
    for i, v in enumerate(out):
        if np.isnan(v):
            out[i] = last
        else:
            last = v
    return out


def _index_series(days: Sequence[date], closes: Mapping[date, float]) -> Array:
    return _ffill(np.array([closes.get(d, NAN) for d in days], dtype=float))


def _regimes(nifty500: Array) -> list[Regime]:
    closes = np.nan_to_num(_ffill(nifty500), nan=0.0)
    first = int(np.argmax(closes > 0)) if np.any(closes > 0) else len(closes)
    ema = np.full(len(closes), NAN)
    if len(closes) - first >= 200:
        ema[first:] = np.array(
            [NAN if v is None else v for v in ind.ema(list(closes[first:]), 200)]
        )
    out = []
    for t in range(len(closes)):
        e, c = ema[t], closes[t]
        prior = ema[t - REGIME_SLOPE_SESSIONS] if t >= REGIME_SLOPE_SESSIONS else NAN
        if np.isnan(e) or np.isnan(prior):
            out.append(Regime.SIDEWAYS)
        elif c > e and e > prior:
            out.append(Regime.BULL)
        elif c < e and e < prior:
            out.append(Regime.BEAR)
        else:
            out.append(Regime.SIDEWAYS)
    return out


def _risk_off(nifty50: Array, vix: Array) -> Array:
    """Spec section 3's regime filter: Nifty 50 below its 200-day EMA, or India VIX in
    the top decile of its last five years (at least one year needed)."""
    n = len(nifty50)
    out = np.zeros(n, dtype=bool)
    closes = _ffill(nifty50)
    defined = np.flatnonzero(~np.isnan(closes))
    if len(defined):
        first = defined[0]
        ema = ind.ema(list(closes[first:]), 200)
        for j, e in enumerate(ema):
            if e is not None and closes[first + j] < e:
                out[first + j] = True
    v = _ffill(vix)
    for t in range(n):
        if np.isnan(v[t]):
            continue
        window = v[max(0, t - VIX_LOOKBACK_SESSIONS) : t]
        window = window[~np.isnan(window)]
        if len(window) >= VIX_MIN_SESSIONS and v[t] >= np.quantile(window, 0.9):
            out[t] = True
    return out


def _rolling_nanmedian(values: Array, window: int) -> Array:
    out = np.full(len(values), NAN)
    if len(values) == 0:
        return out
    padded = np.concatenate([np.full(window - 1, NAN), values])
    view = np.lib.stride_tricks.sliding_window_view(padded, window)
    has = ~np.all(np.isnan(view), axis=1)
    out[has] = np.nanmedian(view[has], axis=1)
    return out


def build_market(inputs: MarketInputs, rules: UniverseRules | None = None) -> Market:
    rules = rules or UniverseRules()
    days = list(inputs.days)
    index = {d: i for i, d in enumerate(days)}
    s_count, d_count = len(inputs.stocks), len(days)

    def blank() -> Array:
        return np.full((s_count, d_count), NAN)

    open_, high, low, close, factor, volume = (blank() for _ in range(6))
    avg_vol, med_turn, band, atr = blank(), blank(), blank(), blank()
    ema20, ema50, ema200, rsi14, adx14 = (blank() for _ in range(5))
    plus_di, minus_di, vol_ratio, prior_high, swing_low = (blank() for _ in range(5))
    prior_high_50 = blank()
    base, rs3, rs6 = blank(), blank(), blank()
    dividend = np.zeros((s_count, d_count))
    eligible = np.zeros((s_count, d_count), dtype=bool)
    last_day = np.full(s_count, -1, dtype=int)
    exclusions = {"not_eq_series": 0, "low_price": 0, "low_turnover": 0, "gsm": 0, "asm": 0}
    exclusions["short_history"] = 0

    nifty500 = _index_series(days, inputs.nifty500)
    n500 = {d: float(v) for d, v in inputs.nifty500.items()}
    sec_days = sorted(inputs.security_list_days)
    sec_idx = (
        np.searchsorted(
            np.array(sec_days, dtype="datetime64[D]"),
            np.array(days, dtype="datetime64[D]"),
            side="right",
        )
        - 1
    )
    list_for_day: list[date | None] = []
    for t, d in enumerate(days):
        j = sec_idx[t]
        listed = sec_days[j] if j >= 0 else None
        if listed is not None and d - listed >= timedelta(days=SECURITY_LIST_MAX_AGE_DAYS):
            listed = None
        list_for_day.append(listed)
    security_list_known = np.array([x is not None for x in list_for_day])

    for s, stock in enumerate(inputs.stocks):
        pos = np.array([index[d] for d in stock.dates], dtype=int)
        if len(pos) == 0:
            continue
        last_day[s] = pos[-1]
        open_[s, pos], high[s, pos], low[s, pos] = stock.open, stock.high, stock.low
        close[s, pos], factor[s, pos], volume[s, pos] = stock.close, stock.factor, stock.volume
        f = stock_features(stock.dates, stock.high, stock.low, stock.close, stock.volume, n500)
        for target, values in (
            (avg_vol, f.avg_volume20),
            (atr, f.atr14),
            (ema20, f.ema20),
            (ema50, f.ema50),
            (ema200, f.ema200),
            (rsi14, f.rsi14),
            (adx14, f.adx14),
            (plus_di, f.plus_di),
            (minus_di, f.minus_di),
            (vol_ratio, f.volume_ratio),
            (prior_high, f.prior_high_52w),
            (prior_high_50, f.prior_high_50),
            (swing_low, f.last_swing_low),
            (base, f.base_points),
            (rs3, f.rs_3m),
            (rs6, f.rs_6m),
        ):
            target[s, pos] = values
        turnover = np.full(d_count, NAN)
        turnover[pos] = stock.turnover
        med_turn[s] = _rolling_nanmedian(turnover, rules.turnover_sessions)
        for ex_date, amount in stock.dividends.items():
            if ex_date in index and not np.isnan(factor[s, index[ex_date]]):
                dividend[s, index[ex_date]] = amount * factor[s, index[ex_date]]

        statuses = inputs.security_status.get(stock.symbol, {})
        gsm = np.zeros(d_count, dtype=bool)
        for t, listed in enumerate(list_for_day):
            if listed is not None:
                st = statuses.get(listed)
                if st is not None:
                    gsm[t] = st.gsm
                    band[s, t] = NAN if st.band_pct is None else st.band_pct
        asm = np.zeros(d_count, dtype=bool)
        for start, end in inputs.asm.get(stock.symbol, []):
            for t, d in enumerate(days):
                if d >= start and (end is None or d < end):
                    asm[t] = True

        traded = np.zeros(d_count, dtype=bool)
        traded[pos] = True
        eq = np.zeros(d_count, dtype=bool)
        eq[pos] = stock.eq_series.astype(bool)
        history = np.zeros(d_count, dtype=int)
        history[pos] = np.arange(1, len(pos) + 1)
        with np.errstate(invalid="ignore"):
            raw_close = close[s] / factor[s]
            price_ok = raw_close >= float(rules.min_price)
            turnover_ok = med_turn[s] >= float(rules.min_median_turnover)
        checks = (
            ("not_eq_series", eq),
            ("low_price", price_ok),
            ("low_turnover", turnover_ok),
            ("gsm", ~gsm),
            ("asm", ~asm),
            ("short_history", history >= rules.min_history),
        )
        ok = traded.copy()
        for name, passed in checks:
            exclusions[name] += int(np.sum(ok & ~passed))
            ok &= passed
        eligible[s] = ok

    score = np.full((s_count, d_count), NAN)
    rs6_rank = np.full((s_count, d_count), NAN)
    half = MAX_POINTS["rs_3m"]
    for t in range(d_count):
        members = np.flatnonzero(eligible[:, t])
        if len(members) == 0:
            continue
        p3 = np.nan_to_num(percentile_ranks(rs3[members, t]), nan=0.0)
        ranks6 = percentile_ranks(rs6[members, t])
        rs6_rank[members, t] = ranks6
        p6 = np.nan_to_num(ranks6, nan=0.0)
        score[members, t] = np.round(base[members, t] + half * p3 + MAX_POINTS["rs_6m"] * p6, 1)

    symbols = [s.symbol for s in inputs.stocks]
    reactions = results_reactions(days, symbols, inputs.results, close, vol_ratio, nifty500)
    sector_closes = [_index_series(days, inputs.sector_indices.get(n, {})) for n in SECTOR_INDICES]
    return Market(
        days=days,
        symbols=symbols,
        sectors=[s.sector for s in inputs.stocks],
        open=open_,
        high=high,
        low=low,
        close=close,
        factor=factor,
        volume=volume,
        avg_volume20=avg_vol,
        median_turnover=med_turn,
        band_pct=band,
        dividend=dividend,
        universe=eligible,
        score=score,
        atr14=atr,
        ema20=ema20,
        ema50=ema50,
        ema200=ema200,
        rsi14=rsi14,
        adx14=adx14,
        plus_di=plus_di,
        minus_di=minus_di,
        volume_ratio=vol_ratio,
        prior_high_52w=prior_high,
        last_swing_low=swing_low,
        last_day=last_day,
        nifty500=nifty500,
        regime=_regimes(nifty500),
        risk_off=_risk_off(_index_series(days, inputs.nifty50), _index_series(days, inputs.vix)),
        quality_fail=np.array([d in inputs.quality_fail_days for d in days]),
        security_list_known=security_list_known,
        exclusions=exclusions,
        rs6_rank=rs6_rank,
        results_blackout=results_blackout(days, symbols, inputs.results),
        results=inputs.results,
        results_updated=inputs.results_updated,
        news_score=news_scores(days, symbols, inputs.news),
        news_labeller=inputs.news_labeller,
        prior_high_50=prior_high_50,
        sector_rank=sector_ranks(close, nifty500, sector_closes),
        results_reaction=None if reactions is None else reactions[0],
        results_volume_ratio=None if reactions is None else reactions[1],
    )


def _returns(closes: Array) -> Array:
    """Daily returns along the last axis; NaN where either close is missing, and on the
    first day."""
    out = np.full(closes.shape, NAN)
    with np.errstate(invalid="ignore", divide="ignore"):
        out[..., 1:] = closes[..., 1:] / closes[..., :-1] - 1
    return out


def sector_ranks(close: Array, nifty500: Array, sectors: Sequence[Array]) -> Array:
    """Strategies v3's sector rotation: for each stock and day, the strength rank
    (1 = strongest) of the sector index the stock follows; NaN where it follows none.

    Every `SECTOR_ASSIGN_EVERY` sessions each stock is assigned to the index whose daily
    returns in excess of Nifty 500's correlate most with the stock's own excess returns
    over the last `SECTOR_LOOKBACK_SESSIONS` (at least `SECTOR_MIN_RETURNS` of them, and
    a correlation of at least `SECTOR_MIN_CORRELATION`). Strength is the index's return
    over `SECTOR_STRENGTH_SESSIONS` minus Nifty 500's. Only data up to each day is used."""
    s_count, d_count = close.shape
    out = np.full((s_count, d_count), NAN)
    if not sectors or d_count == 0:
        return out
    index = np.vstack(sectors)  # (sectors, days)
    market = _returns(nifty500)
    stock_excess = _returns(close) - market
    index_excess = _returns(index) - market

    n = SECTOR_STRENGTH_SESSIONS
    strength = np.full(index.shape, NAN)
    with np.errstate(invalid="ignore", divide="ignore"):
        strength[:, n:] = index[:, n:] / index[:, :-n] - (nifty500[n:] / nifty500[:-n])
    # Rank 1 = strongest; NaN strength gets no rank.
    order = np.argsort(np.argsort(-np.nan_to_num(strength, nan=-np.inf), axis=0), axis=0)
    ranks = np.where(np.isnan(strength), NAN, order + 1.0)

    assigned = np.full(s_count, -1)
    for t in range(d_count):
        if (
            t >= SECTOR_LOOKBACK_SESSIONS
            and (t - SECTOR_LOOKBACK_SESSIONS) % SECTOR_ASSIGN_EVERY == 0
        ):
            window = slice(t - SECTOR_LOOKBACK_SESSIONS + 1, t + 1)
            assigned = _assign_sectors(stock_excess[:, window], index_excess[:, window])
        has = assigned >= 0
        out[has, t] = ranks[assigned[has], t]
    return out


def _assign_sectors(stocks: Array, sectors: Array) -> Array:
    """Index of the best-correlated sector per stock (rows of `stocks` against rows of
    `sectors`, over the days both have), or -1."""
    ok = ~np.isnan(stocks)
    x = np.where(ok, stocks, 0.0)
    w = ok.astype(float)
    y = np.nan_to_num(sectors, nan=0.0).T  # (days, sectors)
    n = w.sum(axis=1, keepdims=True)
    sx, sxx = x.sum(axis=1, keepdims=True), (x * x).sum(axis=1, keepdims=True)
    sy, syy, sxy = w @ y, w @ (y * y), x @ y
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = (n * sxy - sx * sy) / np.sqrt((n * sxx - sx * sx) * (n * syy - sy * sy))
    corr = np.where(np.isfinite(corr), corr, -np.inf)
    best = np.argmax(corr, axis=1)
    keep = (n[:, 0] >= SECTOR_MIN_RETURNS) & (
        corr[np.arange(len(best)), best] >= SECTOR_MIN_CORRELATION
    )
    return np.where(keep, best, -1)


def results_reactions(
    days: Sequence[date],
    symbols: Sequence[str],
    results: Mapping[str, Sequence[ResultsDate]] | None,
    close: Array,
    volume_ratio: Array,
    nifty500: Array,
) -> tuple[Array, Array] | None:
    """Strategies v3's post-results drift. For each results meeting, with `m` the first
    session on or after the meeting date and `r = m + 1`: on day `r`, the stock's return
    from the close of `m - 1` to the close of `r` minus Nifty 500's, and the higher of
    the volume ratios on `m` and `r`. NaN elsewhere."""
    if results is None:
        return None
    reaction = np.full(close.shape, NAN)
    volume = np.full(close.shape, NAN)
    ordinals = np.array([d.toordinal() for d in days])
    for k, symbol in enumerate(symbols):
        for meeting in results.get(symbol, ()):
            m = int(np.searchsorted(ordinals, meeting.meeting_date.toordinal()))
            r = m + 1
            if m < 1 or r >= len(days):
                continue
            before, after = close[k, m - 1], close[k, r]
            if np.isnan(before) or np.isnan(after):
                continue
            reaction[k, r] = after / before - nifty500[r] / nifty500[m - 1]
            ratios = volume_ratio[k, m : r + 1]
            if not np.all(np.isnan(ratios)):
                volume[k, r] = np.nanmax(ratios)
    return reaction, volume


def news_scores(
    days: Sequence[date],
    symbols: Sequence[str],
    news: Mapping[str, Sequence[DatedLabel]] | None,
) -> Array | None:
    """`app.news.labels.news_score` for every stock and day, at once."""
    if news is None:
        return None
    ordinals = np.array([d.toordinal() for d in days])
    total = np.zeros((len(symbols), len(days)))
    for k, symbol in enumerate(symbols):
        for label in news.get(symbol, ()):
            if label.sentiment == 0:
                continue
            weight, half_life = SCORE_WEIGHTS[label.event_type]
            day = label.day.toordinal()
            first = int(np.searchsorted(ordinals, day))
            last = int(
                np.searchsorted(ordinals, day + half_life * SCORE_HORIZON_HALF_LIVES, "right")
            )
            ages = ordinals[first:last] - day
            total[k, first:last] += label.sentiment * weight * np.power(0.5, ages / half_life)
    return np.clip(50.0 + SCORE_SCALE * total, 0.0, 100.0)


def results_blackout(
    days: Sequence[date],
    symbols: Sequence[str],
    results: Mapping[str, Sequence[ResultsDate]] | None,
) -> Array | None:
    if results is None:
        return None
    blocked = np.zeros((len(symbols), len(days)), dtype=bool)
    for k, symbol in enumerate(symbols):
        for t in blackout_signal_days(days, results.get(symbol, ())):
            blocked[k, t] = True
    return blocked


@dataclass(frozen=True)
class MarketState:
    """The market regime on a day, as the backtests and paper trading see it."""

    day: date
    regime: Regime
    # Spec section 3's regime filter is on: risk per trade is halved.
    risk_off: bool


def market_state(
    days: Sequence[date],
    nifty500: Mapping[date, float],
    nifty50: Mapping[date, float],
    vix: Mapping[date, float],
) -> MarketState | None:
    """The regime on the last of `days` (oldest first), from index closes."""
    if not days:
        return None
    regime = _regimes(_index_series(days, nifty500))[-1]
    risk_off = _risk_off(_index_series(days, nifty50), _index_series(days, vix))[-1]
    return MarketState(days[-1], regime, bool(risk_off))
