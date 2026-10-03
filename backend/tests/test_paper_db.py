"""Paper trading end to end on a real Postgres, with the backtest tests' made-up stocks."""

from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.backtest.job import run_backtests
from app.main import app
from app.models import PaperAccount, PaperDay, PaperTrade, ScanRun, SignalRecord
from app.paper.job import run_paper
from app.scan.score import SCORE_VERSION
from app.signals.build import IST
from app.signals.schema import Signal
from tests.conftest import requires_db
from tests.test_backtest_db import DAYS
from tests.test_backtest_db import session as session  # noqa: F401 - the fixture

pytestmark = requires_db

START, MIDDLE, END = DAYS[-120], DAYS[-30], DAYS[-1]


def _scans(session, days, status="ok"):
    for day in days:
        session.add(
            ScanRun(
                trade_date=day,
                score_version=SCORE_VERSION,
                status=status,
                details={} if status == "ok" else {"reasons": ["Data quality FAILED"]},
            )
        )
    session.commit()


def _count(session, model, **where):
    query = select(func.count()).select_from(model)
    for name, value in where.items():
        query = query.where(getattr(model, name) == value)
    return session.scalar(query)


def test_paper_trading_records_signals_and_updates_daily(session):
    # No backtest yet: no account, no signals.
    _scans(session, DAYS[-120:])
    first = run_paper(session, START, ["breakout-52w"])
    assert [a.status for a in first.accounts] == ["no_backtest"]

    (run,) = run_backtests(session, ["score-swing"])
    now = datetime(2026, 1, 1, 19, 0, tzinfo=IST)
    opened = run_paper(session, START, ["score-swing"], now=now)
    (account_outcome,) = opened.accounts
    account = session.get_one(PaperAccount, account_outcome.account_id)
    assert account.start_date == START and account.backtest_run_id == run.id
    assert account.live_eligible == run.live_eligible
    assert account.params == run.summary["schedule"][-1]["params"]
    assert account.rules["sector_cap_pct"] == 30.0 and account.rules["max_correlated"] == 2

    # Catch up to MIDDLE, then one day at a time to END.
    run_paper(session, MIDDLE, ["score-swing"], now=now)
    at_middle = {
        r.signal_id: r.payload
        for r in session.scalars(select(SignalRecord).where(SignalRecord.account_id == account.id))
    }
    assert at_middle, "the made-up market should give score-swing some signals"
    for day in DAYS[-29:]:
        run_paper(session, day, ["score-swing"], now=now)
    session.expire_all()
    signals = session.scalars(
        select(SignalRecord).where(SignalRecord.account_id == account.id)
    ).all()
    # Signals already issued are never changed.
    for row in signals:
        if row.signal_id in at_middle:
            assert row.payload == at_middle[row.signal_id]
        Signal.model_validate(row.payload)
        assert row.research_only == (not account.live_eligible)
        assert row.signal_date >= START
    # Re-running a day adds nothing.
    again = run_paper(session, END, ["score-swing"], now=now)
    assert again.accounts[0].new_signals == 0
    assert _count(session, SignalRecord, account_id=account.id) == len(signals)

    trades = session.scalars(select(PaperTrade).where(PaperTrade.account_id == account.id)).all()
    assert trades
    ids = {r.signal_id for r in signals}
    assert all(t.signal_id in ids for t in trades)
    for t in trades:
        assert t.entry_date > t.signal_date
        if t.status == "open":
            assert t.current_stop is not None and t.shares_held > 0
        else:
            assert t.exit_date is not None and t.exit_reason
    days = session.scalars(
        select(PaperDay).where(PaperDay.account_id == account.id).order_by(PaperDay.trade_date)
    ).all()
    assert days[0].trade_date == START and days[-1].trade_date == END
    assert days[0].equity == Decimal("1000000.00")
    session.refresh(account)
    assert account.last_date == END
    assert account.summary["open_positions"] == sum(t.status == "open" for t in trades)

    client = TestClient(app)
    (listed,) = client.get("/paper/accounts").json()
    assert listed["id"] == account.id
    assert listed["stage"] == ("paper" if account.live_eligible else "research only")
    view = client.get(f"/paper/accounts/{account.id}").json()
    assert len(view["open_trades"]) + len(view["closed_trades"]) == len(trades)
    assert len(view["days"]) == len(days)
    newest = client.get("/signals", params={"limit": 5}).json()
    assert newest and newest[0]["strategy_key"] == "score-swing"
    one = client.get(f"/signals/{newest[0]['signal_id']}").json()
    assert one["payload"]["ticker"] == newest[0]["ticker"]
    assert client.get("/paper/accounts/999999").status_code == 404


def test_paper_refuses_a_day_without_a_scan(session):
    run_backtests(session, ["score-swing"])
    outcome = run_paper(session, END, ["score-swing"])
    assert outcome.status == "blocked"
    assert outcome.reasons == [f"No scan for {END}; run the scan first."]
    _scans(session, [END], status="blocked")
    outcome = run_paper(session, END, ["score-swing"])
    assert outcome.reasons == [f"The scan for {END} was blocked: Data quality FAILED"]
    assert _count(session, PaperAccount) == 0


def test_restart_opens_a_new_account(session):
    run_backtests(session, ["score-swing"])
    _scans(session, [MIDDLE, END])
    first = run_paper(session, MIDDLE, ["score-swing"]).accounts[0].account_id
    second = run_paper(session, END, ["score-swing"], restart=True).accounts[0].account_id
    assert first != second
    assert session.get_one(PaperAccount, first).status == "closed"
    assert session.get_one(PaperAccount, second).start_date == END
