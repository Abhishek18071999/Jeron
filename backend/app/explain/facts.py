"""Explain a stock from Jeron's own numbers (docs/plans/explain-v1.md). Pure: the
service loads the inputs.

Every statement is a `Fact` with where it came from and the date it is true for, marked
by what kind of thing it is:

- `data`: published by the exchange (NSE's daily prices, filings, announcements);
- `calculated`: worked out by Jeron's tested code from that data (indicators, scores,
  the plan's arithmetic, a strategy's out-of-sample record);
- `model`: an estimate from a model (the LLM's label of an announcement);
- `rule`: what a strategy's rules say (a signal's entry zone, stop, what cancels it).

The brief built from the facts (why it is in the scan, what supports it, what argues
against it, what would cancel it, three plain scenarios, a pre-trade checklist and what
Jeron doesn't know) is deterministic: no LLM, no new numbers. A score is a score, not a
probability, and nothing here is advice to buy or sell.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any


class Kind(StrEnum):
    DATA = "data"
    CALCULATED = "calculated"
    MODEL = "model"
    RULE = "rule"


class Stance(StrEnum):
    FOR = "for"  # supports a long trade
    AGAINST = "against"
    NEUTRAL = "neutral"


NSE_PRICES = "NSE bhavcopy (end of day)"
SCAN = "Jeron scan"
FILINGS = "NSE Financial Results filings"
ANNOUNCEMENTS = "NSE corporate announcements"
BOARD_MEETINGS = "NSE board meetings"
CORPORATE_ACTIONS = "NSE corporate actions"


@dataclass(frozen=True)
class Fact:
    id: str
    topic: str
    label: str
    value: str  # as shown
    kind: Kind
    source: str
    as_of: date | None
    stance: Stance = Stance.NEUTRAL
    number: float | None = None  # the value as a number, when it is one


@dataclass(frozen=True)
class ScanInputs:
    trade_date: date
    score: float
    rank: int
    universe: int | None
    score_version: str
    components: Sequence[dict[str, Any]]  # key, label, value, points, max_points
    indicators: dict[str, Any]


@dataclass(frozen=True)
class SignalInputs:
    """The newest signal for the stock, its levels on today's (adjusted) price basis."""

    signal_date: date
    strategy: str
    research_only: bool
    setup_name: str
    tier: str
    entry_low: float
    entry_high: float
    valid_until: date
    stop: float
    stop_reason: str
    t1: float
    t2: float
    invalidation: str
    why: Sequence[str]
    backtest: dict[str, Any]
    # Adjusted (date, open, low, close) for each session after the signal day.
    since: Sequence[tuple[date, float, float, float]] = ()


@dataclass(frozen=True)
class NewsInputs:
    day: date
    subject: str
    event_type: str
    sentiment: int | None  # None: only the subject rule read it
    reason: str
    labeller: str | None


@dataclass(frozen=True)
class FundInputs:
    score: float | None
    quality: float
    valuation: float
    rejected: str | None
    version: str
    newest_quarter: date | None
    filed: date | None
    facts: dict[str, float | None]
    notes: Sequence[str] = ()


@dataclass(frozen=True)
class StockInputs:
    symbol: str
    name: str | None
    sector: str | None
    today: date
    last_date: date | None  # the newest stored session
    last_close: float | None  # raw, that session
    due: date | None  # the newest session whose data should be in by now
    scan: ScanInputs | None
    mood: tuple[date, str, str] | None  # (scan day, attack/normal/defend, why)
    results_date: date | None
    results_line: str
    blackout: bool | None  # None: the board-meeting calendar is not loaded
    ex_dates: Sequence[str] = ()
    signal: SignalInputs | None = None
    fundamentals: FundInputs | None = None
    news: Sequence[NewsInputs] = ()
    news_ready: bool = False
    holding: tuple[int, float, float | None] | None = None  # shares, avg entry, stop


