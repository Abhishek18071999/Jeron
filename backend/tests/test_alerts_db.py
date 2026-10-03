"""M5 end to end on a real Postgres: scan -> paper signal -> alert -> journal."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from alembic import command
from app.alerts.channels import AlertError
from app.alerts.job import run_alerts, send_test
from app.backtest.job import run_backtests
from app.config import Settings, get_settings
from app.db import get_engine
from app.enums import Exchange
from app.main import app
from app.models import Alert, Instrument, SignalRecord
from app.paper.job import run_paper
from app.signals.build import IST
from tests.conftest import TEST_DATABASE_URL, requires_db
from tests.test_backtest_db import BACKEND_DIR, DAYS
from tests.test_backtest_db import session as session  # noqa: F401 - the fixture
from tests.test_paper_db import _scans

pytestmark = requires_db


@pytest.fixture
def empty_session(monkeypatch):
    """A migrated database with no data."""
    monkeypatch.setenv("JERON_DATABASE_URL", TEST_DATABASE_URL or "")
    get_settings.cache_clear()
    get_engine.cache_clear()
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    with Session(get_engine()) as s:
        yield s
    get_engine().dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()


START, END = DAYS[-120], DAYS[-1]
NOW = datetime(2026, 1, 1, 19, 0, tzinfo=IST)


class FakeChannel:
    def __init__(self, name="telegram", fail=False):
        self.name, self.fail, self.sent = name, fail, []

    def send(self, text, subject):
        if self.fail:
            raise AlertError("network down")
        self.sent.append((subject, text))


def _signal_day(session, live: bool) -> date:
    """Paper-trade score-swing over the last 120 days; the newest day with signals."""
    (run,) = run_backtests(session, ["score-swing"])
    run.live_eligible = live  # pretend it passed (or failed) section 6
    session.commit()
    _scans(session, DAYS[-120:])
    run_paper(session, START, ["score-swing"], now=NOW)
    run_paper(session, DAYS[-31], ["score-swing"], now=NOW)
    for d in DAYS[-30:]:  # day by day, as the daily job runs, so signals aren't late
        run_paper(session, d, ["score-swing"], now=NOW)
    day = session.scalar(
        select(func.max(SignalRecord.signal_date)).where(SignalRecord.late.is_(False))
    )
    assert day is not None, "the made-up market should give score-swing some signals"
    return day


def test_scan_signal_alert_journal(session):
    day = _signal_day(session, live=True)
    signals = session.scalars(
        select(SignalRecord).where(SignalRecord.signal_date == day).order_by(SignalRecord.ticker)
    ).all()
    settings = Settings(web_url="http://jeron.local")

    # Not set up: nothing is sent or stored.
    assert run_alerts(session, day, settings=settings, channels=[]).status == "not_configured"
    assert session.scalar(select(func.count()).select_from(Alert)) == 0

    # Telegram down, no backup: stored as failed, retried next time.
    down = FakeChannel(fail=True)
    failed = run_alerts(session, day, settings=settings, channels=[down], now=NOW)
    assert len(failed.failed) == len(signals) + 1 and not failed.sent

    telegram = FakeChannel()
    outcome = run_alerts(session, day, settings=settings, channels=[telegram], now=NOW)
    assert len(outcome.sent) == len(signals) + 1
    subjects = [s for s, _ in telegram.sent]
    assert subjects[-1] == f"Jeron daily summary {day}"
    first = signals[0]
    text = next(t for _, t in telegram.sent if t.startswith(f"NEW SIGNAL: {first.ticker}"))
    assert f"journal?signal={first.signal_id}" in text
    summary = telegram.sent[-1][1]
    assert f"New signals ({len(signals)}):" in summary
    alert = session.scalar(select(Alert).where(Alert.key == f"signal:{first.signal_id}"))
    assert alert.status == "sent" and alert.attempts == 2 and alert.channel == "telegram"

    # A re-run sends nothing twice.
    again = run_alerts(session, day, settings=settings, channels=[telegram], now=NOW)
    assert not again.sent and again.already_sent == len(signals) + 1
    assert send_test(session, settings=settings, channels=[telegram], now=NOW).status == "sent"

    # The journal: the signal is pending until I decide; then fills and stats.
    client = TestClient(app)
    view = client.get("/journal", params={"pending_days": 3650}).json()
    assert str(first.signal_id) in {p["signal_id"] for p in view["pending"]}
    stop = Decimal(str(first.payload["stop"]["price"]))
    low = Decimal(str(first.payload["entry_zone"]["low"]))
    entry = client.put(
        f"/journal/signal/{first.signal_id}",
        json={"decision": "taken", "reason": "as planned", "followed_plan": True},
    ).json()
    assert entry["decision"] == "taken" and Decimal(entry["stop"]) == stop
    assert entry["position"]["status"] == "no fills"
    buy = {"trade_date": str(day), "side": "buy", "shares": 10, "price": str(low), "charges": "5"}
    entry = client.post(f"/journal/{entry['id']}/fills", json=buy).json()
    assert entry["position"]["status"] == "open" and entry["position"]["held"] == 10
    too_many = buy | {"side": "sell", "shares": 11}
    assert client.post(f"/journal/{entry['id']}/fills", json=too_many).status_code == 422
    exit_price = low + 2 * (low - stop)
    sell = buy | {"side": "sell", "price": str(exit_price), "charges": "5"}
    entry = client.post(f"/journal/{entry['id']}/fills", json=sell).json()
    position = entry["position"]
    assert position["status"] == "closed"
    expected_r = (2 * (low - stop) * 10 - 10) / ((low - stop) * 10)
    assert abs(Decimal(position["r_multiple"]) - expected_r) < Decimal("0.0001")
    # Deleting the buy while the sell exists is refused.
    buy_id = entry["fills"][0]["id"]
    assert client.delete(f"/journal/fills/{buy_id}").status_code == 422

    view = client.get("/journal", params={"pending_days": 3650}).json()
    (stats,) = [s for s in view["stats"] if s["strategy_key"] == "score-swing"]
    assert stats["taken"] == 1 and stats["closed"] == 1 and stats["followed"] == 1
    assert stats["pending"] == stats["signals"] - 1
    assert str(first.signal_id) not in {p["signal_id"] for p in view["pending"]}
    one = client.get(f"/journal/signal/{first.signal_id}").json()
    assert one["entry"]["id"] == entry["id"] and one["payload"]["ticker"] == first.ticker

    manual = client.post("/journal", json={"ticker": "stk1", "stop": "90"}).json()
    assert manual["ticker"] == "STK1" and manual["signal"] is None
    assert (
        client.put(
            "/journal/signal/00000000-0000-0000-0000-000000000000", json={"decision": "taken"}
        ).status_code
        == 404
    )

    board = client.get("/dashboard").json()
    assert board["as_of"] == str(END)
    assert board["accounts"][0]["stage"] == "paper"
    assert board["alerts"]["telegram"] is False
    assert board["last_summary"]["status"] == "sent"
    stock = client.get(f"/stocks/{first.ticker}", params={"sessions": 60}).json()
    assert len(stock["candles"]) == 60
    assert any(s["signal"]["signal_id"] == str(first.signal_id) for s in stock["signals"])
    assert stock["journal"][0]["id"] == entry["id"]  # (the test scans store no scores)
    assert client.get("/stocks/NOPE").status_code == 404
    log = client.get("/alerts").json()
    assert log[0]["kind"] == "test"


def test_research_only_signals_are_only_in_the_summary(session):
    day = _signal_day(session, live=False)
    count = session.scalar(
        select(func.count())
        .select_from(SignalRecord)
        .where(SignalRecord.signal_date == day, SignalRecord.late.is_(False))
    )
    telegram = FakeChannel()
    outcome = run_alerts(session, day, settings=Settings(), channels=[telegram], now=NOW)
    assert outcome.sent == [f"digest:{day}"]
    (summary,) = [t for _, t in telegram.sent]
    assert "New signals: none (no strategy has passed the backtest bar yet)" in summary
    assert f"Research only, not trades ({count}):" in summary

    # With the setting on they go out one by one, marked.
    outcome = run_alerts(
        session,
        day,
        settings=Settings(alert_research_signals=True),
        channels=[telegram],
        now=NOW,
    )
    assert len(outcome.sent) == count
    assert all(t.startswith("RESEARCH ONLY") for _, t in telegram.sent[1:])


def test_dashboard_and_alerts_before_any_data(empty_session):
    client = TestClient(app)
    board = client.get("/dashboard").json()
    assert board["as_of"] is None and board["signals"] == [] and board["accounts"] == []
    assert client.get("/journal").json() == {"entries": [], "pending": [], "stats": []}
    outcome = run_alerts(empty_session, settings=Settings(), channels=[FakeChannel()])
    assert outcome.status == "no_scan"


def test_stock_search_by_symbol_or_name(empty_session):
    for symbol, name in [
        ("TATASTEEL", "Tata Steel Limited"),
        ("TATAPOWER", "Tata Power Company Limited"),
        ("TATASTLBSL", None),
        ("M&M", "Mahindra & Mahindra Limited"),
        ("INFY", "Infosys Limited"),
        ("SAIL", "Steel Authority of India Limited"),
    ]:
        empty_session.add(Instrument(exchange=Exchange.NSE, symbol=symbol, name=name))
    empty_session.commit()
    client = TestClient(app)

    def search(q):
        return [m["symbol"] for m in client.get("/stocks/search", params={"q": q}).json()]

    assert search("tata steel") == ["TATASTEEL"]
    assert search("tata st") == ["TATASTEEL", "TATASTLBSL"]
    assert search("TATA")[:2] == ["TATAPOWER", "TATASTEEL"]
    assert search("steel") == ["SAIL", "TATASTEEL"]  # name words, then anywhere
    assert search("infos") == ["INFY"]
    assert search("m&m") == ["M&M"]
    assert search("100%") == [] and search("_") == []
    first = client.get("/stocks/search", params={"q": "tata steel"}).json()[0]
    assert first == {"symbol": "TATASTEEL", "name": "Tata Steel Limited", "series": "EQ"}
