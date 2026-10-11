"""Bulk and block deals and insider trades on a real Postgres: storing, the daily
download, and the stock page's panel."""

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.data import pipeline, store
from app.data.deals import BLOCK_URL, BULK_URL, read_file
from app.data.http import FetchError
from app.main import app
from tests.conftest import requires_db
from tests.test_alerts_db import empty_session as empty_session  # noqa: F401 - the fixture
from tests.test_deals import INSIDER_CSV

pytestmark = requires_db

FIXTURES = Path(__file__).parent / "fixtures"
DAY = date(2026, 10, 9)


class FakeArchive:
    def __init__(self, files=None, fail=False):
        self.files, self.fail = files or {}, fail

    def current_list(self, url, today):
        if self.fail:
            raise FetchError("HTTP 403")
        return self.files[url]


def _archive():
    return FakeArchive(
        {
            BULK_URL: (FIXTURES / "nse_bulk_2026-10-09.csv").read_bytes(),
            BLOCK_URL: (FIXTURES / "nse_block_empty.csv").read_bytes(),
        }
    )


def test_daily_download_stores_each_deal_once(empty_session):
    s = empty_session
    assert pipeline.collect_deals(s, _archive(), DAY) == 8
    assert pipeline.collect_deals(s, _archive(), DAY) == 0  # never changed or doubled
    assert store.ok_dates(s, store.NSE_DEALS) == [DAY]
    assert len(store.symbol_deals(s, "ACEVECTOR", date(2026, 1, 1))) == 6
    messages = []
    assert pipeline.collect_deals(s, FakeArchive(fail=True), DAY, log=messages.append) is None
    assert "could not be collected" in messages[0]


def test_insider_import_once(empty_session):
    s = empty_session
    _, trades = read_file(INSIDER_CSV.encode(), "insider.csv")
    assert store.save_insider_trades(s, trades, "test") == 3
    assert store.save_insider_trades(s, trades, "test") == 0
    s.commit()
    assert store.symbol_insider_trades(s, "ABC", date(2026, 1, 1)) == sorted(
        trades, key=lambda t: t.disclosed, reverse=True
    )


def test_stock_deals_endpoint(empty_session):
    s = empty_session
    client = TestClient(app)
    empty = client.get("/stocks/acevector/deals", params={"day": "2026-10-11"}).json()
    assert empty["deal_count"] == 0 and empty["deals_coverage"]["first"] is None

    pipeline.collect_deals(s, _archive(), DAY)
    store.record_source_file(s, store.NSE_BARS, DAY, "ok")
    _, trades = read_file(INSIDER_CSV.encode(), "insider.csv")
    store.save_insider_trades(s, trades, "test")
    s.commit()

    body = client.get("/stocks/acevector/deals", params={"day": "2026-10-11"}).json()
    assert body["symbol"] == "ACEVECTOR" and body["deal_count"] == 6
    # All three firms bought and sold the same day: none is a buyer or seller.
    assert body["buyers"] == [] and body["sellers"] == []
    assert len(body["day_traders"]) == 3
    assert body["deals_coverage"] == {
        "first": "2026-10-09",
        "last": "2026-10-09",
        "days": 1,
        "sessions": 1,
    }

    abc = client.get("/stocks/ABC/deals", params={"day": "2026-10-11"}).json()
    assert abc["insider_count"] == 3
    assert abc["insider"][0]["person"] == "Staff One"  # newest disclosure first
    assert abc["insider_totals"]["promoter_net"] == "500000.00"
    # A year back from 2027-10-09 the October 2026 trades are out of range.
    later = client.get("/stocks/ABC/deals", params={"day": "2027-10-10"}).json()
    assert later["insider_count"] == 0
