"""Telegram buttons under each signal alert (docs/plans/ui-v2.md): "Open plan", "Skip,
with reason" and "I bought it". Pure: the keyboards, what a button press or a reply
means. `bot.py` reads the presses and records them in the journal.

A press carries `callback_data` (at most 64 bytes): "skip:<signal id>",
"skipr:<signal id>:<reason>" or "buy:<signal id>". "I bought it" asks for the shares and
price in a forced reply whose text names the signal, so the reply can be matched to it
without any state kept between messages."""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

# Why a signal was skipped: the journal's reason, one tap each.
SKIP_REASONS = (
    "Opened above the entry zone",
    "No cash free",
    "Too much heat or sector exposure",
    "News or results I don't like",
    "Didn't see it in time",
    "Other",
)
REF = "ref "
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

Keyboard = list[list[dict[str, str]]]


def public_url(web_url: str) -> bool:
    """Telegram refuses URL buttons to localhost; a Tailscale or LAN name works."""
    parsed = urlparse(web_url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme in ("http", "https") and host not in ("", "localhost", "127.0.0.1")


def plan_url(web_url: str, ticker: str, signal_id: str) -> str:
    return f"{web_url.rstrip('/')}/plan/{ticker}?signal={signal_id}"


def signal_keyboard(signal_id: str, ticker: str, web_url: str) -> Keyboard:
    row: list[dict[str, str]] = [
        {"text": "I bought it", "callback_data": f"buy:{signal_id}"},
        {"text": "Skip, with reason", "callback_data": f"skip:{signal_id}"},
    ]
    rows = [row]
    if public_url(web_url):
        rows.insert(0, [{"text": "Open plan", "url": plan_url(web_url, ticker, signal_id)}])
    return rows


def reasons_keyboard(signal_id: str) -> Keyboard:
    return [
        [{"text": reason, "callback_data": f"skipr:{signal_id}:{i}"}]
        for i, reason in enumerate(SKIP_REASONS)
    ]


@dataclass(frozen=True)
class Press:
    action: str  # "buy" / "skip" / "skipr"
    signal_id: UUID
    reason: str = ""


def parse_press(data: str) -> Press | None:
    parts = data.split(":")
    if len(parts) < 2 or parts[0] not in ("buy", "skip", "skipr"):
        return None
    try:
        signal_id = UUID(parts[1])
    except ValueError:
        return None
    if parts[0] != "skipr":
        return Press(parts[0], signal_id) if len(parts) == 2 else None
    if len(parts) != 3 or not parts[2].isdigit() or int(parts[2]) >= len(SKIP_REASONS):
        return None
    return Press("skipr", signal_id, SKIP_REASONS[int(parts[2])])


def buy_prompt(ticker: str, shares: int, zone_high: Decimal, signal_id: str) -> str:
    return (
        f"Bought {ticker}? Reply with the shares and the price you paid, like "
        f'"{shares} {zone_high:.2f}" (the plan: {shares:,} at up to ₹{zone_high:.2f}). '
        f"{REF}{signal_id}"
    )


def prompt_signal(prompt: str) -> UUID | None:
    """The signal a buy prompt asks about, from its text."""
    found = re.search(re.escape(REF) + f"({_UUID})", prompt)
    return UUID(found.group(1)) if found else None


@dataclass(frozen=True)
class Bought:
    shares: int
    price: Decimal


def parse_bought(text: str) -> Bought | None:
    """ "80 612.5", "80 @ ₹612.50" or "80 shares at 612.5": shares, then the price."""
    numbers = re.findall(r"\d[\d,]*(?:\.\d+)?", text)
    if len(numbers) != 2:
        return None
    try:
        shares_text, price_text = (n.replace(",", "") for n in numbers)
        if "." in shares_text:
            return None
        shares, price = int(shares_text), Decimal(price_text)
    except (ValueError, InvalidOperation):
        return None
    if shares <= 0 or price <= 0:
        return None
    return Bought(shares, price)


def markup(keyboard: Keyboard) -> dict[str, Any]:
    return {"inline_keyboard": keyboard}
