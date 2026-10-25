"""The autopilot on a real Postgres: setup steps in order (history, first daily run,
announcements from stored files, news, backtests, paper), the Setup page, uploads, and
news on the stock page with or without the news brain."""

import os
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import autopilot
from app.backtest.strategies import COMBINED, STRATEGIES
from app.config import get_settings
from app.data import store
from app.data.news import Announcement
from app.data.pipeline import ANNOUNCEMENTS_SOURCE
from app.db import get_engine
from app.exits.job import backup_note
from app.main import app
from app.models import BacktestRun, JournalEntry, ScanRun
from app.scan.score import SCORE_VERSION
from app.signals.build import IST
from tests.conftest import requires_db
from tests.test_alerts_db import empty_session as empty_session  # noqa: F401 - the fixture
from tests.test_backtest_db import _bar

pytestmark = requires_db
TODAY = date(2026, 10, 16)


@pytest.fixture
def session(empty_session, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("JERON_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JERON_IMPORTS_DIR", str(tmp_path / "imports"))
    for key in ("ANTHROPIC", "DEEPSEEK", "OLLAMA"):
        monkeypatch.setenv(f"JERON_{key}_API_KEY", "")
    get_settings.cache_clear()
    yield empty_session


def _run(session: Session, ran: list[list[str]], news_on: bool = False) -> str | None:
    def run(args, log_file):
        ran.append(list(args))
        return 0

    return autopilot.run_market_step(lambda: Session(get_engine()), run, today=TODAY)


def _save_run(session: Session, version: str, key: str) -> None:
    session.add(
        BacktestRun(
            strategy_key=key,
            strategy_version=version,
            strategy_name=key,
            tier="swing",
            data_start=TODAY,
            data_end=TODAY,
            oos_start=TODAY,
            holdout_start=TODAY,
            fingerprint="x",
        )
    )


def test_setup_steps_run_in_order_and_once(session):
    ran: list[list[str]] = []
    assert _run(session, ran) == "backfill"

    store.save_bars(session, store.NSE_BARS, [_bar("AAA", date(2025, 3, 3), 100)])
    session.commit()
    assert _run(session, ran) == "daily"

    session.add(ScanRun(trade_date=date(2025, 3, 3), score_version=SCORE_VERSION, status="ok"))
    for day in (date(2025, 3, 3), date(2025, 3, 4), date(2025, 3, 5)):
        store.record_source_file(session, store.NSE_PR, day, "ok")
    store.record_source_file(session, ANNOUNCEMENTS_SOURCE, date(2025, 3, 4), "ok")
    session.commit()
    assert _run(session, ran) == "events"
    assert ran[-1] == ["events", "--start", "2025-03-03", "--end", "2025-03-05"]

    # Read once: days whose bundle has no announcements file aren't read again.
    assert _run(session, ran) == "backtest"
    every = [*STRATEGIES, *COMBINED]
    assert [a for a in ran[-1] if a != "--strategy"] == ["backtest", *every]

    # Nothing new to test until results or board meetings arrive; then paper once.
    assert _run(session, ran) == "paper"
    assert _run(session, ran) is None

    for key, s in STRATEGIES.items():
        _save_run(session, s.version, key)
    for key, c in COMBINED.items():
        _save_run(session, c.version, key)
    session.commit()
    autopilot._update(results_changed=True)
    assert _run(session, ran) == "backtest"
    assert ran[-1] == ["backtest", "--strategy", "quality-trend"]
    state = autopilot.load_state()
    assert state["last"]["step"] == "backtest" and "now" not in state


def test_news_backlog_runs_once_a_day_when_a_key_is_set(session, monkeypatch):
    monkeypatch.setenv("JERON_NEWS_PROVIDER", "ollama")
    monkeypatch.setenv("JERON_OLLAMA_API_KEY", "test-key")
    get_settings.cache_clear()
    store.save_bars(session, store.NSE_BARS, [_bar("AAA", date(2025, 3, 3), 100)])
    session.add(ScanRun(trade_date=date(2025, 3, 3), score_version=SCORE_VERSION, status="ok"))
    session.commit()
    ran: list[list[str]] = []
    assert _run(session, ran) == "news"
    assert ran[-1] == ["news-label", "--start", str(TODAY - timedelta(days=30))]
    assert _run(session, ran) == "backtest"


def test_the_market_lane_waits_for_a_running_job(session):
    with autopilot.market_lock:
        assert _run(session, []) is None


def test_setup_page_uploads_and_news(session):
    client = TestClient(app)
    view = client.get("/setup").json()
    steps = {s["key"]: s for s in view["steps"]}
    assert steps["prices"]["state"] == "waiting"
    assert steps["news"]["state"] == "you" and ".env" in steps["news"]["todo"][0]
    assert steps["alerts"]["state"] == "you"
    calendar = steps["calendar"]
    assert calendar["state"] in ("done", "you")  # "you" in November and December
    assert calendar["state"] == "done" or "holiday calendar" in calendar["detail"]
    assert len(view["strategies"]) == len(STRATEGIES) + len(COMBINED)

    put = client.put("/imports/CF-FR-equities.csv", content=b"COMPANY NAME,** XBRL\n")
    assert put.status_code == 200 and put.json()["imports"]["pending"] == ["CF-FR-equities.csv"]
    assert client.put("/imports/../../etc.csv", content=b"x").status_code in (200, 404)
    assert client.put("/imports/run.sh", content=b"x").status_code == 422
    assert client.put("/imports/empty.csv", content=b"").status_code == 422
    steps = {s["key"]: s for s in client.get("/setup").json()["steps"]}
    assert steps["results"]["state"] == "working"

    today = datetime.now(IST).date()
    items = [
        Announcement(
            "AAA", today, "Bagging/Receiving of orders/contracts",
            "Aaa Ltd has informed the Exchange about an ORDER worth Rs 900 crore from NHAI",
        ),
        Announcement("AAA", today, "Trading Window", "Aaa Ltd: closure of trading window"),
    ]  # fmt: skip
    store.save_announcements(session, items, "test")
    session.commit()
    news = client.get("/stocks/aaa/news").json()
    assert {i["event_type"] for i in news["items"]} == {"order_win", "other"}
    assert all(i["sentiment"] is None for i in news["items"])
    assert "without good or bad labels" in news["note"]
    latest = client.get("/news/latest").json()
    assert [i["subject"] for i in latest["items"]] == ["Bagging/Receiving of orders/contracts"]


def test_setup_page_shows_backups(session, tmp_path, monkeypatch):
    folder = tmp_path / "backups"
    folder.mkdir()
    monkeypatch.setenv("JERON_BACKUPS_MOUNT", str(folder))
    monkeypatch.setenv("JERON_BACKUP_DIR", "D:/Google Drive/jeron-backups")
    get_settings.cache_clear()
    client = TestClient(app)
    steps = {s["key"]: s for s in client.get("/setup").json()["steps"]}
    assert steps["backups"]["state"] == "waiting"
    # The pre-open check says "no backup yet" only once the journal has something to lose.
    assert backup_note(session, get_settings()) is None
    session.add(JournalEntry(ticker="AAA", decision="taken"))
    session.commit()
    assert "No backup has been written" in (backup_note(session, get_settings()) or "")
    (folder / "jeron-2026-10-25.dump").write_bytes(b"x")
    now = datetime.now(UTC)
    (folder / "restore-check.txt").write_text(
        f"ok\tjeron-2026-10-25.dump\t{now:%Y-%m-%dT%H:%M:%S%z}\njournal entries 3\n"
    )
    steps = {s["key"]: s for s in client.get("/setup").json()["steps"]}
    assert steps["backups"]["state"] == "done"
    assert "Restore test passed" in steps["backups"]["detail"]
    old = (now - timedelta(days=4)).timestamp()
    os.utime(folder / "jeron-2026-10-25.dump", (old, old))
    steps = {s["key"]: s for s in client.get("/setup").json()["steps"]}
    assert steps["backups"]["state"] == "you" and "4 days old" in steps["backups"]["todo"][0]

    # Not mounted (a backend run outside Docker Compose): no step.
    monkeypatch.setenv("JERON_BACKUPS_MOUNT", "")
    get_settings.cache_clear()
    assert "backups" not in {s["key"] for s in client.get("/setup").json()["steps"]}
