"""Every strategy end to end on a real Postgres, with made-up stocks that also have a
results calendar and quarterly results: each one backtests, opens a paper account,
and shows in its section; the combined book backtests."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.backtest.job import run_backtests
from app.backtest.strategies import COMBINED, STRATEGIES
from app.data import store
from app.data.events import BoardMeeting
from app.main import app
from app.models import BacktestRun, FinancialResult, PaperAccount, SignalRecord
from app.paper.job import run_paper
from app.signals.build import IST
from tests.conftest import requires_db
from tests.test_backtest_db import DAYS, SYMBOLS
from tests.test_backtest_db import session as session  # noqa: F401 - the fixture
from tests.test_paper_db import _scans

pytestmark = requires_db


def _quarter_ends() -> list[date]:
    ends, year = [], DAYS[0].year - 1
    while True:
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            end = date(year, month, day)
            if end + timedelta(days=45) > DAYS[-1]:
                return ends
            ends.append(end)
        year += 1


def _results(session) -> None:
    """Quarterly results for every stock, published 45 days after each quarter, profit
    growing 5% a quarter; the board meeting on the day they were published."""
    meetings = []
    for n, symbol in enumerate([*SYMBOLS, "SPLITCO", "NEWNAME"]):
        for q, end in enumerate(_quarter_ends()):
            published = end + timedelta(days=45)
            profit = Decimal(f"{1e8 * 1.05**q * (1 + n / 10):.2f}")
            session.add(
                FinancialResult(
                    symbol=symbol,
                    company=f"{symbol} Ltd",
                    period_start=end.replace(day=1) - timedelta(days=60),
                    period_end=end,
                    consolidated=True,
                    audited=False,
                    standard="Ind-AS New",
                    disseminated_at=datetime.combine(published, datetime.min.time(), IST),
                    xbrl_url=f"https://example.test/{symbol}/{end}.xml",
                    revenue=profit * 8,
                    other_income=profit / 20,
                    total_income=profit * 8,
                    finance_costs=profit / 10,
                    depreciation=profit / 5,
                    profit_before_tax=profit * Decimal("1.3"),
                    tax=profit * Decimal("0.3"),
                    net_profit=profit,
                    profit_to_owners=profit,
                    eps=(profit / 10_000_000).quantize(Decimal("0.0001")),
                    paid_up_capital=Decimal(100_000_000),
                    face_value=Decimal(10),
                    facts={},
                )
            )
            meetings.append(BoardMeeting(symbol, published, "Financial Results", announced=None))
    store.save_board_meetings(session, meetings, "test")
    session.commit()


def test_every_strategy_backtests_paper_trades_and_shows_in_its_section(session):
    _results(session)
    lines: list[str] = []
    runs = run_backtests(session, [*STRATEGIES, *COMBINED], log=lines.append)
    assert not [line for line in lines if ": skipped, " in line]
    assert {r.strategy_key for r in runs} == {*STRATEGIES, *COMBINED}
    assert session.scalar(select(func.count()).select_from(BacktestRun)) == len(runs)

    _scans(session, DAYS[-120:])
    outcome = run_paper(session, DAYS[-120], list(STRATEGIES))
    assert sorted(a.strategy_key for a in outcome.accounts) == sorted(STRATEGIES)
    assert all(a.status == "ok" for a in outcome.accounts), outcome.accounts
    later = run_paper(session, DAYS[-1], list(STRATEGIES))
    assert all(a.status == "ok" for a in later.accounts), later.accounts
    assert session.scalar(select(func.count()).select_from(PaperAccount)) == len(STRATEGIES)

    client = TestClient(app)
    sections = client.get("/sections").json()
    shown = {s["key"] for section in sections for s in section["strategies"]}
    assert shown == set(STRATEGIES)
    for section in sections:
        for s in section["strategies"]:
            assert s["backtested"] and s["account_id"] is not None, s
        detail = client.get(f"/sections/{section['key']}")
        assert detail.status_code == 200, detail.text

    # Each strategy's newest signal, as its section shows it: what, when, how much, why.
    newest = session.execute(
        select(PaperAccount.strategy_key, func.max(SignalRecord.signal_date))
        .select_from(SignalRecord)
        .join(PaperAccount, PaperAccount.id == SignalRecord.account_id)
        .group_by(PaperAccount.strategy_key)
    ).all()
    assert {"score-swing", "rs-pullback", "quality-trend"} <= {key for key, _ in newest}
    for key, day in newest:
        tier = STRATEGIES[key].tier.value
        cards = client.get(f"/sections/{tier}", params={"date": str(day)}).json()["signals"]
        mine = [c for c in cards if c["strategy_key"] == key]
        assert mine, key
        for c in mine:
            assert c["what"] and c["when"] and c["how_much"] and c["why"], c
            assert c["shares"] > 0 and float(c["stop"]) < float(c["entry_high"]), c
