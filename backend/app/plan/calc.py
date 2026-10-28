"""The trade plan before a buy (decision 0010): targets, the engine's size, the spec
section 4 checks and the portfolio limits after the buy. Pure: `app.plan.service` loads
the inputs from the database.

- Targets are the engine's: T1 = entry + 2R (book half), T2 = entry + 3R, R = entry - stop.
- Shares come from `app.backtest.engine.position_size`, the function the engine (and so
  paper trading and the signals) sizes with: risk % of capital x the mood's multiplier
  (0.5 in defend, the engine's regime filter), over the risk per share, capped at 20% of
  capital and 1% of the 20-day average volume. Capital is JERON_CAPITAL.
- Reward:risk comes from `app.backtest.engine.reward_risk`: estimated charges and
  slippage come off the reward and are added to the risk.
- Hard checks (a plan that fails one can't be saved): stop below entry; stop at least
  1 x ATR(14) and at most 12% (swing) / 20% (positional) below the entry; reward:risk to
  T2 at least 2 after costs; at least one share; portfolio heat after the buy at most
  6%; the sector at most JERON_SECTOR_CAP_PCT of capital after the buy; no results
  board meeting within the blackout (3 sessions before it through the meeting day).
- The real account's guardrails (`app.portfolio.calc.account_state`, docs/plans/
  platform-audit-v1.md slice 3). Spec section 5, always hard: 10% or more below the
  account's peak halves the risk per trade (with the mood's halving, a quarter); 15% or
  more stops new entries; the tier's open positions at most JERON_MAX_POSITIONS_<TIER>.
  Settings, hard unless JERON_RISK_LIMITS_BLOCK is off: today's realised loss below
  JERON_DAILY_LOSS_LIMIT_PCT of capital, this week's below JERON_WEEKLY_LOSS_LIMIT_PCT,
  and fewer than JERON_MAX_ENTRIES_WEEK positions first bought this week.
- The kill switch (`app.halt`, docs/runbook.md): while Jeron is stopped no plan is saved.
- Paper first in a drawdown (docs/plans/post-review-v2.md, item 3): from
  JERON_DRAWDOWN_JOURNAL_PCT below the peak (default 10%) until the 15% pause, signals
  are paper only, and a plan is saved only with a written drawdown note of at least
  `NOTE_MIN_WORDS` words saying why this trade, now. Hard, whatever JERON_RISK_LIMITS_BLOCK.
- Warnings (shown, not blocking): heat at the 5% warning level, defend mode, a results
  calendar that isn't loaded, ex-dates ahead, and a trade so small that fixed charges
  (the DP charge per day with a sale) cost more than 0.1R (`costs.small_trade_warning`).
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal

from app.backtest.costs import CostModel, small_trade_warning
from app.backtest.engine import PortfolioRules, position_size, reward_risk, round_trip_costs
from app.backtest.strategies import TIERS, Tier
from app.portfolio.calc import AccountState

ZERO = Decimal(0)
RULES = PortfolioRules()
COSTS = CostModel()

# The pre-buy checklist (key, what I tick). All five must be ticked to save a plan.
CHECKLIST: tuple[tuple[str, str], ...] = (
    ("mood", "Market mood allows a buy"),
    ("results", "No results within the blackout window"),
    ("stop", "Stop is where the setup fails, not a round number"),
    ("size", "Size is from the plan, not a guess"),
    ("record", "I will record the fill today"),
)
CHECKLIST_KEYS = tuple(k for k, _ in CHECKLIST)

# The drawdown note: long enough to be a reason, not a tick.
NOTE_MIN_WORDS = 20


def _q(value: Decimal | float, places: str = "0.01") -> Decimal:
    return Decimal(str(value)).quantize(Decimal(places))


def _g(value: float | Decimal) -> str:
    return f"{float(value):g}"


@dataclass(frozen=True)
class Limits:
    """The guardrails' settings; a 0 turns that limit off."""

    max_positions: int  # open positions in the plan's tier
    daily_loss_pct: float = 2.0
    weekly_loss_pct: float = 4.0
    max_entries_week: int = 5
    block: bool = True  # False: the loss and entry limits warn instead
    drawdown_journal_pct: float = 10.0  # paper first, with a written note, from here


