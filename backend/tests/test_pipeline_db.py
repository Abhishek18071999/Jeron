"""The data pipeline and API end to end, on a real Postgres with fake sources."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from alembic import command
from app.calendar.nse import TradingCalendar
from app.config import get_settings
from app.data import pipeline, store
from app.data.provider import CorporateActionRecord
from app.data.yahoo import YahooHistory
from app.db import get_engine
from app.enums import CorporateActionType, QualityStatus
from app.main import app
from tests.conftest import TEST_DATABASE_URL, requires_db
from tests.helpers import bar, pr_zip, udiff_row, udiff_zip

BACKEND_DIR = Path(__file__).resolve().parents[1]
DAYS = [
    date(2024, 10, 21),
    date(2024, 10, 22),
    date(2024, 10, 24),
    date(2024, 10, 25),
    date(2024, 10, 28),
    date(2024, 10, 29),
]
HOLIDAY = date(2024, 10, 23)  # pretend NSE was shut
TODAY = date(2024, 11, 10)

# RELIANCE: raw closes with the 1:1 bonus on 10-28 (prices halve).
RELIANCE = {
    DAYS[0]: (2740, 2750, 2710, 2738.40),
    DAYS[1]: (2738, 2752, 2680, 2686.70),
    DAYS[2]: (2670, 2690, 2646, 2679.60),
    DAYS[3]: (2687, 2688.70, 2644, 2655.70),
    DAYS[4]: (1337, 1353, 1322.10, 1334.35),
    DAYS[5]: (1328.10, 1343.20, 1320.30, 1340.00),
}
# JUMP: an illiquid stock that rises 30% on the last day with no corporate action.
JUMP = {d: (100 + i, 102 + i, 99 + i, 100 + i) for i, d in enumerate(DAYS[:-1])}
JUMP[DAYS[5]] = (130, 135, 125, 134.0)


def _prev(prices, day):
    earlier = [d for d in DAYS if d < day and d in prices]
    return prices[earlier[-1]][3] if earlier else prices[day][3]


class FakeArchive:
    settle_days = 3

    def __init__(self):
        self.calls = 0

    def bhavcopy(self, day, today):
        self.calls += 1
        if day not in DAYS:
            return None
        rows = [
            udiff_row(day, "RELIANCE", *RELIANCE[day], _prev(RELIANCE, day), 1_000_000),
            udiff_row(day, "JUMP", *JUMP[day], _prev(JUMP, day), 10),
        ]
        return udiff_zip(day, rows)

    def pr_bundle(self, day, today):
        if day not in DAYS:
            return None
        return pr_zip(
            day,
            ["EQ,RELIANCE,Reliance Industries Ltd,28/10/2024, , ,28/10/2024, , ,BONUS 1:1"],
        )


class FakeYahoo:
    name = "yahoo"

    def history(self, symbol, start, end):
        assert symbol == "RELIANCE"
        bars = []
        for day, (o, h, lo, c) in RELIANCE.items():
            if start <= day <= end:
                if day == DAYS[2]:
                    c = c * 1.01  # one bad close in the second source
                bars.append(bar(symbol, day, o, h, lo, round(c, 2)))
        split = CorporateActionRecord(
            symbol,
            DAYS[4],
            CorporateActionType.SPLIT,
            Decimal(2),
            Decimal(1),
            raw_text="split 2:1",
        )
        return YahooHistory(symbol, bars, [split])


@pytest.fixture
def session(monkeypatch):
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


def run_all(session):
    calendar = TradingCalendar.default()
    archive = FakeArchive()
    results = pipeline.ingest_range(session, archive, calendar, DAYS[0], DAYS[-1], TODAY)
    unknown = pipeline.crosscheck_range(session, FakeYahoo(), DAYS[0], DAYS[-1])
    reports = pipeline.quality_range(session, calendar, DAYS[0], DAYS[-1])
    return archive, results, unknown, reports


@requires_db
def test_ingest_crosscheck_and_quality(session):
    archive, results, unknown, reports = run_all(session)
    statuses = {r.day: r.status for r in results}
    assert statuses[HOLIDAY] == "not_published"
    assert [d for d, s in statuses.items() if s == "ok"] == DAYS
    assert unknown == []

    # Re-running skips days already stored.
    calls = archive.calls
    pipeline.ingest_range(session, archive, TradingCalendar.default(), DAYS[0], DAYS[-1], TODAY)
    assert archive.calls == calls

    assert store.liquid_symbols(session, DAYS[-1]) == ["RELIANCE"]
    by_day = {r.trade_date: r for r in reports}
    assert set(by_day) == set(DAYS)
    assert by_day[DAYS[2]].status == QualityStatus.FAIL  # 1 of 1 closes disagrees
    assert by_day[DAYS[4]].status == QualityStatus.PASS  # bonus explained, sources agree
    last = {c.name: c for c in by_day[DAYS[5]].checks}
    assert last["big_moves"].status == QualityStatus.WARN
    assert [i["symbol"] for i in last["big_moves"].items] == ["JUMP"]


@requires_db
def test_api(session):
    run_all(session)
    client = TestClient(app)

    status = client.get("/data/status").json()
    coverage = {c["source"]: c for c in status["coverage"]}
    assert coverage["nse_bhavcopy"]["days"] == len(DAYS)
    assert status["latest_quality"]["trade_date"] == "2024-10-29"
    assert status["latest_quality"]["status"] == "warn"
    assert status["scan_allowed"] is True

    assert len(client.get("/data/quality").json()) == len(DAYS)
    assert client.get("/data/quality/2024-10-24").json()["status"] == "fail"
    assert client.get("/data/quality/2024-10-23").status_code == 404
    assert client.get("/data/symbols", params={"q": "rel"}).json() == [
        {"symbol": "RELIANCE", "series": "EQ"}
    ]

    spot = client.get(
        "/data/spot-check", params={"symbol": "reliance", "date": "2024-10-25", "window": 1}
    ).json()
    rows = {r["trade_date"]: r for r in spot["rows"]}
    assert list(rows) == ["2024-10-24", "2024-10-25", "2024-10-28"]
    friday = rows["2024-10-25"]
    assert Decimal(friday["raw"]["close"]) == Decimal("2655.70")
    assert Decimal(friday["adjusted"]["close"]) == Decimal("1327.85")
    assert Decimal(friday["factor"]) == Decimal("0.5")
    assert Decimal(friday["second_source_close"]) == Decimal("2655.70")
    assert rows["2024-10-24"]["close_mismatch"] is True
    (bonus,) = [a for a in spot["adjustments"] if a["source"] == "nse"]
    assert bonus["applied"] is True
    assert bonus["price_confirms"] is True
    assert bonus["confirmed_by_second_source"] is True

    holiday = client.get("/data/spot-check", params={"symbol": "RELIANCE", "date": "2024-10-23"})
    assert "nearest trading day" in holiday.json()["notes"][0]
    assert (
        client.get("/data/spot-check", params={"symbol": "NOPE", "date": "2024-10-23"}).status_code
        == 404
    )

    sample = client.get("/data/spot-check/sample", params={"n": 4, "seed": 1}).json()
    assert len(sample) == 4
    assert any(p["reason"].startswith("ex-date") for p in sample)


@requires_db
def test_daily_update(session):
    report = pipeline.daily_update(
        session,
        FakeArchive(),
        FakeYahoo(),
        TradingCalendar.default(),
        DAYS[-1] + timedelta(days=1),
    )
    assert report is not None
    assert report.trade_date == DAYS[-1]
