"""Trade plans, the watchlist and the ranked stock list on a real Postgres, through the
API (decision 0010)."""

from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.alerts.job import run_alerts
from app.config import Settings
from app.main import app
from app.models import Alert, ScanResult, SignalRecord, TradePlan
from app.plan.calc import CHECKLIST_KEYS
from app.signals.build import IST
from tests.conftest import requires_db
from tests.test_alerts_db import FakeChannel, _signal_day
from tests.test_alerts_db import empty_session as empty_session  # noqa: F401 - the fixture
from tests.test_backtest_db import session as session  # noqa: F401 - the fixture
from tests.test_market_db import DAYS, _adjusted, _seed

pytestmark = requires_db

NOW = datetime(2026, 1, 1, 19, 0, tzinfo=IST)
LAST = Decimal(f"{_adjusted('UP')[-1]:.2f}")


def _seeded(s) -> TestClient:
    _seed(s)
    for symbol in ("UP", "DOWN", "SPLITCO"):
        row = s.scalar(select(ScanResult).where(ScanResult.symbol == symbol))
        assert row is not None
        s.execute(
            update(ScanResult)
            .where(ScanResult.symbol == symbol)
            .values(
                indicators=row.indicators
                | {"atr14": 3.0, "avg_volume20": 1e6, "rs_6m": 0.1, "below_52w_high_pct": 1.5}
            )
        )
    s.commit()
    return TestClient(app)


def _body(**kw):
    return {
        "ticker": "UP",
        "tier": "swing",
        "entry": str(LAST),
        "stop": str(LAST - 7),
        "reason": "breakout",
        "checklist": list(CHECKLIST_KEYS),
    } | kw


