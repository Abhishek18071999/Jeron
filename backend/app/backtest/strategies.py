"""The strategies M3 evaluates. Each has few parameters and a small grid; the
walk-forward picks a grid point on training data only.

Every strategy trades the scan's universe (`app.backtest.market`), long only, and
uses the same entry, exit and sizing rules (`app.backtest.engine`). What differs is
the entry condition, the stop distance and the tier (holding period).
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from itertools import product
from typing import Any, TypeVar

import numpy as np

from app.backtest.features import Array
from app.backtest.market import Market, Regime

Params = dict[str, float]


class Tier(StrEnum):
    SWING = "swing"
    POSITIONAL = "positional"
    INVEST = "invest"


_Rules = TypeVar("_Rules")


@dataclass(frozen=True)
class TierRules:
    max_positions: int
    max_stop_pct: float  # spec section 4: entry-to-stop at most 12% swing / 20% positional
    time_stop_sessions: int  # exit if +1R not reached within this many sessions
    time_stop_label: str
    # The tier's targets and trail; None keeps `PortfolioRules`' (spec section 5: book
    # half at +2R, T2 +3R, trail 2 x ATR).
    t1_r: float | None = None
    t2_r: float | None = None
    trail_atr: float | None = None

    def apply(self, rules: _Rules) -> _Rules:
        """`rules` (a `PortfolioRules`) with this tier's targets and trail."""
        overrides = {
            k: v
            for k, v in (("t1_r", self.t1_r), ("t2_r", self.t2_r), ("trail_atr", self.trail_atr))
            if v is not None
        }
        return replace(rules, **overrides) if overrides else rules  # type: ignore[type-var]


TIERS = {
    Tier.SWING: TierRules(5, 12.0, 15, "Swing: exit if not +1R within 15 sessions"),
    Tier.POSITIONAL: TierRules(8, 20.0, 60, "Positional: exit at the 60-session review if not +1R"),
    # docs/plans/sections-v1.md: investing holds for months, so the target and the
    # trail are wider and the time stop is a year.
    Tier.INVEST: TierRules(
        15,
        20.0,
        250,
        "Invest: exit if not +1R within 250 sessions",
        t1_r=3.0,
        t2_r=5.0,
        trail_atr=4.0,
    ),
}


@dataclass(frozen=True)
class ExitSignal:
    """bool (stocks, days): sell a held position at the next open."""

    when: Array
    reason: str


# Score needed on risk-off days (spec section 3: require >= 85 when the regime filter
# is on).
RISK_OFF_MIN_SCORE = 85.0


def _shift(a: Array) -> Array:
    """Each stock's previous-session value (NaN on the first day)."""
    out = np.full_like(a, np.nan)
    out[:, 1:] = a[:, :-1]
    return out


@dataclass(frozen=True)
class Strategy:
    key: str
    version: str
    name: str
    tier: Tier
    summary: str
    grid_axes: dict[str, tuple[float, ...]]
    default: Params
    describe: Callable[[Params], list[str]]
    condition: Callable[[Market, Params], Array]
    # M6: no entry fills around results (spec section 2), and none while the stock's
    # news score is below this (recent bad news). Off in the M3 versions.
    results_blackout: bool = False
    min_news_score: float | None = None
    # A rule that sells at the next open (sections-v1: results weakened), with the
    # reason the trade records and the sentence `rules` adds.
    exit_condition: Callable[[Market, Params], Array] | None = None
    exit_reason: str = ""
    exit_rule: str = ""

    @property
    def grid(self) -> list[Params]:
        names = list(self.grid_axes)
        return [
            dict(zip(names, values, strict=True)) for values in product(*self.grid_axes.values())
        ]

    def entries(self, market: Market, params: Params) -> Array:
        """Bool (stocks, days): an entry signal at that day's close."""
        with np.errstate(invalid="ignore"):
            entries = market.universe & self.condition(market, params)
            if self.min_news_score is not None and market.news_score is not None:
                entries &= market.news_score >= self.min_news_score
            return np.asarray(entries, dtype=bool)

    def exits(self, market: Market, params: Params) -> ExitSignal | None:
        if self.exit_condition is None:
            return None
        with np.errstate(invalid="ignore"):
            when = np.asarray(self.exit_condition(market, params), dtype=bool)
        return ExitSignal(when, self.exit_reason)

    def rules(self, params: Params) -> list[str]:
        tier = TIERS[self.tier]
        return [
            *self.describe(params),
            f"Stop {params['stop_atr']:g} x ATR(14) below the signal close; skip if that is "
            f"more than {tier.max_stop_pct:g}% away.",
            *common_rules(self.tier),
            *self.event_rules(),
            *([self.exit_rule] if self.exit_rule else []),
            tier.time_stop_label + ".",
        ]

    def event_rules(self) -> list[str]:
        rules = []
        if self.results_blackout:
            rules.append(
                "No entry from 3 sessions before a results board meeting through the "
                "meeting day (where the results calendar has the date)."
            )
        if self.min_news_score is not None:
            rules.append(
                f"No entry while the stock's news score is below {self.min_news_score:g} "
                "(recent bad news); no filter where news isn't labelled."
            )
        return rules


