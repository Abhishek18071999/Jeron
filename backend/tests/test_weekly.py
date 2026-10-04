"""The weekly summary and revalidation (spec sections 6 and 8) on Postgres."""

from datetime import date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.analytics.weekly import ROLLING_TRADES, build_weekly, run_weekly, weekly_message
from app.backtest.strategies import STRATEGIES
from app.config import Settings
from app.journal.service import add_fill, decide, update_entry
from app.main import app
from app.models import Alert, PaperAccount, PaperDay
from app.paper.job import retired_account
from app.signals.build import IST
from tests.conftest import requires_db
from tests.journal_helpers import make_account, make_signal
from tests.test_alerts_db import FakeChannel
from tests.test_alerts_db import empty_session as empty_session  # noqa: F401 - the fixture
from tests.test_compare import _paper_trade

pytestmark = requires_db

FRIDAY = date(2025, 3, 14)
SUMMARY = {"out_of_sample": {"curve": {"max_drawdown_pct": 10.0}}}


def _week(s):
    account = make_account(s, live=True, summary=SUMMARY)
    early = make_signal(s, account, "AAA", date(2025, 3, 7), date(2025, 3, 11))
    late = make_signal(s, account, "BBB", date(2025, 3, 7), date(2025, 3, 12))
    skipped = make_signal(s, account, "CCC", date(2025, 3, 7), date(2025, 3, 11))
    s.add_all(
        [
            _paper_trade(account, 1, early, "AAA", date(2025, 3, 10), 2.0),  # exits 17 Mar
            _paper_trade(account, 2, late, "BBB", date(2025, 3, 10), 1.0, status="open"),
            _paper_trade(account, 3, skipped, "CCC", date(2025, 3, 3), 1.5),  # exits 10 Mar
        ]
    )
    s.commit()
    # AAA: bought on time, sold early on 12 Mar for less than paper.
    a = decide(s, early, "taken", stop=Decimal(85))  # below the signal's 90
    add_fill(s, a, date(2025, 3, 10), "buy", 10, Decimal(100))
    add_fill(s, a, date(2025, 3, 12), "sell", 10, Decimal(105))
    update_entry(s, a, decision="taken", reason="", stop=Decimal(85), followed_plan=False, notes="")
    # BBB: bought three days after paper.
    b = decide(s, late, "taken")
    add_fill(s, b, date(2025, 3, 13), "buy", 10, Decimal(101))
    decide(s, skipped, "skipped", reason="didn't like it")
    return account


def test_weekly_summary(empty_session):
    s = empty_session
    _week(s)
    # The paper trade for AAA exits on 17 Mar; check the week of 17 Mar too.
    w = build_weekly(s, FRIDAY)
    assert w.week_start == date(2025, 3, 10)
    assert w.week.trades == 1 and w.to_date.trades == 1
    text = " | ".join(w.mistakes)
    assert "AAA: stop ₹85.00 is below the signal's ₹90.00" in text
    assert "AAA: marked as not following the plan" in text
    assert "BBB: bought 3 days after the paper entry" in text
    assert "CCC: skipped; paper made +1.50R" in text
    assert w.strict_count == 1 and w.strict_r == 1.5  # AAA's paper trade closes next week

    nxt = build_weekly(s, date(2025, 3, 21))
    assert any("AAA: sold on 12 Mar, before the rules did (17 Mar)" in m for m in nxt.mistakes)
    assert nxt.strict_r == 2.0 and round(nxt.mine_r, 3) == 0.333

    message = weekly_message(w, "http://jeron.local")
    for heading in ("MY REAL EDGE", "MISTAKES", "STRICT RULE-FOLLOWING"):
        assert heading in message
    assert "RETIRED" not in message


def test_revalidation_retires_and_paper_stops(empty_session):
    s = empty_session
    account = make_account(s, key="score-swing", live=True, summary=SUMMARY)
    account.strategy_version = STRATEGIES["score-swing"].version
    for i in range(ROLLING_TRADES):
        s.add(_paper_trade(account, i, None, f"S{i}", date(2025, 1, 1), -0.2))
    s.add(
        PaperDay(account_id=account.id, trade_date=FRIDAY, equity=1,
                 drawdown_pct=Decimal("16"), heat_pct=0, open_positions=0)
    )  # fmt: skip
    s.commit()
    channel = FakeChannel()
    now = datetime(2025, 3, 14, 19, 30, tzinfo=IST)
    w, outcome = run_weekly(s, FRIDAY, settings=Settings(web_url=""), channels=[channel], now=now)
    (retired,) = w.retired
    assert "rolling 50-trade expectancy -0.20R" in retired.reason
    assert "drawdown 16.0% above 1.5 x the backtest's 10.0%" in retired.reason
    s.refresh(account)
    assert account.status == "retired" and account.retired_on == FRIDAY
    assert retired_account(s, STRATEGIES["score-swing"]) is not None
    assert outcome.sent == ["weekly:2025-W11"]
    assert "RETIRED BY THE WEEKLY REVALIDATION" in channel.sent[0][1]
    run_weekly(s, FRIDAY, settings=Settings(web_url=""), channels=[channel], now=now)
    assert len(channel.sent) == 1  # once per week
    assert s.scalar(select(Alert.kind).where(Alert.key == "weekly:2025-W11")) == "weekly"
    assert s.scalars(select(PaperAccount.status)).all() == ["retired"]


def test_weekly_api_is_read_only(empty_session):
    s = empty_session
    account = make_account(s, live=True, summary=SUMMARY)
    for i in range(ROLLING_TRADES):
        s.add(_paper_trade(account, i, None, f"S{i}", date(2025, 1, 1), -0.2))
    s.commit()
    body = TestClient(app).get("/analytics/weekly", params={"day": "2025-03-14"}).json()
    assert body["week_start"] == "2025-03-10" and "MY REAL EDGE" in body["text"]
    s.refresh(account)
    assert account.status == "active"
