"""Strategy statuses, health and the registry on Postgres (decision 0018)."""

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.analytics.strategies import may_resume, registry, set_status, strategy_views
from app.backtest.strategies import STRATEGIES
from app.main import app
from app.models import BacktestRun, BacktestTrade, PaperAccount, StrategyStatusChange
from app.signals.build import IST
from tests.conftest import requires_db
from tests.journal_helpers import make_account
from tests.test_alerts_db import empty_session as empty_session  # noqa: F401 - the fixture
from tests.test_compare import _paper_trade

pytestmark = requires_db

RS = STRATEGIES["rs-pullback"]
DAY = date(2025, 3, 14)
EVIDENCE = {"confidence": {"evidence": {"rating": "moderate", "checks": [], "summary": ""}}}


def _account(s, trades=36):
    summary = EVIDENCE | {
        "out_of_sample": {
            "curve": {"max_drawdown_pct": 10.0, "sessions": 1000},
            "trades": {"trades": 200},
        },
        "gates": [{"key": "expectancy", "passed": True}],
    }
    account = make_account(s, key=RS.key, live=True, summary=summary)
    account.strategy_version = RS.version
    run = s.get_one(BacktestRun, account.backtest_run_id)
    run.strategy_version = RS.version
    run.created_at = datetime(2025, 1, 1, 19, tzinfo=IST)
    account.last_date = date(2025, 6, 1)
    for i in range(200):
        s.add(
            BacktestTrade(
                run_id=run.id, seq=i, segment="oos", symbol="X", variant="v",
                signal_date=DAY, entry_date=DAY, exit_date=DAY, entry_price=1,
                stop_price=1, target_price=1, exit_price=1, shares=1, exit_reason="stop",
                gross_pnl=0, charges=0, dividends=0, net_pnl=(200, -100)[i % 2],
                r_multiple=(2, -1)[i % 2], regime="bull", score=90, sessions=1,
            )
        )  # fmt: skip
    for i in range(trades):
        s.add(_paper_trade(account, i, None, f"S{i}", date(2025, 1, 2), (2.0, -1.0)[i % 2]))
    s.commit()
    return account


def test_status_health_and_promotion(empty_session):
    s = empty_session
    account = _account(s)
    views = {v.version: v for v in strategy_views(s, date(2025, 6, 1))}
    rs = views[RS.version]
    assert rs.status.status == "paper" and rs.status.set_by == "jeron"
    assert rs.evidence and rs.evidence["rating"] == "moderate"
    assert rs.paper_gate and rs.paper_gate.status == "passed"
    assert rs.health and rs.health.verdict == "on track"
    assert rs.health.false_retirement is not None
    # Strategies without a run are research.
    assert views[STRATEGIES["score-swing"].version].status.status == "research"

    with pytest.raises(ValueError, match="Small capital comes first"):
        set_status(s, RS.version, "approved", "Feels good after a month of paper")
    with pytest.raises(ValueError, match="reason"):
        set_status(s, RS.version, "small-capital", "")
    view = set_status(s, RS.version, "small-capital", "Paper passed; evidence moderate")
    assert view.status == "small capital"
    row = s.scalars(select(StrategyStatusChange)).one()
    assert row.set_by == "owner" and row.evidence["evidence"] == "moderate"
    assert row.evidence["paper_gate"] == "passed"

    client = TestClient(app)
    listed = {r["version"]: r for r in client.get("/strategies").json()}
    assert listed[RS.version]["status"]["status"] == "small capital"
    assert listed[RS.version]["health"]["verdict"] == "on track"
    reg = client.get("/strategies/registry").json()
    assert reg["versions"] >= len(STRATEGIES) and reg["grid_points"] > 0
    assert "by luck alone" in reg["note"]
    assert account.status == "active"


def test_a_retired_strategy_needs_a_recorded_revalidation(empty_session):
    s = empty_session
    account = _account(s)
    retired_at = datetime(2025, 6, 2, 10, tzinfo=IST)
    set_status(s, RS.version, "retired", "Drawdown deeper than I can stomach", now=retired_at)
    s.refresh(account)
    assert account.status == "retired" and account.retired_on == date(2025, 6, 2)
    assert not may_resume(s, RS.version)
    with pytest.raises(ValueError, match="must pass the gates"):
        set_status(s, RS.version, "paper", "A few winners since, looks fine again")
    # A new run after the retirement that passes the gates: now it can go back to paper.
    s.add(
        BacktestRun(
            strategy_key=RS.key, strategy_version=RS.version, strategy_name=RS.name,
            tier="positional", data_start=date(2016, 1, 1), data_end=date(2026, 9, 30),
            oos_start=date(2019, 1, 1), holdout_start=date(2025, 10, 1), live_eligible=True,
            fingerprint="new", summary=EVIDENCE,
        )
    )  # fmt: skip
    s.commit()
    set_status(s, RS.version, "paper", "Rerun on data to Sept 2026 passes every gate")
    assert may_resume(s, RS.version)
    assert s.scalars(select(PaperAccount.status)).all() == ["retired"]  # kept, never reused


def test_registry_lists_versions_no_longer_in_the_code(empty_session):
    s = empty_session
    account = make_account(s, key="old-idea", live=False)
    s.commit()
    rows = {r.version: r for r in registry(s).rows}
    old = rows[account.strategy_version]
    assert not old.in_code and old.runs == 1 and old.live_eligible is False
    assert rows[RS.version].in_code and rows[RS.version].grid_points == len(RS.grid)