COMMON_RULES = [
    "Universe: the daily scan's (EQ series, close >= ₹20, 20-day median turnover >= ₹5 "
    "crore, not on GSM/ASM, 200 sessions of history).",
    "Buy at the next open if it is at or below the signal close + 0.5 x ATR. Skip if it "
    "opens above that, opens below the stop, or is locked at the upper circuit.",
    "No entry in a stock in a 2% or 5% price band that day (it can lock at the lower "
    "circuit for days).",
    "Book half at +{t1:g}R, stop to breakeven at +1R (closing basis), trail the rest by "
    "{trail:g} x ATR(14) on closing basis, exiting at the next open.",
    "Size: 1% of equity at risk (halved when Nifty 50 is below its 200-day EMA or VIX is "
    "in its top decile, halved again in a 10% drawdown), at most 20% of equity and 1% of "
    "20-day average volume; no new entries above 6% total open risk or for 20 sessions "
    "after a 15% drawdown.",
    "Most candidates on a day go to the highest tech-v1 score first.",
]


def common_rules(tier: Tier) -> list[str]:
    """`COMMON_RULES` with the tier's target and trail."""
    rules = TIERS[tier]
    t1 = 2.0 if rules.t1_r is None else rules.t1_r
    trail = 2.0 if rules.trail_atr is None else rules.trail_atr
    return [r.format(t1=t1, trail=trail) if "{t1" in r else r for r in COMMON_RULES]


def _score_condition(m: Market, p: Params) -> Array:
    threshold = np.where(m.risk_off, max(p["min_score"], RISK_OFF_MIN_SCORE), p["min_score"])
    prev = np.nan_to_num(_shift(m.score), nan=-1.0)
    today = np.nan_to_num(m.score, nan=-1.0)
    return np.asarray((today >= threshold) & (prev < threshold), dtype=bool)


def _breakout_condition(m: Market, p: Params) -> Array:
    return (m.close > m.prior_high_52w) & (m.volume_ratio >= p["volume_x"]) & (m.close > m.ema200)


def _pullback_condition(m: Market, p: Params) -> Array:
    rsi_prev = _shift(m.rsi14)
    return (
        (m.close > m.ema200)
        & (m.ema20 > m.ema50)
        & (m.adx14 > 20)
        & (rsi_prev < p["rsi_level"])
        & (m.rsi14 >= p["rsi_level"])
    )


def _rs6_rank(m: Market) -> Array:
    if m.rs6_rank is None:
        raise ValueError("this strategy needs the market's rs6_rank")
    return np.asarray(np.nan_to_num(m.rs6_rank, nan=-1.0), dtype=float)


def _uptrend(m: Market) -> Array:
    return np.asarray((m.close > m.ema50) & (m.ema50 > m.ema200), dtype=bool)


# v2 research (docs/plans/strategies-v2.md): a 6-month RS leader is in the top fifth of
# the universe.
TREND_BREAKOUT_MIN_RS = 0.8


def _trend_breakout_condition(m: Market, p: Params) -> Array:
    return np.asarray(
        (m.close > m.prior_high_52w)
        & (m.volume_ratio >= p["volume_x"])
        & _uptrend(m)
        & (_rs6_rank(m) >= TREND_BREAKOUT_MIN_RS)
        & m.regime_is(Regime.BULL),
        dtype=bool,
    )