@dataclass
class Check:
    label: str
    status: str  # "pass" / "fail" / "unknown"
    detail: str
    facts: list[str] = field(default_factory=list)


@dataclass
class SetupStatus:
    state: str  # "waiting" / "in zone" / "above zone" / "invalidated" / "expired"
    still_valid: bool
    reasons: list[str]
    facts: list[str] = field(default_factory=list)


@dataclass
class Brief:
    symbol: str
    name: str | None
    as_of: date | None
    facts: list[Fact]
    why_in_scan: list[str]  # plain sentences
    supporting: list[str]  # fact ids
    against: list[str]
    cancels: list[str]  # plain sentences
    scenarios: dict[str, str]  # bullish / neutral / bearish
    checklist: list[Check]
    unknowns: list[str]
    setup: SetupStatus | None
    stale: bool
    # The newest signal's strategy key ("rs-pullback") and whether it is research only.
    strategy: str | None = None
    research_only: bool | None = None

    def fact(self, fact_id: str) -> Fact:
        return next(f for f in self.facts if f.id == fact_id)


def _rs(value: float) -> str:
    return f"₹{value:,.2f}"


def _pct(value: float, places: int = 1) -> str:
    return f"{value:.{places}f}%"


class _Facts:
    def __init__(self) -> None:
        self.items: list[Fact] = []

    def add(
        self,
        topic: str,
        label: str,
        value: str,
        kind: Kind,
        source: str,
        as_of: date | None,
        stance: Stance = Stance.NEUTRAL,
        number: float | None = None,
    ) -> str:
        fact_id = f"F{len(self.items) + 1}"
        self.items.append(Fact(fact_id, topic, label, value, kind, source, as_of, stance, number))
        return fact_id


def _num(d: dict[str, Any], key: str) -> float | None:
    v = d.get(key)
    return None if v is None else float(v)


def setup_status(s: SignalInputs, today: date, last_close: float | None) -> SetupStatus:
    """Does the newest signal still meet its own conditions? Prices are adjusted."""
    reasons: list[str] = []
    broke = next(((d, low) for d, _, low, _ in s.since if low <= s.stop), None)
    if broke is not None:
        reasons.append(
            f"traded at or below the stop {_rs(s.stop)} on {broke[0]:%-d %b %Y} "
            f"(low {_rs(broke[1])}): the setup is invalidated"
        )
        return SetupStatus("invalidated", False, reasons)
    filled = next((d for d, open_, low, _ in s.since if low <= s.entry_high), None)
    if today > s.valid_until and filled is None:
        reasons.append(
            f"the entry zone was valid until {s.valid_until:%-d %b %Y} and never traded: "
            "the signal expired"
        )
        return SetupStatus("expired", False, reasons)
    close = s.since[-1][3] if s.since else last_close
    if close is not None and close > s.entry_high:
        reasons.append(
            f"the last close {_rs(close)} is above the entry zone (top {_rs(s.entry_high)}); "
            "the engine skips a buy that opens above the zone"
        )
        return SetupStatus("above zone", filled is None, reasons)
    if close is not None and s.entry_low <= close <= s.entry_high:
        reasons.append(f"the last close {_rs(close)} is inside the entry zone")
        return SetupStatus("in zone", True, reasons)
    reasons.append("the stop has not been touched and the zone is still valid")
    return SetupStatus("waiting", True, reasons)


