"""The paper review end to end on a real Postgres (docs/plans/paper-review-v1.md): the
paper job's context, audit trail and missed signals; the review API; proposals stored
once and tested on the history before the paper account."""

from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.backtest.job import run_backtests
from app.backtest.market import build_market
from app.main import app
from app.models import PaperAccount, PaperEvent, PaperTrade, SignalRecord, StrategyProposal
from app.paper import optimize
from app.paper.job import run_paper
from app.paper.optimize import record_proposals, refresh_forward, validate
from app.paper.proposals import ClosedTrade, candidates
from app.signals.build import IST
from tests.conftest import requires_db
from tests.test_backtest_db import DAYS
from tests.test_backtest_db import session as session  # noqa: F401 - the fixture
from tests.test_backtest_walkforward import synthetic_inputs
from tests.test_paper_db import _scans

pytestmark = requires_db

START, END = DAYS[-120], DAYS[-1]
NOW = datetime(2026, 1, 1, 19, 0, tzinfo=IST)


def _count(session, model, **where):
    query = select(func.count()).select_from(model)
    for name, value in where.items():
        query = query.where(getattr(model, name) == value)
    return session.scalar(query)


def _paper(session):
    _scans(session, DAYS[-120:])
    run_backtests(session, ["score-swing"])
    run_paper(session, START, ["score-swing"], now=NOW)
    run_paper(session, END, ["score-swing"], now=NOW)
    return session.scalars(select(PaperAccount)).one()


def test_paper_job_stores_context_audit_trail_and_missed_signals(session):
    account = _paper(session)
    trades = session.scalars(select(PaperTrade).where(PaperTrade.account_id == account.id)).all()
    assert trades
    for t in trades:
        assert t.context["regime"] in ("bull", "bear", "sideways")
        assert isinstance(t.context["risk_off"], bool)
        assert t.context["score"] is not None

    signals = _count(session, SignalRecord, account_id=account.id)
    assert _count(session, PaperEvent, account_id=account.id, kind="signal") == signals
    assert _count(session, PaperEvent, account_id=account.id, kind="entry") == len(trades)
    closed = [t for t in trades if t.status == "closed"]
    assert _count(session, PaperEvent, account_id=account.id, kind="exit") == len(closed)
    first = session.scalars(select(PaperEvent).where(PaperEvent.account_id == account.id)).all()
    assert all(e.recorded_at == NOW for e in first)

    # A later re-run adds nothing and keeps the first recorded times.
    total = _count(session, PaperEvent, account_id=account.id)
    run_paper(session, END, ["score-swing"], now=datetime(2026, 1, 2, 19, 0, tzinfo=IST))
    assert _count(session, PaperEvent, account_id=account.id) == total
    session.expire_all()
    assert all(
        e.recorded_at == NOW
        for e in session.scalars(select(PaperEvent).where(PaperEvent.account_id == account.id))
    )

    session.refresh(account)
    missed = account.summary["missed"]
    assert missed["forward_sessions"] == 10
    assert missed["taken"]["count"] == len(trades)
    perf = account.summary["performance"]
    assert perf["curve"]["sessions"] == len(DAYS[-120:])
    assert perf["benchmark"]["sessions"] == len(DAYS[-120:])

    client = TestClient(app)
    view = client.get(f"/paper/accounts/{account.id}/review").json()
    r = view["review"]
    assert len(r["journal"]["open"]) + len(r["journal"]["closed"]) == len(trades)
    assert r["performance"]["trades"]["trades"] == len(closed)
    assert r["performance"]["backtest"]["trades"]["trades"] > 0
    assert r["limitations"][0].startswith("Simulated")
    assert r["audit_events"] == total
    assert {d["dimension"] for d in r["root_causes"]["dimensions"]} >= {"regime", "score_band"}
    audit = client.get(f"/paper/accounts/{account.id}/audit", params={"kind": "entry"}).json()
    assert len(audit) == len(trades) and all(e["kind"] == "entry" for e in audit)
    assert client.get("/paper/accounts/999999/review").status_code == 404
    assert client.get("/paper/accounts/999999/audit").status_code == 404


def test_proposals_are_recorded_once_and_validated(session, monkeypatch):
    account = _paper(session)
    rows = optimize._rows(session, account.id)
    assert rows
    # Make the rule fire on this market's trades: the group of the first trade's regime.
    regime = rows[0].context["regime"]
    loser = [ClosedTrade(-1.0 + i * 0.01, -1000.0, {"regime": regime}) for i in range(25)]
    winner = [ClosedTrade(0.8 + i * 0.01, 800.0, {"regime": "other"}) for i in range(25)]
    crafted = candidates(loser + winner)
    assert len(crafted) == 1
    monkeypatch.setattr(optimize, "candidates", lambda trades: crafted)

    (p,) = record_proposals(session, now=NOW)
    assert p.strategy_version == "score-swing-v1" and p.status == "proposed"
    assert p.dimension == "regime" and p.group_value == regime
    assert p.evidence["group"]["trades"] == 25
    # Made once, ever.
    assert record_proposals(session, now=NOW) == []
    assert _count(session, StrategyProposal) == 1

    assert refresh_forward(session, now=NOW) == 1
    assert p.forward is not None and p.forward["since"] == "2026-01-01"

    # The made-up history before the account is 4.6 years: too short for a walk-forward
    # test, and the proposal says so.
    validate(session, p, now=NOW)
    session.refresh(p)
    assert p.status == "could not test" and p.validated_at == NOW
    assert "before the paper account opened" in p.backtest["reason"]

    # On a longer market the check runs both versions and judges them.
    longer = build_market(synthetic_inputs(n_days=1700, n_stocks=30, seed=4))
    validate(session, p, market=longer, now=NOW)
    session.refresh(p)
    assert p.status in ("passed backtest", "failed backtest")
    bt = p.backtest
    assert bt["base"]["oos_trades"] >= bt["filtered"]["oos_trades"]
    assert (p.status == "passed backtest") == (bt["fails"] == [])

    client = TestClient(app)
    (listed,) = client.get("/paper/proposals").json()
    assert listed["id"] == p.id and listed["status"] == p.status
    review = client.get(f"/paper/accounts/{account.id}/review").json()["review"]
    assert [x["id"] for x in review["proposals"]] == [p.id]
    assert review["proposals_tested_all"] == 1
