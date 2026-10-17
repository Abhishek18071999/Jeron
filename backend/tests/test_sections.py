"""The four sections (docs/plans/sections-v1.md): each section's state from its
strategies, and a signal as what, when, how much and why."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.backtest.strategies import STRATEGIES, Tier
from app.sections.calc import (
    BY_KEY,
    SECTIONS,
    SectionKey,
    State,
    StrategyState,
    card,
    section_for_tier,
    status,
)
from tests.test_signals import valid_payload


def _state(key="rs-pullback", **kw):
    values = dict(
        key=key,
        version=f"{key}-v1",
        name=key,
        summary="",
        tier=Tier.POSITIONAL,
        backtested=True,
        passed=False,
    )
    values.update(kw)
    return StrategyState(**values)


def test_four_sections_cover_every_strategy_tier():
    assert [s.key for s in SECTIONS] == ["swing", "intraday", "positional", "invest"]
    assert BY_KEY[SectionKey.INTRADAY].tier is None
    for strategy in STRATEGIES.values():
        assert BY_KEY[section_for_tier(strategy.tier.value)].tier is strategy.tier


def test_state_says_plainly_whether_there_is_anything_to_buy():
    positional = BY_KEY[SectionKey.POSITIONAL]
    live = status(positional, [_state(passed=True, account_id=3), _state("results-drift")])
    assert live.state is State.LIVE
    assert live.headline.startswith("Live: rs-pullback-v1 passed the backtest and is paper")

    not_opened = status(positional, [_state(passed=True)])
    assert not_opened.state is State.LIVE and "run paper" in not_opened.headline

    research = status(BY_KEY[SectionKey.SWING], [_state("score-swing", tier=Tier.SWING)])
    assert research.state is State.RESEARCH
    assert research.headline.startswith("Nothing to buy: no swing strategy has passed")

    retired = status(positional, [_state(passed=True, account_id=3, account_status="retired")])
    assert retired.state is State.RESEARCH

    waiting = status(
        BY_KEY[SectionKey.INVEST], [_state("quality-trend", tier=Tier.INVEST, backtested=False)]
    )
    assert waiting.state is State.UNTESTED
    assert "Run: backtest --strategy quality-trend, then paper." in waiting.headline

    intraday = status(BY_KEY[SectionKey.INTRADAY], [])
    assert intraday.state is State.NOT_RUNNING and "no intraday prices" in intraday.headline


def test_stage_of_a_strategy():
    assert _state(backtested=False).stage == "waiting for its first backtest"
    assert _state().stage == "research only"
    assert _state(passed=True).stage == "passed; paper account not opened yet"
    assert _state(passed=True, account_id=1, account_status="active").stage == "paper trading"
    assert _state(passed=True, account_id=1, account_status="retired").stage == "retired"


def test_card_says_what_when_how_much_and_why():
    payload = valid_payload() | {
        "invalidation": "Don't buy if it opens above ₹101.00 or below the stop"
    }
    c = card(uuid4(), date(2026, 10, 1), "score-swing", False, payload, Decimal(1_000_000))
    assert c.what == (
        "Buy AAA: Test setup, conviction 5/5. Stop ₹96.00, targets ₹108.00 and ₹112.00."
    )
    assert c.when.startswith("On Sat 3 Oct. 09:00-09:07, LIMIT BUY 1,980 at ₹101.00")
    assert c.when.endswith("Not filled by 09:15: cancel it.")
    assert c.cost == Decimal("199980.00") and c.cost_pct == Decimal("20.0")
    assert c.at_risk_pct == Decimal("0.99")
    assert c.how_much == (
        "1,980 shares, about ₹1,99,980 at the top of the zone (20.0% of capital), ₹9,900 at "
        "risk (0.99% of capital) if the stop is hit."
    )
    assert c.why == ["one", "two", "three"]
    assert c.holding == "3 to 15 sessions; time stop 15 sessions"
    assert c.backtest.startswith("412 trades out of sample, expectancy 0.19R")
    research = card(uuid4(), date(2026, 10, 1), "score-swing", True, payload, Decimal(1_000_000))
    assert research.what.startswith("Research only, not a trade: Buy AAA")
