"""Alert texts and channels (Telegram, email), without the network."""

import json
import smtplib
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.alerts.channels import AlertError, EmailChannel, TelegramChannel, deliver
from app.alerts.format import (
    Digest,
    DigestAccount,
    DigestPosition,
    DigestSignal,
    digest_message,
    inr,
    signal_message,
    split_message,
)
from tests.test_signals import valid_payload

TOKEN = "123456:SECRET-token"


def test_indian_rupees():
    assert inr(1234567.5) == "₹12,34,567.50"
    assert inr(Decimal("999")) == "₹999.00"
    assert inr(100000, 0) == "₹1,00,000"
    assert inr(-1500) == "-₹1,500.00"


def test_signal_message_has_every_part_of_the_plan():
    payload = valid_payload()
    text = signal_message(payload, research_only=False, web_url="http://jeron.local/")
    assert text.startswith("NEW SIGNAL: AAA (swing, conviction 5/5)")
    for part in (
        "Buy between ₹100.00 and ₹101.00, valid until Sat 3 Oct 2026",
        "Stop ₹96.00 (2 x ATR)",
        "T1 ₹108.00 · T2 ₹112.00",
        "Size 1,980 shares, ₹9,900 at risk",
        "• one",
        "Cancel if: opens below the stop",
        "Event risk: not checked",
        "412 trades, expectancy 0.19R, profit factor 1.25",
        f"Journal: http://jeron.local/journal?signal={payload['signal_id']}",
    ):
        assert part in text
    assert "RESEARCH ONLY" not in text
    research = signal_message(payload, research_only=True, web_url="http://x")
    assert research.startswith("RESEARCH ONLY, not a trade: AAA")
    assert "not passed the backtest bar" in research


def digest(**kw):
    values = dict(
        day=date(2026, 10, 1),
        quality="warn",
        quality_reasons=["a", "b", "c", "d"],
        scan_status="ok",
        universe=523,
        top=[("AAA", Decimal("92.5")), ("BBB", Decimal(90))],
        regime="bull",
        risk_off=False,
        signals=[
            DigestSignal("breakout-52w", "RAMRAT", True, 4, Decimal(100), Decimal(94)),
            DigestSignal("breakout-52w", "WELSPUNLIV", True, 3, Decimal(150), Decimal(141)),
        ],
        accounts=[
            DigestAccount(
                "breakout-52w",
                "research only",
                Decimal(1000063),
                Decimal("0.006"),
                6,
                Decimal("3.2"),
                Decimal("0.4"),
            )
        ],
        positions=[DigestPosition("TCS", 10, Decimal("0.42"))],
        pending=2,
        web_url="http://jeron.local",
    )
    values.update(kw)
    return Digest(**values)


def test_daily_summary():
    text = digest_message(digest())
    assert text.startswith("Jeron daily summary · Thu 1 Oct 2026")
    assert "Data quality: WARN" in text and "  - and 1 more" in text
    assert "Market: bull regime; regime filter off" in text
    assert "Scan: 523 stocks scored; top AAA 92, BBB 90" in text
    assert "New signals: none (no strategy has passed the backtest bar yet)" in text
    assert "Research only, not trades (2):\n• breakout-52w: RAMRAT, WELSPUNLIV" in text
    assert "• breakout-52w (research only): ₹10,00,063 (+0.01%), 6 open, heat 3.2%" in text
    assert "• 1 open: TCS +0.42R" in text
    assert "• 2 live signals waiting for a decision" in text


def test_summary_of_a_blocked_day_with_live_signals():
    live = DigestSignal("score-swing", "INFY", False, 5, Decimal(1500), Decimal(1450))
    text = digest_message(
        digest(
            quality="fail",
            scan_status="blocked",
            scan_reasons=["Data quality FAILED"],
            signals=[live],
            risk_off=True,
            positions=[],
            pending=0,
        )
    )
    assert "Scan: BLOCKED\n  - Data quality FAILED" in text
    assert "regime filter ON: risk per trade halved" in text
    assert "New signals (1):\n• INFY (score-swing, conviction 5/5)" in text
    assert "Research only" not in text and "• no open positions" in text


def test_split_long_messages():
    text = "\n".join(f"line {i:04d} " + "x" * 90 for i in range(100))
    parts = split_message(text, 1000)
    assert all(len(p) <= 1000 for p in parts)
    assert "\n".join(parts) == text
    assert split_message("y" * 2500, 1000) == ["y" * 1000, "y" * 1000, "y" * 500]
    assert split_message("") == [""]


def telegram(handler):
    return TelegramChannel(TOKEN, "42", httpx.Client(transport=httpx.MockTransport(handler)))


def test_telegram_sends_in_parts():
    sent = []

    def handler(request):
        assert request.url.path == f"/bot{TOKEN}/sendMessage"
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {}})

    telegram(handler).send("a" * 5000)
    assert [len(m["text"]) for m in sent] == [4096, 904]
    assert sent[0]["chat_id"] == "42"


def test_telegram_errors_never_show_the_token():
    def refused(request):
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})

    with pytest.raises(AlertError, match="Unauthorized"):
        telegram(refused).send("hi")

    def down(request):
        raise httpx.ConnectError(f"cannot reach {request.url}")

    with pytest.raises(AlertError) as e:
        telegram(down).send("hi")
    assert TOKEN not in str(e.value) and "<token>" in str(e.value)


def test_telegram_setup_lists_chats():
    def handler(request):
        updates = [{"message": {"chat": {"id": 42, "username": "abhishek"}}}, {"other": 1}]
        return httpx.Response(200, json={"ok": True, "result": updates})

    assert telegram(handler).chats() == [("42", "abhishek")]


class FakeSMTP:
    sent: list = []
    fail = False

    def __init__(self, host, port):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        if self.fail:
            raise smtplib.SMTPAuthenticationError(535, b"bad password")

    def send_message(self, message):
        FakeSMTP.sent.append(message)


def test_email_and_fallback():
    email = EmailChannel("smtp.test", 587, "", "me@test", "me@test", "pw", smtp=FakeSMTP)

    def down(request):
        raise httpx.ConnectError("no network")

    channel, errors = deliver([telegram(down), email], "hello", "Jeron test")
    assert channel == "email" and errors[0].startswith("telegram:")
    (message,) = FakeSMTP.sent
    assert message["Subject"] == "Jeron test" and message["To"] == "me@test"
    FakeSMTP.fail = True
    try:
        channel, errors = deliver([email], "hello", "x")
    finally:
        FakeSMTP.fail = False
    assert channel is None and "bad password" in errors[0]
