"""Explain a stock, its LLM wording and compare, on a real Postgres through the API. The
LLM is a fake; the real API is never called."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.api import explain as explain_api
from app.main import app
from app.models import Explanation, Instrument, LlmUsage, SignalRecord
from app.news.claude import Usage
from tests.conftest import requires_db
from tests.test_alerts_db import _signal_day
from tests.test_alerts_db import empty_session as empty_session  # noqa: F401 - the fixture
from tests.test_backtest_db import session as session  # noqa: F401 - the fixture
from tests.test_market_db import DAYS, _seed

pytestmark = requires_db


class FakeWriter:
    def __init__(self, reply: str, name: str = "claude-haiku-4-5") -> None:
        self.reply, self.name, self.calls = reply, name, []

    def write(self, system: str, user: str) -> tuple[str | None, Usage]:
        self.calls.append(user)
        return self.reply, Usage(1, 2000, 300)


def _grounded(brief: dict) -> str:
    score = next(f for f in brief["facts"] if f["label"].startswith("Technical score"))
    text = f"The technical score is {score['value']}; it counts conditions, it is no forecast."
    return f'{{"points": [{{"text": "{text}", "facts": ["{score["id"]}"]}}]}}'


@pytest.fixture
def writer(monkeypatch):
    def use(fake):
        monkeypatch.setattr(explain_api, "make_writer", lambda settings: fake)
        return fake

    return use


def test_explain_and_compare(empty_session):
    _seed(empty_session)
    client = TestClient(app)
    assert client.get("/stocks/NOPE/explain").status_code == 404

    view = client.get("/stocks/up/explain").json()
    b = view["brief"]
    assert b["symbol"] == "UP" and b["as_of"] == str(DAYS[-1])
    assert b["stale"] is True  # the made-up market ends in 2025
    close = b["facts"][0]
    assert close["label"] == "Last close" and close["kind"] == "data"
    assert close["source"].startswith("NSE bhavcopy") and close["as_of"] == str(DAYS[-1])
    score = next(f for f in b["facts"] if f["label"].startswith("Technical score"))
    assert score["value"] == "50.0 / 100" and score["kind"] == "calculated"
    mood = next(f for f in b["facts"] if f["label"] == "Market mood")
    assert mood["value"].startswith("attack")
    assert b["setup"] is None and any("No strategy has signalled" in u for u in b["unknowns"])
    assert view["narration"] is None
    assert view["writer"]["ready"] in (True, False)

    assert score["number"] == 50.0 and b["strategy"] is None

    both = client.get("/stocks/compare", params={"symbols": "UP, splitco,UP"}).json()
    assert [x["symbol"] for x in both["briefs"]] == ["UP", "SPLITCO"]
    assert both["not_found"] == []
    perf = {p["symbol"]: p for p in both["performance"]}
    assert list(perf) == ["UP", "SPLITCO", "Nifty 500"]
    # Adjusted for the split: SPLITCO's raw price halved but its returns match UP's.
    for k, v in perf["UP"]["returns"].items():
        assert abs(perf["SPLITCO"]["returns"][k] - v) < 0.02  # prices are stored to the paisa
    assert perf["UP"]["returns"]["1M"] == round((1.002**21 - 1) * 100, 2)
    assert perf["UP"]["max_drawdown"] == 0.0 and perf["UP"]["sector"] == "IT"
    starts = {p["series"][0]["time"] for p in perf.values()}
    assert len(starts) == 1 and all(p["series"][0]["value"] == 100.0 for p in perf.values())
    assert client.get("/stocks/compare", params={"symbols": "A,B,C,D"}).status_code == 422
    # One that matches nothing is listed, the others are still compared.
    some = client.get("/stocks/compare", params={"symbols": "UP,NOPE"}).json()
    assert [x["symbol"] for x in some["briefs"]] == ["UP"] and some["not_found"] == ["NOPE"]
    # A company name is matched as the search box would; the same stock twice is once.
    empty_session.execute(
        update(Instrument).where(Instrument.symbol == "DOWN").values(name="Down Bank Ltd")
    )
    empty_session.commit()
    named = client.get("/stocks/compare", params={"symbols": "down bank, DOWN"}).json()
    assert [x["symbol"] for x in named["briefs"]] == ["DOWN"] and named["not_found"] == []


def test_narration_is_checked_stored_and_capped(empty_session, writer):
    s = empty_session
    _seed(s)
    client = TestClient(app)
    writer(None)
    r = client.post("/stocks/UP/explain/narrate", json={})
    assert r.status_code == 409 and "No LLM key" in r.json()["detail"]

    brief = client.get("/stocks/UP/explain").json()["brief"]
    good = writer(FakeWriter(_grounded(brief)))
    first = client.post("/stocks/UP/explain/narrate", json={}).json()
    assert first["status"] == "ok" and first["problems"] == []
    assert first["points"][0]["text"].startswith("The technical score is 50.0 / 100")
    assert Decimal(first["cost_usd"]) == Decimal("0.0035")  # 2,000 in, 300 out at US$1/5
    # Asked again on the same day: the stored wording, no second request.
    again = client.post("/stocks/UP/explain/narrate", json={}).json()
    assert again["id"] == first["id"] and len(good.calls) == 1
    assert client.get("/stocks/UP/explain").json()["narration"]["id"] == first["id"]
    usage = s.scalars(select(LlmUsage)).all()
    assert [u.labeller for u in usage] == ["explain:claude-haiku-4-5"]
    # Made from other facts (the brief changed since): not shown, and asked again.
    stored = s.get(Explanation, first["id"])
    assert stored is not None
    stored.facts = stored.facts[:1]
    s.commit()
    assert client.get("/stocks/UP/explain").json()["narration"] is None
    first = client.post("/stocks/UP/explain/narrate", json={}).json()
    assert first["id"] != again["id"] and len(good.calls) == 2

    # A question is always asked, and goes in as data.
    bad = writer(FakeWriter('{"points": [{"text": "It will rise to 999.", "facts": ["F1"]}]}'))
    r = client.post("/stocks/UP/explain/narrate", json={"question": "What next?"}).json()
    assert r["status"] == "rejected" and r["points"] == []
    assert any("999" in p for p in r["problems"]) and any("forecast" in p for p in r["problems"])
    assert "<question>What next?</question>" in bad.calls[0]
    row = s.get(Explanation, r["id"])
    assert row is not None and row.question == "What next?" and row.facts[0]["id"] == "F1"
    # The rejected one is never shown as the stock's wording.
    assert client.get("/stocks/UP/explain").json()["narration"]["id"] == first["id"]
    too_long = client.post("/stocks/UP/explain/narrate", json={"question": "x" * 301})
    assert too_long.status_code == 422

    # The month's cap (shared with the news labeller) stops it.
    s.add(LlmUsage(labeller="claude-haiku-4-5", requests=1, cost_usd=Decimal("500")))
    s.commit()
    r = client.post("/stocks/UP/explain/narrate", json={"question": "Why?"})
    assert r.status_code == 409 and "cap" in r.json()["detail"]


def test_a_provider_error_is_stored_as_failed(empty_session, writer):
    _seed(empty_session)

    class Broken(FakeWriter):
        def write(self, system, user):
            raise RuntimeError("Insufficient Balance")

    writer(Broken(""))
    r = TestClient(app).post("/stocks/UP/explain/narrate", json={}).json()
    assert r["status"] == "failed" and r["problems"] == ["Insufficient Balance"]


def test_explain_a_signalled_stock(session):
    day = _signal_day(session, live=True)
    rec = session.scalars(select(SignalRecord).where(SignalRecord.signal_date == day)).first()
    assert rec is not None
    b = TestClient(app).get(f"/stocks/{rec.ticker}/explain").json()["brief"]
    sig = next(f for f in b["facts"] if f["label"] == "Signal")
    assert b["strategy"] == "score-swing" and b["research_only"] is False
    assert sig["kind"] == "rule" and sig["as_of"] == str(day)
    zone = next(f for f in b["facts"] if f["label"] == "Entry zone")
    low = Decimal(str(rec.payload["entry_zone"]["low"]))
    assert f"₹{low:,.2f}" in zone["value"]
    assert b["setup"] is not None and b["setup"]["state"] in (
        "waiting",
        "in zone",
        "above zone",
        "invalidated",
        "expired",
    )
    labels = [c["label"] for c in b["checklist"]]
    assert "The setup still meets its conditions" in labels
    assert any("stop" in c for c in b["cancels"])
