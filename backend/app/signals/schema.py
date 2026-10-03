"""The signal schema (spec section 4). Every field is required; a signal that doesn't
validate is rejected and never stored.

Prices are rupees per share as traded on the signal date (raw, not adjusted for
later splits). Signals are immutable once stored; a change would be a new version.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "signal-v1"
# Spec section 4: entry-to-stop at most 12% (swing) or 20% (positional and investing),
# measured from the signal close (the entry zone's low), as the engine does.
MAX_STOP_PCT = {"swing": Decimal(12), "positional": Decimal(20), "invest": Decimal(20)}
MIN_REWARD_RISK_T2 = Decimal(2)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EntryZone(_Strict):
    low: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    valid_until: date


class Stop(_Strict):
    price: Decimal = Field(gt=0)
    type: Literal["structural", "ATR"]
    reason: str = Field(min_length=1)


class Targets(_Strict):
    t1: Decimal = Field(gt=0)
    t2: Decimal = Field(gt=0)
    basis: str = Field(min_length=1)


class Holding(_Strict):
    min_days: int = Field(ge=1)
    max_days: int = Field(ge=1)


class Brains(_Strict):
    technical: Decimal = Field(ge=0, le=100)
    # The fundamental and news brains arrive in M6; until then they are null and the
    # combined score is the technical score.
    fundamental: Decimal | None = Field(ge=0, le=100)
    news: Decimal | None = Field(ge=0, le=100)
    combined: Decimal = Field(ge=0, le=100)


class BacktestStats(_Strict):
    trades: int = Field(ge=0)
    win_rate: Decimal
    avg_R: Decimal  # noqa: N815 - the spec's field name
    expectancy_R: Decimal  # noqa: N815
    profit_factor: Decimal | None  # null when there were no losing trades
    max_drawdown_pct: Decimal
    period: str = Field(min_length=1)


class Signal(_Strict):
    signal_id: UUID
    created_at: datetime
    data_as_of: datetime
    ticker: str = Field(min_length=1)
    setup_name: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    tier: Literal["swing", "positional", "invest"]
    direction: Literal["long"]
    why: list[str] = Field(min_length=3, max_length=5)
    entry_zone: EntryZone
    stop: Stop
    targets: Targets
    risk_reward_t1: Decimal
    risk_reward_t2: Decimal
    expected_holding: Holding
    shares: int = Field(ge=1)
    capital_at_risk: Decimal = Field(gt=0)
    exit_plan: str = Field(min_length=1)
    time_stop_days: int = Field(ge=1)
    invalidation: str = Field(min_length=1)
    event_risk: str = Field(min_length=1)
    conviction: int = Field(ge=1, le=5)
    brains_breakdown: Brains
    backtest_stats: BacktestStats
    # Jeron's additions to the spec's fields.
    research_only: bool  # the strategy hasn't passed section 6: paper-traded, never alerted
    notes: list[str]

    @model_validator(mode="after")
    def _consistent(self) -> "Signal":
        zone, stop = self.entry_zone, self.stop.price
        if zone.valid_until <= self.data_as_of.date():
            raise ValueError("entry zone must be valid after the data date")
        if not stop < zone.low <= zone.high:
            raise ValueError("need stop < entry zone low <= entry zone high")
        if not zone.high < self.targets.t1 < self.targets.t2:
            raise ValueError("need entry zone high < T1 < T2")
        if (zone.low - stop) / zone.low * 100 > MAX_STOP_PCT[self.tier]:
            raise ValueError(f"stop more than {MAX_STOP_PCT[self.tier]}% below the signal close")
        if self.risk_reward_t2 < MIN_REWARD_RISK_T2:
            raise ValueError("reward:risk to T2 below 2 after costs")
        if self.expected_holding.min_days > self.expected_holding.max_days:
            raise ValueError("expected holding: min_days above max_days")
        if any(not reason.strip() for reason in self.why):
            raise ValueError("empty reason in why")
        return self
