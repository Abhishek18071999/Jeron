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
- Warnings (shown, not blocking): heat at the 5% warning level, defend mode, a results
  calendar that isn't loaded, ex-dates ahead.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal

from app.backtest.costs import CostModel
from app.backtest.engine import PortfolioRules, position_size, reward_risk, round_trip_costs
from app.backtest.strategies import TIERS, Tier

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


def _q(value: Decimal | float, places: str = "0.01") -> Decimal:
    return Decimal(str(value)).quantize(Decimal(places))


def _g(value: float | Decimal) -> str:
    return f"{float(value):g}"


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
    rules = rules_for(p.risk_pct)
    tier = TIERS[p.tier]
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
    if valid:
        avg = math.nan if p.avg_volume20 is None else p.avg_volume20
        shares = max(0, position_size(capital, rules, p.risk_multiplier, entry, stop, 1.0, avg))
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


def missing_checklist(ticked: Iterable[str]) -> list[str]:
    """The checklist items not ticked, as worded."""
    done = set(ticked)
    return [label for key, label in CHECKLIST if key not in done]
