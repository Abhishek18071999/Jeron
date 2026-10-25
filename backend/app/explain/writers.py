"""The explain narration through the news labeller's provider (`JERON_NEWS_PROVIDER`):
the same key, model and transport, a different prompt. One request per narration, and
it spends from the same monthly cap (decision 0012). Tests use a fake writer."""

from typing import Any, Protocol

from app.config import Settings
from app.explain.narrate import NARRATION_SCHEMA
from app.news.claude import ClaudeLabeller, Usage
from app.news.deepseek import DeepSeekLabeller
from app.news.gemini import GeminiLabeller
from app.news.job import make_labeller
from app.news.ollama import OllamaLabeller

MAX_TOKENS = 2500


class Writer(Protocol):
    name: str  # the model id, stored with every narration

    def write(self, system: str, user: str) -> tuple[str | None, Usage]: ...


class ClaudeWriter:
    def __init__(self, labeller: ClaudeLabeller) -> None:
        self.client = labeller.client
        self.name = labeller.name

    def write(self, system: str, user: str) -> tuple[str | None, Usage]:
        output_config: dict[str, Any] = {
            "format": {"type": "json_schema", "schema": NARRATION_SCHEMA}
        }
        if not self.name.startswith("claude-haiku"):
            output_config["effort"] = "low"
        message = self.client.messages.create(
            model=self.name,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
        )
        used = Usage()
        used.add(message)
        if getattr(message, "stop_reason", None) in ("refusal", "max_tokens"):
            return None, used
        text = next((b.text for b in message.content if getattr(b, "type", "") == "text"), "")
        return text, used


class ChatWriter:
    """DeepSeek, Gemini and Ollama, through the labeller's own request code."""

    def __init__(self, labeller: DeepSeekLabeller) -> None:
        self.labeller = labeller
        self.name = labeller.name

    def write(self, system: str, user: str) -> tuple[str | None, Usage]:
        lab = self.labeller
        if isinstance(lab, OllamaLabeller):
            content, tokens_in, tokens_out = lab._reply(
                lab._post(lab._body(system, user, NARRATION_SCHEMA))
            )
        elif isinstance(lab, GeminiLabeller):
            content, tokens_in, tokens_out = lab._content(lab._post(lab._body(system, user)))
        else:
            body = {
                "model": lab.name,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": MAX_TOKENS,
                "temperature": 0,
                "stream": False,
            }
            data = lab._post(body)
            usage = data.get("usage") or {}
            tokens_in = int(usage.get("prompt_tokens") or 0)
            tokens_out = int(usage.get("completion_tokens") or 0)
            choice = (data.get("choices") or [{}])[0]
            content = None
            if choice.get("finish_reason") in (None, "stop"):
                content = (choice.get("message") or {}).get("content") or ""
        return content, Usage(1, tokens_in, tokens_out)


def make_writer(settings: Settings) -> Writer | None:
    """The writer for the provider in `.env`; None without its key."""
    labeller = make_labeller(settings)
    if isinstance(labeller, ClaudeLabeller):
        return ClaudeWriter(labeller)
    if isinstance(labeller, DeepSeekLabeller):
        return ChatWriter(labeller)
    return None