def _rs_pullback_condition(m: Market, p: Params) -> Array:
    return np.asarray(
        (_rs6_rank(m) >= p["min_rs"])
        & _uptrend(m)
        & (m.low <= m.ema20)
        & (m.close > m.ema20)
        & m.regime_is(Regime.BULL, Regime.SIDEWAYS),
        dtype=bool,
    )


SCORE_SWING = Strategy(
    key="score-swing",
    version="score-swing-v1",
    name="Technical score crossing (swing)",
    tier=Tier.SWING,
    summary="Buy when a stock's tech-v1 score rises to the threshold.",
    grid_axes={"min_score": (70.0, 75.0, 80.0, 85.0), "stop_atr": (1.5, 2.0, 2.5)},
    default={"min_score": 80.0, "stop_atr": 2.0},
    describe=lambda p: [
        f"Enter when the tech-v1 score closes at or above {p['min_score']:g} after being "
        f"below it the day before ({RISK_OFF_MIN_SCORE:g} when the regime filter is on)."
    ],
    condition=_score_condition,
)

BREAKOUT_52W = Strategy(
    key="breakout-52w",
    version="breakout-52w-v1",
    name="52-week-high breakout with volume (positional)",
    tier=Tier.POSITIONAL,
    summary="Buy a close above the prior 52-week high on heavy volume, in an uptrend.",
    grid_axes={"volume_x": (1.5, 2.0), "stop_atr": (2.0, 3.0)},
    default={"volume_x": 1.5, "stop_atr": 2.0},
    describe=lambda p: [
        "Enter when the close is above the highest high of the previous 252 sessions, "
        f"on volume at least {p['volume_x']:g}x the 20-day average, with the close above "
        "the 200-day EMA."
    ],
    condition=_breakout_condition,
)

PULLBACK_TREND = Strategy(
    key="pullback-trend",
    version="pullback-trend-v1",
    name="Pullback in an uptrend (swing)",
    tier=Tier.SWING,
    summary="Buy when RSI turns back up after a dip, in an established uptrend.",
    grid_axes={"rsi_level": (35.0, 40.0, 45.0), "stop_atr": (1.5, 2.0)},
    default={"rsi_level": 40.0, "stop_atr": 1.5},
    describe=lambda p: [
        "Enter in an uptrend (close above the 200-day EMA, 20-day EMA above the 50-day, "
        f"ADX(14) above 20) when RSI(14) closes back above {p['rsi_level']:g} after being "
        "below it."
    ],
    condition=_pullback_condition,
)

TREND_BREAKOUT = Strategy(
    key="trend-breakout",
    version="trend-breakout-v1",
    name="52-week breakout by a relative-strength leader (positional)",
    tier=Tier.POSITIONAL,
    summary="Buy a 52-week-high breakout on volume by a top-fifth RS stock, in a bull market.",
    grid_axes={"volume_x": (1.5, 2.0), "stop_atr": (2.5, 3.0)},
    default={"volume_x": 1.5, "stop_atr": 3.0},
    describe=lambda p: [
        "Enter when the close is above the highest high of the previous 252 sessions, on "
        f"volume at least {p['volume_x']:g}x the 20-day average, with the close above the "
        "50-day EMA and the 50-day above the 200-day, the stock's 6-month relative "
        f"strength in the top {100 - 100 * TREND_BREAKOUT_MIN_RS:g}% of the universe, and "
        "the market regime bull (Nifty 500 above its rising 200-day EMA)."
    ],
    condition=_trend_breakout_condition,
)

RS_PULLBACK = Strategy(
    key="rs-pullback",
    version="rs-pullback-v1",
    name="Pullback to the 20-day EMA by a relative-strength leader (positional)",
    tier=Tier.POSITIONAL,
    summary="Buy a dip to the 20-day EMA that holds, in a top RS stock, unless the market is bear.",
    grid_axes={"min_rs": (0.8, 0.9), "stop_atr": (2.0, 3.0)},
    default={"min_rs": 0.9, "stop_atr": 2.0},
    describe=lambda p: [
        "Enter when the stock's 6-month relative strength is in the top "
        f"{100 - 100 * p['min_rs']:g}% of the universe, the close is above the 50-day EMA "
        "and the 50-day above the 200-day, the day's low touched the 20-day EMA and the "
        "close held above it, and the market regime is not bear."
    ],
    condition=_rs_pullback_condition,
)

# v3 research (docs/plans/strategies-v3.md).
RESULTS_MIN_VOLUME_X = 2.0


