"""The market mood and the portfolio on a real Postgres, through the API."""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import update

from app import indicators as ind
from app.api.dashboard import _results_ahead
from app.calendar.nse import TradingCalendar
from app.data import store
from app.data.events import BoardMeeting
from app.data.nse_lists import INDIA_VIX, NIFTY_50, NIFTY_500, IndexClose
from app.data.provider import CorporateActionRecord
from app.enums import CorporateActionType
from app.exits.job import is_session, next_session
from app.journal.service import add_fill, manual_entry
from app.main import app
from app.models import Instrument, ScanResult, ScanRun
from app.scan.score import SCORE_VERSION
from tests.backtest_helpers import weekdays
from tests.conftest import requires_db
from tests.test_alerts_db import empty_session as empty_session  # noqa: F401 - the fixture
from tests.test_backtest_db import _bar

pytestmark = requires_db

CAL = TradingCalendar.default()
DAYS = [d for d in weekdays(date(2024, 6, 3), 330) if is_session(CAL, d)][:300]
SPLIT_AT = 200
SECTORS = {"UP": "IT", "DOWN": "Banks", "SPLITCO": "IT"}


def _adjusted(symbol: str) -> list[float]:
    if symbol == "DOWN":
        return [200 * 0.998**i for i in range(len(DAYS))]
    return [100 * 1.002**i for i in range(len(DAYS))]


def _seed(s) -> None:
    for symbol in SECTORS:
        closes = _adjusted(symbol)
        raw = [c * 2 if symbol == "SPLITCO" and i < SPLIT_AT else c for i, c in enumerate(closes)]
        bars = [_bar(symbol, d, c) for d, c in zip(DAYS, raw, strict=True)]
        store.save_bars(s, store.NSE_BARS, bars)
        s.execute(
            update(Instrument).where(Instrument.symbol == symbol).values(sector=SECTORS[symbol])
        )
    store.save_actions(
        s,
        store.NSE_ACTIONS,
        [
            CorporateActionRecord(
                "SPLITCO", DAYS[SPLIT_AT], CorporateActionType.SPLIT, Decimal(2), Decimal(1)
            )
        ],
    )
    for d in DAYS:
        store.record_source_file(s, store.NSE_BARS, d, "ok")
    rising = [1000 * 1.001**i for i in range(len(DAYS))]
    store.save_index_closes(
        s,
        [
            IndexClose(name, d, None, None, None, Decimal(f"{v:.2f}"))
            for name in (NIFTY_500, NIFTY_50)
            for d, v in zip(DAYS, rising, strict=True)
        ]
        + [
            IndexClose(INDIA_VIX, d, None, None, None, Decimal(12 + i % 9))
            for i, d in enumerate(DAYS)
        ],
    )
    run = ScanRun(trade_date=DAYS[-1], score_version=SCORE_VERSION, status="ok", details={})
    s.add(run)
    s.flush()
    ids = store.existing_ids(s, SECTORS)
    for rank, symbol in enumerate(SECTORS, 1):
        closes = _adjusted(symbol)
        s.add(
            ScanResult(
                run_id=run.id,
                instrument_id=ids[symbol],
                symbol=symbol,
                rank=rank,
                score=Decimal("50"),
                close=Decimal(f"{closes[-1]:.2f}"),
                in_nifty500=symbol != "SPLITCO",
                sector=SECTORS[symbol],
                components=[],
                indicators={
                    "close": round(closes[-1], 2),
                    "ema200": ind.ema(closes, 200)[-1],
                    "return_6m": closes[-1] / closes[-127] - 1,
                },
            )
        )
    s.commit()


def test_market_mood(empty_session):
    client = TestClient(app)
    assert client.get("/market/mood").status_code == 404
    _seed(empty_session)
    mood = client.get("/market/mood").json()
    assert mood["day"] == str(DAYS[-1])
    b = mood["breadth"]
    assert (b["stocks"], b["above_ema200"], b["pct_above_ema200"]) == (3, 2, 66.7)
    assert (b["nifty500_stocks"], b["nifty500_pct_above_ema200"]) == (2, 50.0)
    # SPLITCO's raw prices halved on the split, but adjusted it makes a new high.
    assert (b["new_highs"], b["new_lows"]) == (2, 1)
    assert mood["regime"]["risk_off"] is False and mood["regime"]["regime"] == "bull"
    assert mood["mode"] == "attack" and mood["risk_multiplier"] == 1.0
    assert "67% of stocks" in mood["reason"]
    assert [x["sector"] for x in mood["sectors"]] == ["IT", "Banks"]
    assert mood["sectors"][0]["stocks"] == 2
    assert client.get("/market/mood", params={"date": str(DAYS[-2])}).status_code == 404
    assert client.get("/market/mood", params={"date": str(DAYS[-1])}).json()["mode"] == "attack"


def test_portfolio(empty_session):
    client = TestClient(app)
    empty = client.get("/portfolio", params={"day": str(next_session(CAL, DAYS[-1]))}).json()
    assert empty["holdings"] == [] and empty["totals"]["positions"] == 0

    s = empty_session
    _seed(s)
    buy_at = Decimal(f"{_adjusted('UP')[280]:.2f}")
    up = manual_entry(s, "UP", stop=(buy_at * Decimal("0.98")).quantize(Decimal("0.01")))
    add_fill(s, up, DAYS[280], "buy", 100, buy_at)
    down = manual_entry(s, "DOWN")
    add_fill(s, down, DAYS[290], "buy", 10, Decimal("120"))

    p = client.get("/portfolio", params={"day": str(next_session(CAL, DAYS[-1]))}).json()
    assert p["stale"] is False and p["data_as_of"] == str(DAYS[-1])
    by = {h["ticker"]: h for h in p["holdings"]}
    h = by["UP"]
    # +1R reached (stop to breakeven), then T1 at +2R: book half.
    assert h["action"] == "sell half" and h["sector"] == "IT" and h["shares"] == 100
    assert h["sessions_held"] == 19 and h["stop"] == h["avg_entry"] == str(buy_at)
    assert Decimal(h["open_risk"]) == 0
    assert Decimal(h["stop_distance_pct"]) == Decimal("3.73")  # 1.002**19 above the entry
    assert Decimal(h["pnl"]) > 0
    assert by["DOWN"]["problem"] == "no stop set: add one in the journal"
    assert by["DOWN"]["action"] is None and by["DOWN"]["open_risk"] is None
    t = p["totals"]
    assert t["positions"] == 2 and t["without_stop"] == 1
    assert Decimal(t["heat_pct"]) < 1 and Decimal(t["capital"]) == Decimal("1000000")
    assert [x["sector"] for x in t["sectors"]] == ["IT", "Banks"]
    assert any("without a stop" in w for w in t["warnings"])


def test_results_ahead_for_signals(empty_session):
    s = empty_session
    store.save_board_meetings(
        s,
        [
            BoardMeeting("UP", date(2025, 8, 20), "Financial Results", announced=None),
            BoardMeeting("DOWN", date(2025, 12, 1), "Financial Results", announced=None),
        ],
        "test",
    )
    s.commit()
    found = _results_ahead(s, {"UP", "DOWN", "NONE"}, date(2025, 8, 1))
    assert found == {"UP": date(2025, 8, 20)}  # DOWN's is more than 30 days away
    assert _results_ahead(s, set(), date(2025, 8, 1)) == {}