@dataclass(frozen=True)
class PlanInputs:
    """Everything a plan needs. Prices are raw rupees on the latest session's basis."""

    ticker: str
    tier: Tier
    entry: Decimal
    stop: Decimal
    capital: Decimal
    risk_pct: float
    # The mood's risk multiplier: 0.5 when the engine's regime filter is on (defend).
    risk_multiplier: float
    mood: str | None  # "attack" / "normal" / "defend"; None when there is no scan
    atr: float | None  # ATR(14) on the latest session
    avg_volume20: float | None  # shares, the 20 sessions before the latest
    median_turnover: float | None  # rupees, for the slippage bucket
    sector: str | None
    open_risk: Decimal  # the real portfolio's open risk before this buy
    sector_value: Decimal  # what the portfolio already holds in this sector
    sector_cap_pct: Decimal
    # True: a results meeting falls in the blackout; None: the calendar isn't loaded.
    results_blackout: bool | None
    results_line: str  # the signal's event-risk wording for this stock
    ex_dates: Sequence[str] = ()
    heat_warn_pct: Decimal = Decimal(str(RULES.heat_warn_pct))
    heat_block_pct: Decimal = Decimal(str(RULES.heat_block_pct))
    # The real account and its limits; without them the guardrails aren't checked.
    account: AccountState | None = None
    limits: Limits | None = None
    # The kill switch's reason (app/halt.py) when Jeron is stopped: no buy is saved.
    halted: str | None = None
    # Why I'm trading through a drawdown (needed from `Limits.drawdown_journal_pct`).
    drawdown_note: str = ""


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    status: str  # "pass" / "fail" / "warn"
    detail: str
    hard: bool = True


@dataclass(frozen=True)
class Plan:
    inputs: PlanInputs
    shares: int
    sized_by: str  # which rule set the size
    risk_per_share: Decimal
    risk_amount: Decimal  # (entry - stop) x shares
    position_value: Decimal
    position_pct: Decimal  # of capital
    target1: Decimal
    target2: Decimal
    reward_risk_t1: Decimal | None  # after costs
    reward_risk_t2: Decimal | None
    round_trip_costs: Decimal | None  # to T2, charges and slippage
    slippage_pct: float
    stop_distance_pct: Decimal | None
    stop_atr: Decimal | None  # the stop's distance in ATRs
    heat_before_pct: Decimal
    heat_after_pct: Decimal
    sector_before_pct: Decimal
    sector_after_pct: Decimal
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blockers

    @property
    def blockers(self) -> list[str]:
        return [f"{c.label}: {c.detail}" for c in self.checks if c.hard and c.status == "fail"]


def rules_for(risk_pct: float) -> PortfolioRules:
    """The engine's portfolio rules with my risk % (as paper trading sets them)."""
    return replace(RULES, risk_pct=risk_pct)


def sized_by(
    shares: int, capital: float, entry: float, avg_volume: float | None, rules: PortfolioRules
) -> str:
    """Which of the engine's three limits set `shares` (for the explanation only)."""
    if shares < 1:
        return "too small"
    if avg_volume is not None and shares == math.floor(avg_volume * rules.max_volume_pct / 100):
        return f"{_g(rules.max_volume_pct)}% of 20-day average volume"
    if shares == math.floor(capital * rules.max_position_pct / 100 / entry):
        return f"{_g(rules.max_position_pct)}% of capital"
    return "risk per trade"