def _results_drift_condition(m: Market, p: Params) -> Array:
    if m.results_reaction is None or m.results_volume_ratio is None:
        raise ValueError("this strategy needs the results calendar (run the events job)")
    reaction = np.nan_to_num(m.results_reaction, nan=-np.inf)
    volume = np.nan_to_num(m.results_volume_ratio, nan=0.0)
    return np.asarray((reaction >= p["min_jump"]) & (volume >= RESULTS_MIN_VOLUME_X), dtype=bool)


def _sector_rotation_condition(m: Market, p: Params) -> Array:
    if m.sector_rank is None or m.prior_high_50 is None:
        raise ValueError("this strategy needs the sector ranks and 50-session highs")
    rank = np.nan_to_num(m.sector_rank, nan=np.inf)
    return np.asarray(
        (rank <= p["top_n"])
        & (m.close > m.prior_high_50)
        & _uptrend(m)
        & m.regime_is(Regime.BULL, Regime.SIDEWAYS),
        dtype=bool,
    )


RESULTS_DRIFT = Strategy(
    key="results-drift",
    version="results-drift-v1",
    name="Drift after a strong results reaction (positional)",
    tier=Tier.POSITIONAL,
    summary="Buy the day after results when the stock beat Nifty 500 by a wide margin on volume.",
    grid_axes={"min_jump": (0.05, 0.08), "stop_atr": (2.5, 3.0)},
    default={"min_jump": 0.05, "stop_atr": 3.0},
    describe=lambda p: [
        "Enter at the close of the session after a results board meeting when the stock's "
        "return from the close before the meeting session beats Nifty 500's by at least "
        f"{100 * p['min_jump']:g}%, and volume on the meeting session or the one after is "
        f"at least {RESULTS_MIN_VOLUME_X:g}x the 20-day average. No trend or regime filter."
    ],
    condition=_results_drift_condition,
)

SECTOR_ROTATION = Strategy(
    key="sector-rotation",
    version="sector-rotation-v1",
    name="10-week high in a leading sector (positional)",
    tier=Tier.POSITIONAL,
    summary="Buy a fresh 10-week high in an uptrend when the stock's sector leads the market.",
    grid_axes={"top_n": (2.0, 3.0), "stop_atr": (2.5, 3.0)},
    default={"top_n": 3.0, "stop_atr": 3.0},
    describe=lambda p: [
        "Enter when the stock's sector is among the strongest "
        f"{p['top_n']:g} of ten NSE sectoral indices (3-month return against Nifty 500), "
        "the close is above the highest high of the previous 50 sessions, the close is "
        "above the 50-day EMA and the 50-day above the 200-day, and the market regime is "
        "not bear. A stock's sector is the index its excess returns followed most closely "
        "over the last year, re-measured every 21 sessions."
    ],
    condition=_sector_rotation_condition,
)

# sections-v1 (docs/plans/sections-v1.md): the investing tier's first strategy.
FUND_EXIT_BELOW = 50.0


def _fund_score(m: Market) -> Array:
    if m.fund_score is None:
        raise ValueError("this strategy needs the fundamental scores (run fundamentals-import)")
    return m.fund_score


def _quality_trend_condition(m: Market, p: Params) -> Array:
    fund = np.nan_to_num(_fund_score(m), nan=-1.0)
    ok = ((fund >= p["min_fund"]) & (m.close > m.ema50) & (m.ema50 > m.ema200)).astype(float)
    before = np.nan_to_num(_shift(ok), nan=0.0)
    return np.asarray((ok == 1.0) & (before == 0.0), dtype=bool)


def _quality_trend_exit(m: Market, p: Params) -> Array:
    # An unknown score (no filing yet, or stale) is not an exit.
    return np.asarray(np.nan_to_num(_fund_score(m), nan=100.0) < FUND_EXIT_BELOW, dtype=bool)