def test_plan_view_and_save(empty_session):
    s = empty_session
    client = _seeded(s)
    assert client.get("/plan/NOPE").status_code == 404

    view = client.get("/plan/UP").json()
    assert view["stock"]["last_close"] == f"{LAST:.4f}" and view["stock"]["in_scan"]
    assert Decimal(view["defaults"]["entry"]) == LAST
    assert Decimal(view["defaults"]["stop"]) == LAST - 6  # 2 x ATR (no swing low)
    assert view["mood"]["mode"] == "attack" and view["events"]["blackout"] is None
    plan = view["plan"]
    # 1% of 10,00,000 / 6 = 1,666 shares; 20% of capital: floor(2,00,000 / 181.9) = 1,099.
    assert plan["shares"] == int(200_000 // LAST) and plan["sized_by"] == "20% of capital"
    assert plan["ok"] is True and Decimal(plan["target2"]) == LAST + 18
    assert len(view["checklist"]) == 5 and view["saved"] == []

    sized = client.get("/plan/UP", params={"entry": "180", "stop": "179"}).json()["plan"]
    assert sized["ok"] is False
    assert any("1 x ATR" in b for b in sized["blockers"])

    # Blocked: an unticked checklist, a stop too tight.
    r = client.post("/plans", json=_body(checklist=["mood"]))
    assert r.status_code == 422 and "Tick every checklist item" in r.json()["detail"]
    r = client.post("/plans", json=_body(stop=str(LAST - 1)))
    assert r.status_code == 422 and "ATR" in r.json()["detail"]
    assert s.scalar(select(TradePlan)) is None

    first = client.post("/plans", json=_body()).json()
    assert first["shares"] == plan["shares"] and first["supersedes_id"] is None
    assert first["mood"] == "attack" and first["checklist"] == list(CHECKLIST_KEYS)
    assert first["details"]["sized_by"] == "20% of capital"
    second = client.post("/plans", json=_body(stop=str(LAST - 8), reason="wider")).json()
    assert second["id"] != first["id"] and second["supersedes_id"] == first["id"]
    # The first plan is unchanged and can't be changed.
    again = client.get(f"/plans/{first['id']}").json()
    assert again == first
    row = s.get(TradePlan, first["id"])
    assert row is not None
    row.reason = "edited"
    with pytest.raises(ValueError, match="never changed"):
        s.commit()
    s.rollback()
    assert [p["id"] for p in client.get("/plans", params={"ticker": "up"}).json()] == [
        second["id"],
        first["id"],
    ]
    assert [p["id"] for p in client.get("/plan/UP").json()["saved"]] == [second["id"], first["id"]]

    # The journal entry points at the plan; a plan for another stock is refused.
    entry = client.post(
        "/journal", json={"ticker": "UP", "stop": str(LAST - 8), "plan_id": second["id"]}
    ).json()
    assert entry["plan_id"] == second["id"]
    r = client.post("/journal", json={"ticker": "DOWN", "plan_id": second["id"]})
    assert r.status_code == 422 and "is for UP" in r.json()["detail"]


def test_plan_from_a_signal(session):
    day = _signal_day(session, live=False)
    record = session.scalars(select(SignalRecord).where(SignalRecord.signal_date == day)).first()
    assert record is not None
    client = TestClient(app)
    view = client.get(f"/plan/{record.ticker}", params={"signal_id": str(record.signal_id)})
    assert view.status_code == 200
    v = view.json()
    p = record.payload
    assert v["signal"]["signal_id"] == str(record.signal_id)
    assert Decimal(v["defaults"]["entry"]) == Decimal(str(p["entry_zone"]["high"]))
    assert Decimal(v["defaults"]["stop"]) == Decimal(str(p["stop"]["price"]))
    assert v["defaults"]["reason"] == p["setup_name"]
    other = "ZZZ" if record.ticker != "ZZZ" else "YYY"
    r = client.get(f"/plan/{other}", params={"signal_id": str(record.signal_id)})
    assert r.status_code in (404, 422)


def test_watchlist_alerts_once(empty_session):
    s = empty_session
    client = _seeded(s)
    assert client.get("/watchlist").json() == {"day": None, "items": [], "hits": 0}
    r = client.post("/watchlist", json={"ticker": "NOPE"})
    assert r.status_code == 422 and "Unknown stock" in r.json()["detail"]
    r = client.post("/watchlist", json={"ticker": "UP", "alert_price": "100"})
    assert r.status_code == 422 and "above/below" in r.json()["detail"]

    # UP's last high is 1% above its close; DOWN is far from its alert.
    above = (LAST * Decimal("1.005")).quantize(Decimal("0.01"))
    client.post(
        "/watchlist",
        json={
            "ticker": "up",
            "alert_price": str(above),
            "alert_direction": "above",
            "note": "base",
        },
    )
    w = client.post(
        "/watchlist", json={"ticker": "DOWN", "alert_price": "1", "alert_direction": "below"}
    ).json()
    assert [i["ticker"] for i in w["items"]] == ["DOWN", "UP"] and w["hits"] == 1
    up = w["items"][1]
    assert up["hit"] is True and up["note"] == "base" and up["alerted_on"] is None
    assert Decimal(up["pct_to_alert"]) == Decimal("0.50") and up["score"] == "50.0"
    assert Decimal(up["below_52w_high_pct"]) == Decimal("1.50")
    assert Decimal(up["change_pct"]) == Decimal("0.20")
    assert w["day"] == str(DAYS[-1])

    settings = Settings(web_url="http://jeron.local")
    telegram = FakeChannel()
    run_alerts(s, DAYS[-1], settings=settings, channels=[telegram], now=NOW)
    watch = [t for subject, t in telegram.sent if subject.startswith("Jeron watchlist")]
    assert len(watch) == 1 and "WATCHLIST: UP reached" in watch[0] and "Note: base" in watch[0]
    assert "http://jeron.local/plan/UP" in watch[0]
    # A re-run (or the next day still above) never sends it again.
    run_alerts(s, DAYS[-1], settings=settings, channels=[telegram], now=NOW)
    assert sum(1 for subject, _ in telegram.sent if subject.startswith("Jeron watchlist")) == 1
    alerts = s.scalars(select(Alert).where(Alert.kind == "watch")).all()
    assert len(alerts) == 1 and alerts[0].status == "sent"
    assert client.get("/watchlist").json()["items"][1]["alerted_on"] == str(DAYS[-1])

    # A new alert price arms it again.
    higher = (LAST * Decimal("1.008")).quantize(Decimal("0.01"))
    client.post(
        "/watchlist", json={"ticker": "UP", "alert_price": str(higher), "alert_direction": "above"}
    )
    run_alerts(s, DAYS[-1], settings=settings, channels=[telegram], now=NOW)
    assert sum(1 for subject, _ in telegram.sent if subject.startswith("Jeron watchlist")) == 2

    assert client.delete("/watchlist/UP").json()["items"][0]["ticker"] == "DOWN"
    assert client.delete("/watchlist/UP").status_code == 404


def test_ranked_stocks(empty_session):
    client = TestClient(app)
    assert client.get("/stocks/ranked").json()["total"] == 0
    _seeded(empty_session)
    client.post("/watchlist", json={"ticker": "DOWN"})
    r = client.get("/stocks/ranked").json()
    assert r["trade_date"] == str(DAYS[-1]) and r["total"] == 3
    assert [i["symbol"] for i in r["items"]] == ["UP", "DOWN", "SPLITCO"]
    it = client.get("/stocks/ranked", params={"sector": "IT", "sort": "return"}).json()
    assert it["total"] == 2 and {i["sector"] for i in it["items"]} == {"IT"}
    page = client.get("/stocks/ranked", params={"offset": 1, "limit": 1}).json()
    assert [i["symbol"] for i in page["items"]] == ["DOWN"] and page["items"][0]["watched"]
    by_return = client.get("/stocks/ranked", params={"sort": "return"}).json()["items"]
    assert by_return[-1]["symbol"] == "DOWN"
    # /stocks/{symbol} still works next to /stocks/ranked.
    assert client.get("/stocks/UP").status_code == 200
