"""Read the Telegram buttons pressed under signal alerts and record them in the journal
(docs/plans/ui-v2.md). Runs every minute from the scheduler while Telegram is set up.

- "Skip, with reason" swaps the buttons for the reasons; a reason records the skip.
- "I bought it" records the signal as taken and asks for the shares and price; the
  reply adds the buy fill (today, charges estimated), which the journal can correct.

Only the configured chat is listened to. Each update is stored once (`bot_updates`), so
a re-read records nothing twice."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.buttons import (
    buy_prompt,
    parse_bought,
    parse_press,
    prompt_signal,
    reasons_keyboard,
)
from app.alerts.channels import AlertError, TelegramChannel
from app.alerts.format import _day, inr, journal_link
from app.backtest.costs import CostModel
from app.config import Settings
from app.journal.service import JournalError, add_fill, decide, signal_info
from app.models import BotUpdate, JournalEntry, JournalFill
from app.settings_store import effective_settings
from app.signals.build import IST

Log = Callable[[str], None]


def _quiet(_: str) -> None:
    pass


@dataclass
class BotOutcome:
    handled: int = 0
    recorded: int = 0
    error: str | None = None


def _entry(session: Session, signal_id: UUID) -> JournalEntry | None:
    return session.scalar(select(JournalEntry).where(JournalEntry.signal_id == signal_id))


def _has_fills(session: Session, entry: JournalEntry | None) -> bool:
    return entry is not None and bool(
        session.scalar(select(func.count()).where(JournalFill.entry_id == entry.id))
    )


def _charges(shares: int, price: Decimal) -> Decimal:
    """Estimated buy charges, as a tradebook import estimates them."""
    c = CostModel().charges(float(price * shares), "buy")
    return Decimal(f"{c.total - c.dp:.2f}")


class _Handler:
    def __init__(
        self, session: Session, channel: TelegramChannel, settings: Settings, now: datetime
    ):
        self.session, self.channel, self.settings, self.now = session, channel, settings, now
        self.recorded = 0

    def press(self, query: dict[str, Any]) -> tuple[str, UUID | None, str]:
        message = query.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id", ""))
        message_id = message.get("message_id")
        press = parse_press(str(query.get("data", "")))
        if press is None:
            self.channel.answer(query["id"], "That button is not one Jeron knows.")
            return "ignored", None, "unknown button"
        info = signal_info(self.session, press.signal_id)
        if info is None:
            self.channel.answer(query["id"], "That signal is not in Jeron.")
            return "ignored", press.signal_id, "unknown signal"
        entry = _entry(self.session, press.signal_id)
        if press.action == "skip":
            if _has_fills(self.session, entry):
                self.channel.answer(query["id"], f"{info.ticker} already has a buy recorded.")
                return "skip", press.signal_id, "already bought"
            if message_id is not None:
                self.channel.set_buttons(chat_id, message_id, reasons_keyboard(str(info.signal_id)))
            self.channel.answer(query["id"], "Why skip it?")
            return "skip", press.signal_id, "asked why"
        if press.action == "skipr":
            if _has_fills(self.session, entry):
                self.channel.answer(query["id"], f"{info.ticker} already has a buy recorded.")
                return "skip", press.signal_id, "already bought"
            decide(self.session, press.signal_id, "skipped", reason=press.reason)
            if message_id is not None:
                self.channel.set_buttons(chat_id, message_id, None)
            self.recorded += 1
            self.channel.answer(query["id"], f"Skipped: {press.reason}")
            self.channel.send(
                f"Journal: skipped {info.ticker} ({press.reason}). "
                f"Change it at {journal_link(self.settings.web_url, str(info.signal_id))}"
            )
            return "skip", press.signal_id, f"skipped: {press.reason}"
        # "I bought it"
        if entry is None or entry.decision == "skipped":
            decide(self.session, press.signal_id, "taken")
        zone_high = Decimal(str(info.payload["entry_zone"]["high"]))
        self.channel.ask(
            buy_prompt(info.ticker, int(info.payload["shares"]), zone_high, str(info.signal_id))
        )
        self.channel.answer(query["id"], "Reply with the shares and price.")
        return "buy", press.signal_id, "asked for the fill"

    def reply(self, message: dict[str, Any]) -> tuple[str, UUID | None, str]:
        prompt = str((message.get("reply_to_message") or {}).get("text", ""))
        signal_id = prompt_signal(prompt)
        if signal_id is None:
            return "ignored", None, "a message, not a reply to a buy prompt"
        info = signal_info(self.session, signal_id)
        if info is None:
            return "ignored", signal_id, "unknown signal"
        bought = parse_bought(str(message.get("text", "")))
        if bought is None:
            self.channel.ask("Couldn't read that. " + prompt)
            return "bought", signal_id, "unreadable reply"
        entry = _entry(self.session, signal_id) or decide(self.session, signal_id, "taken")
        day = self.now.astimezone(IST).date()
        try:
            add_fill(
                self.session,
                entry,
                day,
                "buy",
                bought.shares,
                bought.price,
                _charges(bought.shares, bought.price),
                source="telegram",
                charges_estimated=True,
            )
        except JournalError as e:
            self.session.rollback()
            self.channel.send(f"Not recorded: {e}")
            return "bought", signal_id, f"refused: {e}"
        self.recorded += 1
        self.channel.send(
            f"Journal: bought {bought.shares:,} {info.ticker} at {inr(bought.price)} on "
            f"{_day(day)} (charges estimated). Check it, or import the tradebook later: "
            f"{journal_link(self.settings.web_url, str(signal_id))}"
        )
        return "bought", signal_id, f"{bought.shares} at {bought.price}"


def poll(
    session: Session,
    *,
    settings: Settings | None = None,
    channel: TelegramChannel | None = None,
    now: datetime | None = None,
    log: Log = _quiet,
) -> BotOutcome:
    settings = settings or effective_settings(session)
    outcome = BotOutcome()
    if not settings.telegram_ready:
        return outcome
    channel = channel or TelegramChannel(settings.telegram_bot_token, settings.telegram_chat_id)
    handler = _Handler(session, channel, settings, now or datetime.now(IST))
    last = session.scalar(select(func.max(BotUpdate.update_id)))
    try:
        updates = channel.updates(None if last is None else last + 1)
    except AlertError as e:
        outcome.error = str(e)
        log(f"Telegram buttons: {e}")
        return outcome
    for update in updates:
        update_id = int(update["update_id"])
        if session.get(BotUpdate, update_id) is not None:
            continue
        query = update.get("callback_query")
        message = update.get("message") or {}
        chat = ((query or {}).get("message") or message).get("chat") or {}
        try:
            if str(chat.get("id", "")) != str(settings.telegram_chat_id):
                kind, signal_id, what = "ignored", None, "another chat"
            elif query is not None:
                kind, signal_id, what = handler.press(query)
            else:
                kind, signal_id, what = handler.reply(message)
        except AlertError as e:
            # Telegram failed mid-way; leave the update unstored so the next poll retries.
            outcome.error = str(e)
            log(f"Telegram buttons: {e}")
            break
        session.add(BotUpdate(update_id=update_id, kind=kind, signal_id=signal_id, outcome=what))
        session.commit()
        outcome.handled += 1
        if kind != "ignored":
            log(f"Telegram: {kind} {what}")
    outcome.recorded = handler.recorded
    return outcome
