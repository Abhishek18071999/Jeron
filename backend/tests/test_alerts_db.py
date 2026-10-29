"""M5 end to end on a real Postgres: scan -> paper signal -> alert -> journal."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.channels import AlertError
from app.alerts.job import run_alerts, send_test
from app.backtest.job import run_backtests
from app.calendar.nse import TradingCalendar
from app.config import Settings, get_settings
from app.db import get_engine
from app.enums import Exchange
from app.main import app
from app.models import Alert, Instrument, SignalRecord, SymbolChange
from app.paper.job import run_paper
from app.signals.build import IST
from tests.conftest import TEST_DATABASE_URL, requires_db, reset_database
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
    reset_database(config)
    with Session(get_engine()) as s:
        yield s
    get_engine().dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()


START, END = DAYS[-120], DAYS[-1]
NOW = datetime(2026, 1, 1, 19, 0, tzinfo=IST)


class FakeChannel:
    def __init__(self, name="telegram", fail=False):
        self.name, self.fail, self.sent, self.buttons = name, fail, [], []

    def send(self, text, subject, buttons=None):
        if self.fail:
            raise AlertError("network down")
        self.sent.append((subject, text))
        self.buttons.append(buttons)


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
    text = next(t for _, t in telegram.sent if t.startswith(f"SWING · NEW SIGNAL: {first.ticker}"))
    assert f"journal?signal={first.signal_id}" in text
    summary = telegram.sent[-1][1]
    assert f"Swing: {len(signals)} to buy" in summary
    assert "Intraday: not running (no intraday prices yet)" in summary
    assert "Long-term: nothing to buy (waiting for its first backtest)" in summary
    alert = session.scalar(select(Alert).where(Alert.key == f"signal:{first.signal_id}"))
    assert alert.status == "sent" and alert.attempts == 2 and alert.channel == "telegram"

    # A re-run sends nothing twice.
    again = run_alerts(session, day, settings=settings, channels=[telegram], now=NOW)
    assert not again.sent and again.already_sent == len(signals) + 1
    assert send_test(session, settings=settings, channels=[telegram], now=NOW).status == "sent"

    client = TestClient(app)
    # The four sections: swing holds the live signals with what, when, how much, why.
    overview = {s["key"]: s for s in client.get("/sections").json()}
    assert list(overview) == ["swing", "intraday", "positional", "invest"]
    assert overview["swing"]["state"] == "live"
    assert overview["intraday"]["state"] == "not_running" and overview["intraday"]["needs"]
    assert overview["invest"]["state"] == "untested"
    swing = client.get("/sections/swing", params={"date": str(day)}).json()
    (card,) = [c for c in swing["signals"] if c["signal_id"] == str(first.signal_id)]
    assert card["what"].startswith(f"Buy {first.ticker}: ")
    assert card["when"].startswith("On ") and "LIMIT BUY" in card["when"]
    assert f"{first.payload['shares']:,} shares" in card["how_much"]
    assert card["why"] == first.payload["why"]
    assert client.get("/sections/options").status_code == 404

    # The journal: the signal is pending until I decide; then fills and stats.
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
    assert "Swing: nothing to buy (no strategy has passed the backtest bar)" in summary
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
    assert all(t.startswith("SWING · RESEARCH ONLY") for _, t in telegram.sent[1:])


def test_dashboard_and_alerts_before_any_data(empty_session):
    client = TestClient(app)
    board = client.get("/dashboard").json()
    assert board["as_of"] is None and board["signals"] == [] and board["accounts"] == []
    assert client.get("/journal").json() == {"entries": [], "pending": [], "stats": []}
    states = {s["key"]: s["state"] for s in client.get("/sections").json()}
    assert states == {
        "swing": "untested",
        "intraday": "not_running",
        "positional": "untested",
        "invest": "untested",
    }
    assert client.get("/sections/positional").json()["signals"] == []
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
        ("RELIANCE", "Reliance Industries Limited"),
        ("RALLIS", "Rallis India Limited"),
        ("ZOMATO", None),
        ("ETERNAL", "ETERNAL LIMITED"),
    ]:
        empty_session.add(Instrument(exchange=Exchange.NSE, symbol=symbol, name=name))
    empty_session.add(
        SymbolChange(old_symbol="ZOMATO", new_symbol="ETERNAL", change_date=date(2025, 4, 9))
    )
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
    assert search("ril") == ["RELIANCE", "RALLIS"]  # short-name list, then initials
    assert search("zomato") == ["ETERNAL"]
    first = client.get("/stocks/search", params={"q": "tata steel"}).json()[0]
    assert first == {
        "symbol": "TATASTEEL",
        "name": "Tata Steel Limited",
        "series": "EQ",
        "alias": None,
    }
    renamed = client.get("/stocks/search", params={"q": "zomato"}).json()[0]
    assert renamed["alias"] == "was ZOMATO"


def test_signal_on_an_unexplained_drop_is_marked_held(session):
    from tests.test_exits_db import _held

    day = _signal_day(session, live=True)
    ticker = session.scalars(select(SignalRecord.ticker).where(SignalRecord.signal_date == day))
    held = sorted(ticker)[0]
    _held(session, day, held)
    telegram = FakeChannel()
    run_alerts(session, day, settings=Settings(), channels=[telegram], now=NOW)
    text = next(t for subject, t in telegram.sent if f": {held} (" in subject)
    assert text.startswith(f"HELD, check by hand before buying: {held} fell -30.00%")


class FakeBot:
    """Telegram for app/alerts/bot.py: queued updates, and what the bot said back."""

    name = "telegram"

    def __init__(self, updates):
        self.queue, self.said, self.asked, self.answers, self.markups = updates, [], [], [], []

    def updates(self, offset):
        return [u for u in self.queue if offset is None or u["update_id"] >= offset]

    def send(self, text, subject="", buttons=None):
        self.said.append(text)

    def ask(self, text):
        self.asked.append(text)

    def answer(self, callback_id, text):
        self.answers.append(text)

    def set_buttons(self, chat_id, message_id, buttons):
        self.markups.append(buttons)


def _press(update_id, data, chat="42"):
    message = {"message_id": 7, "chat": {"id": int(chat)}}
    return {
        "update_id": update_id,
        "callback_query": {"id": f"q{update_id}", "data": data, "message": message},
    }


def _reply(update_id, text, prompt, chat="42"):
    return {
        "update_id": update_id,
        "message": {
            "chat": {"id": int(chat)},
            "text": text,
            "reply_to_message": {"text": prompt},
        },
    }


def test_telegram_buttons_record_skips_and_buys(session):
    from app.alerts.bot import poll
    from app.models import BotUpdate, JournalEntry, JournalFill

    _signal_day(session, live=True)
    first, second = session.scalars(
        select(SignalRecord).order_by(SignalRecord.signal_date.desc(), SignalRecord.ticker)
    ).all()[:2]
    settings = Settings(telegram_bot_token="t", telegram_chat_id="42", web_url="http://jeron.local")

    # Skip, then the reason: recorded as skipped; another chat is ignored.
    bot = FakeBot(
        [
            _press(1, f"skip:{first.signal_id}"),
            _press(2, f"skipr:{first.signal_id}:1"),
            _press(3, f"skipr:{second.signal_id}:0", chat="99"),
        ]
    )
    outcome = poll(session, settings=settings, channel=bot, now=NOW)
    assert outcome.handled == 3 and outcome.recorded == 1
    assert bot.markups[0] and bot.markups[1] is None  # reasons shown, then removed
    entry = session.scalar(select(JournalEntry).where(JournalEntry.signal_id == first.signal_id))
    assert entry.decision == "skipped" and entry.reason == "No cash free"
    assert (
        session.scalar(select(JournalEntry).where(JournalEntry.signal_id == second.signal_id))
        is None
    )

    # I bought it: taken, asked for the fill; the reply adds the buy.
    bot = FakeBot([_press(4, f"buy:{second.signal_id}")])
    poll(session, settings=settings, channel=bot, now=NOW)
    (prompt,) = bot.asked
    bot = FakeBot([_reply(5, "no idea", prompt), _reply(6, "10 @ 101.50", prompt)])
    outcome = poll(session, settings=settings, channel=bot, now=NOW)
    assert outcome.recorded == 1 and bot.asked[0].startswith("Couldn't read that.")
    entry = session.scalar(select(JournalEntry).where(JournalEntry.signal_id == second.signal_id))
    (fill,) = session.scalars(select(JournalFill).where(JournalFill.entry_id == entry.id)).all()
    assert entry.decision == "taken"
    assert (fill.shares, fill.price, fill.source) == (10, Decimal("101.50"), "telegram")
    assert fill.charges > 0 and fill.charges_estimated

    # Nothing is recorded twice, and a bought signal can't be skipped by a stray tap.
    again = FakeBot([_reply(6, "10 @ 101.50", prompt), _press(7, f"skipr:{second.signal_id}:2")])
    poll(session, settings=settings, channel=again, now=NOW)
    assert session.scalar(select(func.count()).select_from(JournalFill)) == 1
    assert session.get(JournalEntry, entry.id).decision == "taken"
    assert session.scalar(select(func.count()).select_from(BotUpdate)) == 7

    # The broker's tradebook later replaces the typed fill with its own.
    from app.journal.importer import import_tradebook
    from tests.test_tradebook import HEADER

    day = NOW.date()
    rows = [
        f"{second.ticker},,{day},NSE,EQ,EQ,buy,false,6,101.40,5001,7001,{day}T09:15:01",
        f"{second.ticker},,{day},NSE,EQ,EQ,buy,false,4,101.40,5002,7001,{day}T09:15:02",
    ]
    result = import_tradebook(session, "\n".join([HEADER, *rows]) + "\n")
    assert (result.added, result.replaced) == (2, 1)
    fills = session.scalars(select(JournalFill).where(JournalFill.entry_id == entry.id)).all()
    assert sorted((f.source, f.shares) for f in fills) == [("tradebook", 4), ("tradebook", 6)]


def test_signal_alerts_carry_buttons(session):
    day = _signal_day(session, live=True)
    telegram = FakeChannel()
    run_alerts(
        session,
        day,
        settings=Settings(web_url="http://localhost:3000"),
        channels=[telegram],
        now=NOW,
    )
    signal_buttons = [
        b for (s, _), b in zip(telegram.sent, telegram.buttons, strict=True) if "Signal" in s
    ]
    assert signal_buttons and all(b[0][0]["text"] == "I bought it" for b in signal_buttons)
    assert telegram.buttons[-1] is None  # the summary has none


def test_late_data_is_told_once(empty_session):
    """The day's NSE data did not arrive: one alert saying what is loaded and when Jeron
    tries again; the retry run (or a manual one) doesn't send it twice."""
    from app.alerts.late import data_late

    calendar = TradingCalendar.default()
    channel = FakeChannel()
    friday = datetime(2026, 10, 23, 19, 5, tzinfo=IST)
    settings = Settings(telegram_bot_token="t", telegram_chat_id="1")
    assert data_late(empty_session, calendar, now=friday, settings=settings, channels=[channel])
    ((subject, text),) = channel.sent
    assert "Fri 23 Oct 2026 has not arrived" in text
    assert "No prices are loaded yet." in text
    assert "tries again at 21:30 IST" in text
    late = empty_session.scalar(select(Alert).where(Alert.key == "late:2026-10-23"))
    assert late is not None and late.kind == "late" and late.status == "sent"
    # The 21:30 retry still finds nothing: no second message.
    retry = datetime(2026, 10, 23, 21, 35, tzinfo=IST)
    assert data_late(empty_session, calendar, now=retry, settings=settings, channels=[channel])
    assert len(channel.sent) == 1


def test_data_on_time_sends_nothing(session):
    from app.alerts.late import data_late

    channel = FakeChannel()
    newest = DAYS[-1]
    # The evening of the newest loaded session, after the daily time: nothing is late.
    evening = datetime(newest.year, newest.month, newest.day, 19, 30, tzinfo=IST)
    calendar = TradingCalendar.default()
    assert not data_late(session, calendar, now=evening, settings=Settings(), channels=[channel])
    assert channel.sent == []
