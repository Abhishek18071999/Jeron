"""The pre-open check on a real Postgres: journal positions -> exit plans, events,
stale data, one message per day."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.alerts.format import inr
from app.calendar.nse import TradingCalendar
from app.config import Settings
from app.data import store
from app.data.events import BoardMeeting
from app.data.provider import CorporateActionRecord
from app.enums import CorporateActionType
from app.exits.job import build_preopen, check_day, preopen_message, run_preopen
from app.exits.rules import Action
from app.journal.service import add_fill, manual_entry
from app.models import Alert
from app.signals.build import IST
from tests.conftest import requires_db
from tests.test_alerts_db import FakeChannel
from tests.test_alerts_db import empty_session as empty_session  # noqa: F401 - the fixture
from tests.test_backtest_db import _bar

pytestmark = requires_db

CAL = TradingCalendar.default()
DAYS = list(CAL.trading_days(date(2025, 6, 2), date(2025, 8, 29)))


def _setup(s, up_to: date):
    """UP rises 1% a day from 100; FLAT stays at 100. Both bought on DAYS[20]."""
    days = [d for d in DAYS if d <= up_to]
    store.save_bars(s, store.NSE_BARS, [_bar("UP", d, 100 * 1.01**i) for i, d in enumerate(days)])
    store.save_bars(s, store.NSE_BARS, [_bar("FLAT", d, 100) for d in days])
    s.commit()
    up = manual_entry(s, "UP", stop=Decimal("110"))
    add_fill(s, up, DAYS[20], "buy", 100, Decimal(str(round(100 * 1.01**20, 2))))
    flat = manual_entry(s, "FLAT", stop=Decimal("96"))
    add_fill(s, flat, DAYS[20], "buy", 50, Decimal("100"))
    manual_entry(s, "NOSTOP")
    return up, flat


def test_preopen_plans_and_events(empty_session):
    s = empty_session
    _setup(s, DAYS[44])
    day = DAYS[45]
    store.save_board_meetings(
        s, [BoardMeeting("FLAT", DAYS[46], "Financial Results", announced=None)], "test"
    )
    store.save_actions(
        s,
        store.NSE_ACTIONS,
        [CorporateActionRecord("UP", DAYS[47], CorporateActionType.SPLIT, Decimal(2), Decimal(1))],
    )
    s.commit()
    p = build_preopen(s, day, CAL)
    assert not p.stale and p.data_as_of == DAYS[44]
    by = {c.ticker: c for c in p.positions}
    assert set(by) == {"UP", "FLAT"}  # NOSTOP has no fills: not open

    up = by["UP"]
    assert up.plan is not None and up.plan.t1_hit is not None and up.plan.trail is not None
    assert up.plan.action == Action.SELL_HALF  # T1 reached, nothing sold yet
    assert up.r_now is not None and up.r_now > 2
    assert up.tier_assumed

    flat = by["FLAT"]
    assert flat.plan is not None and flat.plan.action == Action.SELL_ALL
    assert flat.plan.reason.startswith("time stop")
    assert any("results board meeting" in e for e in flat.events)
    assert any(e.startswith("split 2:1") for e in up.events), up.events

    text = preopen_message(p, "http://jeron.local")
    assert text.index("SELL ALL") < text.index("SELL HALF")
    assert "FLAT 50 sh" in text and "UP 100 sh" in text
    assert "EVENTS" in text and "Journal: http://jeron.local/journal" in text


def test_partial_sale_and_stale_prices(empty_session):
    s = empty_session
    up, _ = _setup(s, DAYS[44])
    add_fill(s, up, DAYS[40], "sell", 50, Decimal("140"))
    p = build_preopen(s, DAYS[45], CAL)
    (plan,) = [c.plan for c in p.positions if c.ticker == "UP"]
    assert plan is not None and plan.action == Action.HOLD
    assert inr(round(plan.trail, 2)) in plan.reason

    stale = build_preopen(s, DAYS[47], CAL)  # DAYS[45] and [46] are not loaded
    assert stale.stale
    text = preopen_message(stale)
    assert "not loaded" in text and "SELL" not in text


def test_sent_once_per_day(empty_session):
    s = empty_session
    _setup(s, DAYS[44])
    channel = FakeChannel()
    now = datetime(2025, 8, 4, 8, 30, tzinfo=IST)
    assert check_day(CAL, now) == date(2025, 8, 4)
    assert check_day(CAL, datetime(2025, 8, 2, 8, 30, tzinfo=IST)) == date(2025, 8, 4)  # Sat
    settings = Settings(web_url="")
    _, outcome = run_preopen(s, DAYS[45], settings=settings, channels=[channel], now=now)
    assert outcome.sent == [f"preopen:{DAYS[45]}"]
    _, again = run_preopen(s, DAYS[45], settings=settings, channels=[channel], now=now)
    assert again.already_sent == 1 and len(channel.sent) == 1
    alert = s.scalar(select(Alert).where(Alert.kind == "preopen"))
    assert alert is not None and alert.status == "sent"
