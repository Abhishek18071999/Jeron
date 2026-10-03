"""Where alerts go: Telegram first, email as the backup (spec section 9)."""

import smtplib
from collections.abc import Callable, Sequence
from email.message import EmailMessage
from typing import Any, Protocol

import httpx

from app.alerts.format import split_message
from app.config import Settings

TELEGRAM_API = "https://api.telegram.org"


class AlertError(RuntimeError):
    """A channel could not deliver a message."""


class Channel(Protocol):
    name: str

    def send(self, text: str, subject: str) -> None: ...


class TelegramChannel:
    name = "telegram"

    def __init__(self, token: str, chat_id: str, client: httpx.Client | None = None) -> None:
        self._token = token
        self.chat_id = chat_id
        self._client = client or httpx.Client(timeout=20.0)

    def _call(self, method: str, payload: dict[str, Any]) -> Any:
        url = f"{TELEGRAM_API}/bot{self._token}/{method}"
        try:
            response = self._client.post(url, json=payload)
            body = response.json()
        except (httpx.HTTPError, ValueError) as e:
            # The bot token is part of the URL; never let it into a log or the database.
            raise AlertError(str(e).replace(self._token, "<token>")) from None
        if not body.get("ok"):
            raise AlertError(
                f"Telegram refused {method}: {body.get('description', response.status_code)}"
            )
        return body.get("result")

    def send(self, text: str, subject: str = "") -> None:
        for part in split_message(text):
            self._call(
                "sendMessage",
                {"chat_id": self.chat_id, "text": part, "disable_web_page_preview": True},
            )

    def chats(self) -> list[tuple[str, str]]:
        """(chat id, name) of everyone who has messaged the bot recently."""
        seen: dict[str, str] = {}
        for update in self._call("getUpdates", {}) or []:
            message = update.get("message") or update.get("channel_post") or {}
            chat = message.get("chat") or {}
            if "id" in chat:
                name = chat.get("username") or chat.get("title") or chat.get("first_name") or ""
                seen[str(chat["id"])] = name
        return list(seen.items())


class EmailChannel:
    name = "email"

    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        to: str,
        user: str = "",
        password: str = "",
        starttls: bool = True,
        smtp: Callable[[str, int], smtplib.SMTP] = smtplib.SMTP,
    ) -> None:
        self.host, self.port, self.sender, self.to = host, port, sender or user or to, to
        self._user, self._password, self._starttls, self._smtp = user, password, starttls, smtp

    def send(self, text: str, subject: str) -> None:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.sender
        message["To"] = self.to
        message.set_content(text)
        try:
            with self._smtp(self.host, self.port) as server:
                if self._starttls:
                    server.starttls()
                if self._user:
                    server.login(self._user, self._password)
                server.send_message(message)
        except (OSError, smtplib.SMTPException) as e:
            raise AlertError(f"Email to {self.to} failed: {e}") from None


def channels_from(settings: Settings) -> list[Channel]:
    """The configured channels, Telegram first."""
    out: list[Channel] = []
    if settings.telegram_ready:
        out.append(TelegramChannel(settings.telegram_bot_token, settings.telegram_chat_id))
    if settings.email_ready:
        out.append(
            EmailChannel(
                settings.smtp_host,
                settings.smtp_port,
                settings.alert_email_from,
                settings.alert_email_to,
                settings.smtp_user,
                settings.smtp_password,
                settings.smtp_starttls,
            )
        )
    return out


def deliver(channels: Sequence[Channel], text: str, subject: str) -> tuple[str | None, list[str]]:
    """Try each channel in order until one works: (the channel that delivered, errors)."""
    errors: list[str] = []
    for channel in channels:
        try:
            channel.send(text, subject)
        except AlertError as e:
            errors.append(f"{channel.name}: {e}")
            continue
        return channel.name, errors
    return None, errors