QUALITY_TREND = Strategy(
    key="quality-trend",
    version="quality-trend-v1",
    name="Strong results in a long-term uptrend (invest)",
    tier=Tier.INVEST,
    summary="Own companies with a high fund-v1 score while the 50-day EMA is above the 200-day.",
    grid_axes={"min_fund": (60.0, 70.0), "stop_atr": (3.0, 4.0)},
    default={"min_fund": 70.0, "stop_atr": 4.0},
    describe=lambda p: [
        f"Enter on the first day the stock's fundamental score (fund-v1, from the results "
        f"filings published before that day) is at least {p['min_fund']:g}, the close is "
        "above the 50-day EMA and the 50-day EMA is above the 200-day EMA. No market-regime "
        "filter."
    ],
    condition=_quality_trend_condition,
    exit_condition=_quality_trend_exit,
    exit_reason=f"results weakened (fund-v1 below {FUND_EXIT_BELOW:g})",
    exit_rule=(
        f"Sell at the next open after a new results filing takes fund-v1 below "
        f"{FUND_EXIT_BELOW:g} (a qualified audit opinion scores 0)."
    ),
)

# Bad news keeps a stock out until its score recovers: one -2 results label scores 25,
# back above 40 after about 26 days.
MIN_NEWS_SCORE = 40.0


def with_events(base: Strategy) -> Strategy:
    """The M3 strategy with M6's results blackout and news filter."""
    return replace(
        base,
        key=f"{base.key}-events",
        version=f"{base.key}-events-v1",
        name=f"{base.name} + results blackout and news filter",
        summary=f"{base.summary} Not around results or after bad news.",
        results_blackout=True,
        min_news_score=MIN_NEWS_SCORE,
    )


STRATEGIES = {
    s.key: s
    for s in (
        SCORE_SWING,
        BREAKOUT_52W,
        PULLBACK_TREND,
        with_events(SCORE_SWING),
        with_events(BREAKOUT_52W),
        with_events(PULLBACK_TREND),
        TREND_BREAKOUT,
        RS_PULLBACK,
        RESULTS_DRIFT,
        SECTOR_ROTATION,
        QUALITY_TREND,
    )
}


@dataclass(frozen=True)
class Combined:
    """Several strategies trading one account (a combined book), each with its own
    entry, stop and exit rules and the grid points its own walk-forward picks. On a
    busy day the strategy with fewer open positions orders first; a tie goes to the one
    listed first. Not in `STRATEGIES`: paper trading opens no account for it."""

    key: str
    version: str
    name: str
    summary: str
    members: tuple[Strategy, ...]
    # The strategies whose variants its plan counted as trials for the deflated Sharpe.
    trial_keys: tuple[str, ...] = ()

    @property
    def tier(self) -> Tier:
        tiers = {s.tier for s in self.members}
        if len(tiers) != 1:
            raise ValueError(f"{self.key}: members trade different tiers")
        return self.members[0].tier

    def rules(self, params: dict[str, Params]) -> list[str]:
        out = [
            f"One account trades {', '.join(s.version for s in self.members)}, each by its "
            "own rules below. A stock held or ordered by one is skipped by the others.",
            "When there are more signals than free slots (or open-risk room), the strategy "
            "with fewer open positions orders first; on a tie "
            f"{self.members[0].version} goes first. Within a strategy, the highest "
            "tech-v1 score first.",
        ]
        for s in self.members:
            out += [f"{s.version}: {r}" for r in s.describe(params[s.key])]
            out.append(
                f"{s.version}: stop {params[s.key]['stop_atr']:g} x ATR(14) below the signal close."
            )
        tier = TIERS[self.tier]
        return [
            *out,
            f"Skip a stop more than {tier.max_stop_pct:g}% away.",
            *common_rules(self.tier),
            tier.time_stop_label + ".",
        ]


# Pre-registered in docs/plans/combined-book-v1.md.
COMBINED_BOOK = Combined(
    key="combined-book",
    version="combined-book-v1",
    name="Combined book: RS pullback and results drift in one account (positional)",
    summary="rs-pullback-v1 and results-drift-v1 sharing one account, 8 positions, 6% heat.",
    members=(RS_PULLBACK, RESULTS_DRIFT),
    # The 60 variants registered before it (docs/plans/combined-book-v1.md).
    trial_keys=(
        "score-swing",
        "breakout-52w",
        "pullback-trend",
        "score-swing-events",
        "breakout-52w-events",
        "pullback-trend-events",
        "trend-breakout",
        "rs-pullback",
        "results-drift",
        "sector-rotation",
    ),
)

COMBINED = {COMBINED_BOOK.key: COMBINED_BOOK}


def params_label(params: Params) -> str:
    return ", ".join(f"{k}={v:g}" for k, v in params.items())


def params_json(params: Params) -> dict[str, Any]:
    return dict(params)
