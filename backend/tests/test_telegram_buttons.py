"""Telegram buttons under signal alerts: keyboards and parsing (app/alerts/buttons.py)."""

import json
from decimal import Decimal
from uuid import UUID, uuid4

import httpx

from app.alerts.buttons import (
    SKIP_REASONS,
    Bought,
    buy_prompt,
    parse_bought,
    parse_press,
    prompt_signal,
    public_url,
    reasons_keyboard,
    signal_keyboard,
)
from app.alerts.channels import TelegramChannel

SID = "1b4e28ba-2fa1-11d2-883f-0016d3cca427"


def test_open_plan_needs_an_address_telegram_can_open():
    assert not public_url("http://localhost:3000")
    assert not public_url("http://127.0.0.1:3000")
    assert public_url("http://my-pc.tail1234.ts.net:3000")
    local = signal_keyboard(SID, "AZAD", "http://localhost:3000")
    assert [b["text"] for row in local for b in row] == ["I bought it", "Skip, with reason"]
    remote = signal_keyboard(SID, "AZAD", "https://jeron.example.net/")
    assert remote[0] == [
        {"text": "Open plan", "url": f"https://jeron.example.net/plan/AZAD?signal={SID}"}
    ]
    # Telegram allows at most 64 bytes of callback data.
    for row in [*remote, *reasons_keyboard(SID)]:
        for button in row:
            assert len(button.get("callback_data", "").encode()) <= 64


def test_presses():
    assert parse_press(f"buy:{SID}").action == "buy"
    assert parse_press(f"skip:{SID}").signal_id == UUID(SID)
    press = parse_press(f"skipr:{SID}:1")
    assert press.action == "skipr" and press.reason == SKIP_REASONS[1]
    for bad in ("", "buy", "buy:nope", f"skipr:{SID}", f"skipr:{SID}:99", f"sell:{SID}"):
        assert parse_press(bad) is None


def test_buy_prompt_and_reply():
    sid = str(uuid4())
    prompt = buy_prompt("AZAD", 80, Decimal("612.5"), sid)
    assert "80 612.50" in prompt and prompt_signal(prompt) == UUID(sid)
    assert prompt_signal("hello") is None
    assert parse_bought("80 612.5") == Bought(80, Decimal("612.5"))
    assert parse_bought("1,200 shares @ ₹1,612.50") == Bought(1200, Decimal("1612.50"))
    for bad in ("80", "yes", "80.5 612", "0 612", "80 612 3"):
        assert parse_bought(bad) is None


def test_buttons_go_under_the_last_part():
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"ok": True, "result": {}})

    channel = TelegramChannel("t", "42", httpx.Client(transport=httpx.MockTransport(handler)))
    channel.send("x" * 5000, "", signal_keyboard(SID, "AZAD", "http://localhost:3000"))
    bodies = [json.loads(r.content) for r in sent]
    assert len(bodies) == 2
    assert "reply_markup" not in bodies[0] and "inline_keyboard" in bodies[1]["reply_markup"]
