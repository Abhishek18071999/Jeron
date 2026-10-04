"""Zerodha tradebook import: the parser (pure) and the journal import on Postgres. The
sample is made up in Kite Console's format; no real account data."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.data import store
from app.journal.importer import import_tradebook
from app.journal.service import entry_views
from app.journal.tradebook import estimate_charges, parse_tradebook
from app.main import app
from app.models import Instrument, JournalEntry, JournalFill
from tests.conftest import requires_db
from tests.journal_helpers import make_account, make_signal
from tests.test_alerts_db import empty_session as empty_session  # noqa: F401 - the fixture
from tests.test_backtest_db import _bar

HEADER = (
    "symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,"
    "trade_id,order_id,order_execution_time"
)
ROWS = [
    "INFY,INE009A01021,2025-03-03,NSE,EQ,EQ,buy,false,10.000000,1500.000000,1001,9001,2025-03-03T09:20:01",
    "INFY,INE009A01021,2025-03-03,NSE,EQ,EQ,buy,false,5.000000,1501.000000,1002,9001,2025-03-03T09:20:02",
    "NIFTY25MARFUT,,2025-03-03,NFO,FO,,buy,false,75.000000,22000.000000,2001,9002,2025-03-03T09:30:00",
    "TCS,INE467B01029,2025-03-04,NSE,EQ,EQ,buy,false,3.000000,3500.000000,1003,9003,2025-03-04T10:00:00",
    "INFY,INE009A01021,2025-03-10,NSE,EQ,EQ,sell,false,15.000000,1600.000000,1004,9004,2025-03-10T11:00:00",
    "WIPRO,INE075A01022,2025-03-11,NSE,EQ,EQ,sell,false,20.000000,300.000000,1005,9005,2025-03-11T11:00:00",
    "RELIANCE,INE002A01018,2025-03-12,BSE,EQ,A,buy,false,4.000000,1250.000000,1006,9006,2025-03-12T09:16:00",
]  # fmt: skip
CSV = "\n".join([HEADER, *ROWS]) + "\n"


def test_parse_keeps_equity_and_counts_the_rest():
    book = parse_tradebook("﻿" + CSV)
    assert book.problems == []
    assert book.skipped == {"FO": 1}
    assert [(t.symbol, t.side, t.shares) for t in book.trades][:3] == [
        ("INFY", "buy", 10),
        ("INFY", "buy", 5),
        ("TCS", "buy", 3),
    ]
    first = book.trades[0]
    assert first.price == Decimal("1500") and first.key == "zerodha:NSE:1001"
    assert first.trade_date == date(2025, 3, 3) and first.executed_at is not None


def test_parse_problems():
    assert "missing column" in parse_tradebook("a,b\n1,2\n").problems[0]
    bad = (
        HEADER
        + "\nINFY,,2025-03-03,NSE,EQ,EQ,short,false,1,10,1,1,"
        + "\nINFY,,03-03-2025,NSE,EQ,EQ,buy,false,1.5,10,2,2,\n"
    )
    book = parse_tradebook(bad)
    assert len(book.problems) == 2 and "trade_type" in book.problems[0]
    assert "quantity" in book.problems[1]


def test_charges_are_estimated_with_dp_once_per_stock_and_day():
    book = parse_tradebook(CSV)
    charges = estimate_charges(book.trades)
    buy = charges["zerodha:NSE:1001"]  # 15,000 bought: STT 15, stamp 2.25, exchange, GST
    assert Decimal("17") < buy < Decimal("19")
    sell = charges["zerodha:NSE:1004"]  # 24,000 sold: STT 24 plus DP 15.34
    assert Decimal("39") < sell < Decimal("42")


@requires_db
def test_import_matches_signals_and_open_entries(empty_session):
    s = empty_session
    store.save_bars(
        s, store.NSE_BARS, [_bar(sym, date(2025, 3, 3), 100) for sym in ("INFY", "TCS", "RELIANCE")]
    )
    s.execute(
        Instrument.__table__.update()
        .where(Instrument.symbol == "RELIANCE")
        .values(isin="INE002A01018")
    )
    account = make_account(s)
    infy = make_signal(s, account, "INFY", date(2025, 2, 28), date(2025, 3, 5))
    make_signal(s, account, "TCS", date(2025, 2, 20), date(2025, 2, 25))  # expired

    result = import_tradebook(s, CSV)
    assert result.added == 5 and result.already == 0
    assert result.to_signals == 1 and result.new_entries == 2  # TCS and RELIANCE
    assert result.skipped == {"FO": 1}
    assert len(result.problems) == 1 and "WIPRO" in result.problems[0]

    entry = s.scalar(select(JournalEntry).where(JournalEntry.signal_id == infy))
    assert entry is not None and entry.decision == "taken"
    (view,) = entry_views(s, [entry])
    assert view.position.status == "closed" and view.position.bought == 15
    assert all(f.charges_estimated and f.source == "tradebook" for f in view.fills)
    reliance = s.scalar(select(JournalEntry).where(JournalEntry.ticker == "RELIANCE"))
    assert reliance is not None  # BSE trade found by ISIN

    again = import_tradebook(s, CSV)
    assert again.added == 0 and again.already == 5
    assert len(s.scalars(select(JournalFill)).all()) == 5


@requires_db
def test_import_through_the_api(empty_session):
    client = TestClient(app)
    response = client.post("/journal/import", json={"csv": CSV})
    assert response.status_code == 200
    body = response.json()
    assert body["added"] == 5 and body["new_entries"] == 3
    journal = client.get("/journal").json()
    fills = [f for e in journal["entries"] for f in e["fills"]]
    assert fills and all(f["charges_estimated"] for f in fills)
    assert client.post("/journal/import", json={"csv": ""}).status_code == 422


@pytest.mark.parametrize("text", ["", "\n\n"])
def test_empty_file(text):
    assert parse_tradebook(text).problems