def build_plan(p: PlanInputs) -> Plan:
    tier = TIERS[p.tier]
    rules = tier.apply(rules_for(p.risk_pct))
    entry, stop = float(p.entry), float(p.stop)
    distance = entry - stop
    capital = float(p.capital)
    checks: list[Check] = []
    valid = p.entry > 0 and p.stop > 0 and distance > 0

    checks.append(
        Check(
            "stop_below_entry",
            "Stop below entry",
            "pass" if valid else "fail",
            f"stop ₹{_q(p.stop)} vs entry ₹{_q(p.entry)}"
            if valid
            else "the stop must be below the entry",
        )
    )
    shares = 0
    multiplier = p.risk_multiplier
    braked = p.account is not None and p.account.drawdown_pct >= Decimal(
        str(rules.drawdown_halve_pct)
    )
    if braked:
        multiplier *= 0.5
    if valid:
        avg = math.nan if p.avg_volume20 is None else p.avg_volume20
        shares = max(0, position_size(capital, rules, multiplier, entry, stop, 1.0, avg))
    one_r = p.entry - p.stop if valid else ZERO
    target1 = _q(p.entry + Decimal(str(rules.t1_r)) * one_r)
    target2 = _q(p.entry + Decimal(str(rules.t2_r)) * one_r)
    slip = COSTS.slippage_pct(p.median_turnover or 0.0)
    rr1 = rr2 = costs = None
    if valid and shares > 0:
        rr1 = _q(reward_risk(COSTS, entry, distance, shares, slip, rules.t1_r))
        rr2 = _q(reward_risk(COSTS, entry, distance, shares, slip, rules.t2_r))
        costs = _q(round_trip_costs(COSTS, entry, distance, shares, slip, rules.t2_r))
    stop_pct = _q(one_r / p.entry * 100) if valid else None
    stop_atr = _q(distance / p.atr) if valid and p.atr else None

    # Spec section 4: entry-to-stop at least 1 x ATR, at most the tier's %.
    if not valid:
        pass
    elif p.atr is None or p.atr <= 0:
        checks.append(
            Check(
                "stop_min_atr",
                "Stop at least 1 x ATR",
                "fail",
                "no ATR(14): the stock has too little price history",
            )
        )
    else:
        ok = distance >= rules.min_stop_atr * p.atr
        checks.append(
            Check(
                "stop_min_atr",
                f"Stop at least {_g(rules.min_stop_atr)} x ATR",
                "pass" if ok else "fail",
                f"{stop_atr} x ATR (ATR {p.atr:.2f})"
                + ("" if ok else ": too tight, normal noise would stop it out"),
            )
        )
    if valid and stop_pct is not None:
        ok = float(stop_pct) <= tier.max_stop_pct
        checks.append(
            Check(
                "stop_max_pct",
                f"Stop at most {_g(tier.max_stop_pct)}% away ({p.tier.value})",
                "pass" if ok else "fail",
                f"{stop_pct}% below the entry",
            )
        )
    if valid:
        if rr2 is None:
            checks.append(
                Check(
                    "reward_risk",
                    "Reward:risk to T2 at least 2 after costs",
                    "fail",
                    "no size, so no reward:risk",
                )
            )
        else:
            ok = float(rr2) >= rules.min_reward_risk_t2
            checks.append(
                Check(
                    "reward_risk",
                    f"Reward:risk to T2 at least {_g(rules.min_reward_risk_t2)} after costs",
                    "pass" if ok else "fail",
                    f"{rr2} after about ₹{costs} of charges and slippage",
                )
            )
        checks.append(
            Check(
                "size",
                "At least one share",
                "pass" if shares >= 1 else "fail",
                f"{shares} shares, set by {sized_by(shares, capital, entry, p.avg_volume20, rules)}"
                if shares >= 1
                else "the risk budget buys less than one share",
            )
        )

    risk_amount = _q(one_r * shares)
    value = _q(p.entry * shares)
    small = small_trade_warning(float(risk_amount), COSTS) if shares >= 1 else None
    if small:
        checks.append(Check("small_trade", "Charges worth the trade", "warn", small, hard=False))
    heat_before = _q(p.open_risk / p.capital * 100) if p.capital > 0 else ZERO
    heat_after = _q((p.open_risk + risk_amount) / p.capital * 100) if p.capital > 0 else ZERO
    if heat_after > p.heat_block_pct:
        checks.append(
            Check(
                "heat",
                f"Portfolio heat at most {_g(p.heat_block_pct)}%",
                "fail",
                f"{heat_after}% after this buy (now {heat_before}%): no new entries above "
                f"{_g(p.heat_block_pct)}%",
            )
        )
    else:
        warn = heat_after >= p.heat_warn_pct
        checks.append(
            Check(
                "heat",
                f"Portfolio heat at most {_g(p.heat_block_pct)}%",
                "warn" if warn else "pass",
                f"{heat_after}% after this buy (now {heat_before}%)"
                + (f", at the {_g(p.heat_warn_pct)}% warning level" if warn else ""),
            )
        )
    sector_before = _q(p.sector_value / p.capital * 100) if p.capital > 0 else ZERO
    sector_after = _q((p.sector_value + value) / p.capital * 100) if p.capital > 0 else ZERO
    if not p.sector:
        checks.append(
            Check(
                "sector",
                f"Sector at most {_g(p.sector_cap_pct)}% of capital",
                "warn",
                "sector unknown (not in the Nifty 500 list): not capped",
                hard=False,
            )
        )
    else:
        ok = sector_after <= p.sector_cap_pct
        checks.append(
            Check(
                "sector",
                f"Sector at most {_g(p.sector_cap_pct)}% of capital",
                "pass" if ok else "fail",
                f"{p.sector}: {sector_after}% after this buy (now {sector_before}%)",
            )
        )
    if p.results_blackout is None:
        checks.append(
            Check(
                "results",
                "No results within the blackout",
                "warn",
                p.results_line,
                hard=False,
            )
        )
    else:
        checks.append(
            Check(
                "results",
                "No results within the blackout",
                "fail" if p.results_blackout else "pass",
                p.results_line,
            )
        )
    if p.ex_dates:
        checks.append(
            Check("ex_dates", "Corporate actions ahead", "warn", "; ".join(p.ex_dates), hard=False)
        )
    if p.mood is None:
        checks.append(
            Check("mood", "Market mood", "warn", "unknown: no completed scan", hard=False)
        )
    elif p.mood == "defend":
        checks.append(
            Check(
                "mood",
                "Market mood",
                "warn",
                f"defend: risk per trade x{_g(p.risk_multiplier)}, size already halved",
                hard=False,
            )
        )
    else:
        checks.append(
            Check("mood", "Market mood", "pass", f"{p.mood}: full risk per trade", hard=False)
        )
    checks += guardrails(p, rules, braked)
    if p.halted:
        checks.append(
            Check(
                "halted",
                "Kill switch off",
                "fail",
                f"Jeron is stopped: {p.halted}. Run `python -m app.cli resume` when it is "
                "sorted (docs/runbook.md).",
            )
        )
    return Plan(
        inputs=p,
        shares=shares,
        sized_by=sized_by(shares, capital, entry, p.avg_volume20, rules) if valid else "no size",
        risk_per_share=_q(one_r),
        risk_amount=risk_amount,
        position_value=value,
        position_pct=_q(value / p.capital * 100) if p.capital > 0 else ZERO,
        target1=target1,
        target2=target2,
        reward_risk_t1=rr1,
        reward_risk_t2=rr2,
        round_trip_costs=costs,
        slippage_pct=slip,
        stop_distance_pct=stop_pct,
        stop_atr=stop_atr,
        heat_before_pct=heat_before,
        heat_after_pct=heat_after,
        sector_before_pct=sector_before,
        sector_after_pct=sector_after,
        checks=checks,
    )