def build_brief(i: StockInputs) -> Brief:
    f = _Facts()
    supporting: list[str] = []
    against: list[str] = []
    why: list[str] = []
    cancels: list[str] = []
    unknowns: list[str] = []
    checklist: list[Check] = []

    def note(fid: str) -> str:
        stance = f.items[int(fid[1:]) - 1].stance
        if stance == Stance.FOR:
            supporting.append(fid)
        elif stance == Stance.AGAINST:
            against.append(fid)
        return fid

    stale = i.last_date is None or (i.due is not None and i.last_date < i.due)
    if i.last_close is not None and i.last_date is not None:
        f.add(
            "price",
            "Last close",
            _rs(i.last_close),
            Kind.DATA,
            NSE_PRICES,
            i.last_date,
            number=i.last_close,
        )
    else:
        unknowns.append("No prices are stored for this stock.")
    if stale and i.last_date is not None:
        unknowns.append(
            f"The newest prices are for {i.last_date:%-d %b %Y}; everything below is as of then."
        )

    # --- The scan -------------------------------------------------------------------
    s = i.scan
    levels: dict[str, float] = {}
    if s is None:
        unknowns.append(
            "Not in the latest scan: it failed the universe rules (liquidity, price, "
            "surveillance) or the scan has not run, so there is no technical score."
        )
    else:
        ind = s.indicators
        of = f" of {s.universe}" if s.universe else ""
        note(
            f.add(
                "score",
                f"Technical score ({s.score_version})",
                f"{s.score:.1f} / 100",
                Kind.CALCULATED,
                SCAN,
                s.trade_date,
                Stance.FOR if s.score >= 70 else Stance.AGAINST if s.score < 40 else Stance.NEUTRAL,
                s.score,
            )
        )
        f.add(
            "score",
            "Rank in the scan",
            f"{s.rank}{of}",
            Kind.CALCULATED,
            SCAN,
            s.trade_date,
            number=float(s.rank),
        )
        full = [c for c in s.components if c.get("points", 0) >= c.get("max_points", 1) > 0]
        none = [c for c in s.components if c.get("points", 0) <= 0]
        if full:
            why.append("Full points for: " + "; ".join(str(c["label"]).lower() for c in full) + ".")
        if none:
            why.append("No points for: " + "; ".join(str(c["label"]).lower() for c in none) + ".")
        why.append(
            f"The score adds these up to {s.score:.1f} of 100. It ranks stocks by how many "
            "technical conditions hold; it is not a probability of profit."
        )
        close = _num(ind, "close")
        for key, label in (
            ("ema20", "20-day EMA"),
            ("ema50", "50-day EMA"),
            ("ema200", "200-day EMA"),
        ):
            v = _num(ind, key)
            if v is None:
                continue
            levels[key] = v
            stance = Stance.NEUTRAL
            if close is not None:
                stance = Stance.FOR if close > v else Stance.AGAINST
            above = "" if close is None else (" (close above)" if close > v else " (close below)")
            note(
                f.add(
                    "trend", label, _rs(v) + above, Kind.CALCULATED, SCAN, s.trade_date, stance, v
                )
            )
        rsi = _num(ind, "rsi14")
        if rsi is not None:
            stance = (
                Stance.FOR
                if 50 <= rsi <= 70
                else Stance.AGAINST
                if rsi > 80 or rsi < 40
                else Stance.NEUTRAL
            )
            note(
                f.add(
                    "momentum",
                    "RSI(14)",
                    f"{rsi:.1f}",
                    Kind.CALCULATED,
                    SCAN,
                    s.trade_date,
                    stance,
                    rsi,
                )
            )
        adx = _num(ind, "adx14")
        if adx is not None:
            note(
                f.add(
                    "trend",
                    "ADX(14), trend strength",
                    f"{adx:.1f}",
                    Kind.CALCULATED,
                    SCAN,
                    s.trade_date,
                    Stance.FOR if adx > 20 else Stance.NEUTRAL,
                    adx,
                )
            )
        vr = _num(ind, "volume_ratio")
        if vr is not None:
            note(
                f.add(
                    "volume",
                    "Volume vs 20-day average",
                    f"{vr:.2f}x",
                    Kind.CALCULATED,
                    SCAN,
                    s.trade_date,
                    Stance.FOR if vr >= 1.5 else Stance.NEUTRAL,
                    vr,
                )
            )
        below = _num(ind, "below_52w_high_pct")
        high = _num(ind, "high_52w")
        if below is not None and high is not None:
            levels["high_52w"] = high
            note(
                f.add(
                    "levels",
                    "Below the 52-week high",
                    f"{_pct(below)} (high {_rs(high)})",
                    Kind.CALCULATED,
                    SCAN,
                    s.trade_date,
                    Stance.FOR if below <= 5 else Stance.AGAINST if below >= 25 else Stance.NEUTRAL,
                    below,
                )
            )
        atr_pct = _num(ind, "atr_pct")
        if atr_pct is not None:
            note(
                f.add(
                    "risk",
                    "ATR(14), typical daily range",
                    _pct(atr_pct, 2) + " of price",
                    Kind.CALCULATED,
                    SCAN,
                    s.trade_date,
                    Stance.AGAINST if atr_pct > 6 else Stance.NEUTRAL,
                    atr_pct,
                )
            )
        for key, label in (("rs_3m", "3 months"), ("rs_6m", "6 months")):
            v = _num(ind, key)
            if v is not None:
                note(
                    f.add(
                        "relative",
                        f"Return vs Nifty 500, {label}",
                        _pct(v * 100, 1),
                        Kind.CALCULATED,
                        SCAN,
                        s.trade_date,
                        Stance.FOR if v > 0 else Stance.AGAINST,
                        v * 100,
                    )
                )
        for key, label in (
            ("support", "Support (swing pivots)"),
            ("resistance", "Resistance (swing pivots)"),
        ):
            v = _num(ind, key)
            if v is not None:
                levels[key] = v
                f.add("levels", label, _rs(v), Kind.CALCULATED, SCAN, s.trade_date, number=v)

    # --- The market -----------------------------------------------------------------
    if i.mood is not None:
        day, mode, reason = i.mood
        note(
            f.add(
                "market",
                "Market mood",
                f"{mode}: {reason}",
                Kind.CALCULATED,
                SCAN,
                day,
                Stance.AGAINST if mode == "defend" else Stance.NEUTRAL,
            )
        )
    else:
        unknowns.append("The market mood is unknown: no completed scan.")

    # --- Events ---------------------------------------------------------------------
    if i.blackout is None:
        unknowns.append("The results calendar is not loaded, so results dates are unknown.")
    else:
        when = f.add(
            "events",
            "Results",
            i.results_line,
            Kind.DATA,
            BOARD_MEETINGS,
            i.today,
            Stance.AGAINST if i.blackout else Stance.NEUTRAL,
        )
        note(when)
    for line in i.ex_dates:
        f.add("events", "Corporate action ahead", line, Kind.DATA, CORPORATE_ACTIONS, i.today)

    # --- Fundamentals ---------------------------------------------------------------
    fu = i.fundamentals
    if fu is None:
        unknowns.append("No quarterly results are loaded for this stock: no fundamental score.")
    else:
        if fu.rejected:
            note(
                f.add(
                    "fundamentals",
                    "Fundamental hard reject",
                    fu.rejected,
                    Kind.CALCULATED,
                    FILINGS,
                    fu.filed,
                    Stance.AGAINST,
                )
            )
        if fu.score is not None:
            note(
                f.add(
                    "fundamentals",
                    f"Fundamental score ({fu.version})",
                    f"{fu.score:.0f} / 100",
                    Kind.CALCULATED,
                    FILINGS,
                    fu.filed,
                    Stance.FOR
                    if fu.score >= 60
                    else Stance.AGAINST
                    if fu.score < 40
                    else Stance.NEUTRAL,
                    fu.score,
                )
            )
        if fu.newest_quarter is not None:
            f.add(
                "fundamentals",
                "Newest quarter in the filings",
                f"{fu.newest_quarter:%b %Y}",
                Kind.DATA,
                FILINGS,
                fu.filed,
            )
        for key, label, scale, unit in (
            ("sales_growth", "Sales growth, TTM vs a year before", 100, "%"),
            ("eps_growth", "EPS growth, TTM vs a year before", 100, "%"),
            ("margin", "Net margin, TTM", 100, "%"),
            ("pe", "P/E (TTM)", 1, ""),
            ("pe_percentile", "P/E vs its own history (percentile)", 100, "%"),
        ):
            v = fu.facts.get(key)
            if v is None:
                continue
            shown = v * scale
            stance = Stance.NEUTRAL
            if key.endswith("growth"):
                stance = Stance.FOR if v > 0.1 else Stance.AGAINST if v < 0 else Stance.NEUTRAL
            elif key == "pe_percentile":
                stance = Stance.AGAINST if v > 0.8 else Stance.FOR if v < 0.3 else Stance.NEUTRAL
            note(
                f.add(
                    "fundamentals",
                    label,
                    f"{shown:.1f}{unit}",
                    Kind.CALCULATED,
                    FILINGS,
                    fu.filed,
                    stance,
                    shown,
                )
            )
        unknowns += list(fu.notes)

    # --- News -----------------------------------------------------------------------
    recent = [n for n in i.news if (i.today - n.day).days <= 90]
    if not i.news_ready:
        unknowns.append("The news labeller has no API key: headlines are not read as good or bad.")
    for n in recent[:5]:
        if n.sentiment is None:
            f.add(
                "news",
                n.subject or n.event_type,
                n.reason or "not labelled",
                Kind.DATA,
                ANNOUNCEMENTS,
                n.day,
            )
            continue
        stance = (
            Stance.FOR if n.sentiment > 0 else Stance.AGAINST if n.sentiment < 0 else Stance.NEUTRAL
        )
        note(
            f.add(
                "news",
                n.subject or n.event_type,
                f"{n.event_type}, sentiment {n.sentiment:+d}: {n.reason}",
                Kind.MODEL,
                f"{ANNOUNCEMENTS}, labelled by {n.labeller}",
                n.day,
                stance,
                float(n.sentiment),
            )
        )
    if not recent:
        unknowns.append("No company announcements in the last 90 days.")

    # --- The signal -----------------------------------------------------------------
    setup = None
    sig = i.signal
    if sig is None:
        unknowns.append(
            "No strategy has signalled this stock: Jeron has no backtested reason to buy it now."
        )
    else:
        tag = "research only (failed the backtest gates)" if sig.research_only else "live"
        note(
            f.add(
                "signal",
                "Signal",
                f"{sig.strategy}, {sig.setup_name} ({tag})",
                Kind.RULE,
                f"paper account {sig.strategy}",
                sig.signal_date,
                Stance.NEUTRAL if sig.research_only else Stance.FOR,
            )
        )
        zone = f.add(
            "signal",
            "Entry zone",
            f"{_rs(sig.entry_low)} to {_rs(sig.entry_high)}, "
            f"valid until {sig.valid_until:%-d %b %Y}",
            Kind.RULE,
            f"paper account {sig.strategy}",
            sig.signal_date,
        )
        stop = f.add(
            "signal",
            "Stop",
            f"{_rs(sig.stop)}: {sig.stop_reason}",
            Kind.RULE,
            f"paper account {sig.strategy}",
            sig.signal_date,
            number=sig.stop,
        )
        f.add(
            "signal",
            "Targets",
            f"T1 {_rs(sig.t1)}, T2 {_rs(sig.t2)}",
            Kind.RULE,
            f"paper account {sig.strategy}",
            sig.signal_date,
        )
        bt = sig.backtest
        if bt:
            exp = float(bt.get("expectancy_R") or 0)
            note(
                f.add(
                    "signal",
                    "Strategy's out-of-sample record",
                    f"{bt.get('trades')} trades, expectancy {exp:+.2f}R, win rate "
                    f"{float(bt.get('win_rate') or 0) * 100:.0f}%, max drawdown "
                    f"{float(bt.get('max_drawdown_pct') or 0):.1f}%; {bt.get('period')}",
                    Kind.CALCULATED,
                    "Jeron backtest (walk-forward, after costs)",
                    sig.signal_date,
                    Stance.FOR if exp > 0.15 else Stance.AGAINST,
                    exp,
                )
            )
        setup = setup_status(sig, i.today, i.last_close)
        setup.facts = [zone, stop]
        cancels.append(f"A trade at or below the stop {_rs(sig.stop)} ({sig.stop_reason}).")
        cancels.append(
            f"No fill by {sig.valid_until:%-d %b %Y}, or an open above {_rs(sig.entry_high)}."
        )
        if sig.invalidation:
            cancels.append(sig.invalidation)
    if i.blackout is False and i.results_date is not None:
        cancels.append(
            f"Results on {i.results_date:%-d %b %Y}: no new entries from 3 sessions before."
        )
    if s is not None and "ema200" in levels:
        cancels.append(f"A close below the 200-day EMA ({_rs(levels['ema200'])}) ends the uptrend.")

    # --- Scenarios (levels only, no forecasts) ------------------------------------------
    top = levels.get("resistance") or levels.get("high_52w")
    floor = levels.get("support") or levels.get("ema50") or levels.get("ema200")
    scenarios = {}
    if top is not None:
        scenarios["bullish"] = (
            f"A close above {_rs(top)} (resistance or the 52-week high) on volume above "
            "its 20-day average would extend the trend."
        )
    if top is not None and floor is not None:
        scenarios["neutral"] = f"Between {_rs(floor)} and {_rs(top)}: a range, nothing confirmed."
    if floor is not None:
        bear = f"A close below {_rs(floor)}"
        if "ema200" in levels and floor != levels["ema200"]:
            bear += f", then the 200-day EMA {_rs(levels['ema200'])},"
        scenarios["bearish"] = bear + " would weaken the setup."
    if not scenarios:
        unknowns.append("Too little history for support, resistance or moving averages.")

    # --- Pre-trade checklist ------------------------------------------------------------
    checklist.append(
        Check(
            "A backtested strategy signalled it",
            "pass" if sig is not None and not sig.research_only else "fail",
            "live signal"
            if sig is not None and not sig.research_only
            else ("research-only signal" if sig is not None else "no signal"),
        )
    )
    if setup is not None:
        checklist.append(
            Check(
                "The setup still meets its conditions",
                "pass" if setup.still_valid else "fail",
                "; ".join(setup.reasons),
                setup.facts,
            )
        )
    checklist.append(
        Check(
            "Market mood allows a buy",
            "unknown" if i.mood is None else ("fail" if i.mood[1] == "defend" else "pass"),
            "unknown" if i.mood is None else i.mood[1],
        )
    )
    checklist.append(
        Check(
            "No results within the blackout",
            "unknown" if i.blackout is None else ("fail" if i.blackout else "pass"),
            i.results_line,
        )
    )
    checklist.append(
        Check(
            "Data is current",
            "fail" if stale else "pass",
            "no prices" if i.last_date is None else f"prices to {i.last_date:%-d %b %Y}",
        )
    )
    checklist.append(
        Check(
            "Size and stop come from the trade plan",
            "unknown",
            "open the trade plan: it sizes from your capital and checks heat, sector and limits",
        )
    )

    if i.holding is not None:
        shares, avg, hstop = i.holding
        f.add(
            "holding",
            "You hold",
            f"{shares} shares at {_rs(avg)}" + ("" if hstop is None else f", stop {_rs(hstop)}"),
            Kind.DATA,
            "your journal",
            i.today,
        )
    unknowns.append(
        "Jeron uses end-of-day data only: nothing here reflects today's trading until the "
        "evening run."
    )
    return Brief(
        symbol=i.symbol,
        name=i.name,
        as_of=i.last_date,
        facts=f.items,
        why_in_scan=why,
        supporting=supporting,
        against=against,
        cancels=cancels,
        scenarios=scenarios,
        checklist=checklist,
        unknowns=unknowns,
        setup=setup,
        stale=stale,
        strategy=None if sig is None else sig.strategy,
        research_only=None if sig is None else sig.research_only,
    )
