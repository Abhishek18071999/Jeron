"""Quarterly results on a real Postgres: loading NSE's filings (a fake download of real
XBRL samples), point-in-time reads and the stock page's endpoint."""

from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.data import store
from app.data.fundamentals import IST, read_results_csv
from app.fundamentals.job import import_results, quarters_known, stock_fundamentals
from app.main import app
from app.models import FinancialResult, Instrument
from tests.conftest import requires_db
from tests.test_alerts_db import empty_session as empty_session  # noqa: F401 - the fixture
from tests.test_backtest_db import _bar

pytestmark = requires_db

FIXTURES = Path(__file__).parent / "fixtures"
FILES = {
    "INDAS_117297_1348248_16012025081520.xml": "xbrl_reliance_2024q3.xml",
    "BANKING_118874_1373047_06022025045242.xml": "xbrl_sbi_2024q3.xml",
}


class FakeArchive:
    def __init__(self):
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        name = url.rsplit("/", 1)[-1]
        if name in FILES:
            return (FIXTURES / FILES[name]).read_bytes()
        return b"<html>Access Denied</html>"


def _setup(s, names):
    for symbol, name in names.items():
        store.save_bars(s, store.NSE_BARS, [_bar(symbol, date(2025, 1, 15), 1200)])
        s.execute(update(Instrument).where(Instrument.symbol == symbol).values(name=name))
    s.commit()


def _refs():
    return read_results_csv((FIXTURES / "nse_financial_results.csv").read_text("utf-8-sig"))


def test_loads_consolidated_filings_of_known_liquid_stocks(empty_session):
    s = empty_session
    _setup(s, {"RELIANCE": "Reliance Industries Limited", "SBIN": "State Bank of India"})
    fetch = FakeArchive()
    run = import_results(s, _refs(), fetch)
    assert run.stored == 2 and not run.failed
    names = [u.rsplit("/", 1)[-1] for u in fetch.urls]
    assert set(FILES) <= set(names)
    # V.S.T Tillers is no stock here: its newest filing is read once for its symbol.
    assert len(names) == 3
    assert {"Videocon Industries Limited", "V.S.T Tillers Tractors Limited"} <= run.unmatched
    rows = {r.symbol: r for r in s.scalars(select(FinancialResult))}
    assert rows["RELIANCE"].consolidated and rows["SBIN"].standard == "Non-Ind-AS"
    assert rows["RELIANCE"].facts["RevenueFromOperations"] == "2438650000000.00"
    # Run again: nothing downloaded twice, nothing stored twice.
    again = import_results(s, _refs(), fetch)
    assert again.already == 2 and again.stored == 0
    assert len(fetch.urls) == 4  # only the symbol lookup again (the CLI caches files)
    assert s.scalar(select(func.count()).select_from(FinancialResult)) == 2


def test_point_in_time(empty_session):
    s = empty_session
    _setup(s, {"RELIANCE": "Reliance Industries Limited"})
    import_results(s, _refs(), FakeArchive())
    published = datetime(2025, 1, 16, 20, 15, 46, tzinfo=IST)
    assert quarters_known(s, ["RELIANCE"], published) == {}
    known = quarters_known(s, ["RELIANCE"], published + timedelta(seconds=1))
    assert known["RELIANCE"][0].net_profit == 185400000000.0
    # The stock page on the day after: one quarter, too few for a score, said so.
    found = stock_fundamentals(s, "RELIANCE", date(2025, 1, 17))
    assert found and found.score.score is None and found.price == 1200.0
    assert stock_fundamentals(s, "RELIANCE", date(2025, 1, 15)) is None


def test_api(empty_session):
    s = empty_session
    _setup(s, {"RELIANCE": "Reliance Industries Limited"})
    import_results(s, _refs(), FakeArchive())
    client = TestClient(app)
    body = client.get("/stocks/reliance/fundamentals").json()
    assert body["symbol"] == "RELIANCE" and body["version"] == "fund-v1"
    assert body["quarters"][0]["period_end"] == "2024-12-31"
    assert body["quarters"][0]["filed"] == "2025-01-16"
    assert client.get("/stocks/NOPE/fundamentals").status_code == 404