def _inr(value: Decimal) -> str:
    return f"₹{abs(value):,.0f}"


def guardrails(p: PlanInputs, rules: PortfolioRules, braked: bool) -> list[Check]:
    """The real account's limits (module notes). Empty without the account."""
    a, lim = p.account, p.limits
    if a is None or lim is None:
        return []
    checks = []
    halve, pause = Decimal(str(rules.drawdown_halve_pct)), Decimal(str(rules.drawdown_pause_pct))
    where = f"account {a.drawdown_pct}% below its peak of {_inr(a.peak)}"
    if a.drawdown_pct >= pause:
        checks.append(
            Check(
                "drawdown",
                f"Drawdown brake (halve at {_g(halve)}%, pause at {_g(pause)}%)",
                "fail",
                f"{where}: new entries paused (spec section 5). Review the journal's "
                "recent trades before the next one.",
            )
        )
    else:
        checks.append(
            Check(
                "drawdown",
                f"Drawdown brake (halve at {_g(halve)}%, pause at {_g(pause)}%)",
                "warn" if braked else "pass",
                f"{where}: risk per trade halved" if braked else where,
                hard=False,
            )
        )
    if paper_first(a.drawdown_pct, lim.drawdown_journal_pct, float(pause)):
        words = note_words(p.drawdown_note)
        written = words >= NOTE_MIN_WORDS
        checks.append(
            Check(
                "drawdown_note",
                f"Paper first below -{_g(lim.drawdown_journal_pct)}%: write why",
                "pass" if written else "fail",
                f"drawdown note written ({words} words)"
                if written
                else f"{where}: signals are paper only. To trade this one anyway, write "
                f"in the drawdown note, in at least {NOTE_MIN_WORDS} words, why this trade "
                f"and why now, and what you'll do if it fails ({words} so far).",
            )
        )
    tier = p.tier.value
    held = a.open_by_tier.get(tier, 0)
    checks.append(
        Check(
            "positions",
            f"{tier.capitalize()} positions at most {lim.max_positions}",
            "fail" if held >= lim.max_positions else "pass",
            f"{held} open now" + (": close one first" if held >= lim.max_positions else ""),
        )
    )
    capital = p.capital
    for key, label, pct, lost, when in (
        ("daily_loss", "Daily loss limit", lim.daily_loss_pct, a.realised_today, "today"),
        ("weekly_loss", "Weekly loss limit", lim.weekly_loss_pct, a.realised_week, "this week"),
    ):
        if pct <= 0 or capital <= 0:
            continue
        limit = capital * Decimal(str(pct)) / 100
        over = lost < 0 and -lost >= limit
        realised = f"realised {when}: {'-' if lost < 0 else ''}{_inr(lost)}"
        checks.append(
            Check(
                key,
                f"{label} {_g(pct)}% ({_inr(limit)})",
                ("fail" if lim.block else "warn") if over else "pass",
                realised + (": no new entries until the limit resets" if over else ""),
                hard=lim.block,
            )
        )
    if lim.max_entries_week > 0:
        over = a.entries_week >= lim.max_entries_week
        checks.append(
            Check(
                "entries_week",
                f"New positions this week at most {lim.max_entries_week}",
                ("fail" if lim.block else "warn") if over else "pass",
                f"{a.entries_week} since Monday" + (": the week's cap is reached" if over else ""),
                hard=lim.block,
            )
        )
    return checks


def note_words(note: str) -> int:
    return len(note.split())


def paper_first(drawdown_pct: Decimal, journal_pct: float, pause_pct: float) -> bool:
    """True from `journal_pct` below the peak up to the pause (where nothing is saved
    anyway); a 0 turns the rule off."""
    return 0 < journal_pct <= float(drawdown_pct) < pause_pct


def missing_checklist(ticked: Iterable[str]) -> list[str]:
    """The checklist items not ticked, as worded."""
    done = set(ticked)
    return [label for key, label in CHECKLIST if key not in done]
