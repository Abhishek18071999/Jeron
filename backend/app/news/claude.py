"""Claude as the news labeller, through the Anthropic API.

One request per announcement for the daily run; the Message Batches API (half price,
results within a day) for the history. Replies are strict JSON (structured outputs),
checked again against `NewsLabel`. The API key comes from `JERON_ANTHROPIC_API_KEY` in
`.env` and is never logged.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.news.labels import (
    LABEL_SCHEMA,
    SYSTEM_PROMPT,
    NewsItem,
    NewsLabel,
    parse_label,
    user_prompt,
)

MAX_TOKENS = 2000

# US$ per million tokens: (input, output, cache read, cache write). Batches cost half.
# For the cost estimate printed after a run; the bill on console.anthropic.com is final.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
    "claude-haiku-4-5": (1.0, 5.0, 0.10, 1.25),
}


@dataclass
class Usage:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, message: Any) -> None:
        usage = getattr(message, "usage", None)
        if usage is None:
            return
        self.requests += 1
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0

    def cost(self, model: str, batch: bool = False) -> float | None:
        """Estimated US$; None for a model without a price here."""
        price = PRICES.get(model)
        if price is None:
            return None
        tokens = (
            self.input_tokens,
            self.output_tokens,
            self.cache_read_tokens,
            self.cache_write_tokens,
        )
        total = sum(t * p for t, p in zip(tokens, price, strict=True)) / 1_000_000
        return total / 2 if batch else total


class Labeller(Protocol):
    """Anything that labels announcements; tests use a fake."""

    name: str  # stored with every label (the model id)

    def label(self, items: Sequence[NewsItem]) -> list[NewsLabel | None]: ...


def request_params(model: str, item: NewsItem) -> dict[str, Any]:
    """The Messages API request for one announcement."""
    output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": LABEL_SCHEMA}}
    if not model.startswith("claude-haiku"):
        # A short classification: little thinking needed on models that think.
        output_config["effort"] = "low"
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        # Cached after the first request on models whose cache minimum it reaches.
        "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user_prompt(item)}],
        "output_config": output_config,
    }


def label_from_message(message: Any) -> NewsLabel | None:
    """The label in a Messages API reply; None when the model refused, ran out of
    tokens or returned something that doesn't fit the schema."""
    if getattr(message, "stop_reason", None) in ("refusal", "max_tokens"):
        return None
    text = next((b.text for b in message.content if getattr(b, "type", "") == "text"), "")
    return parse_label(text)


class ClaudeLabeller:
    def __init__(self, api_key: str, model: str, client: Any = None) -> None:
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
        self.client = client
        self.name = model
        self.usage = Usage()

    def label(self, items: Sequence[NewsItem]) -> list[NewsLabel | None]:
        labels = []
        for item in items:
            message = self.client.messages.create(**request_params(self.name, item))
            self.usage.add(message)
            labels.append(label_from_message(message))
        return labels

    # History: the Message Batches API ---------------------------------------------

    BATCH_LIMIT = 100_000

    def submit_batch(self, items: Sequence[NewsItem]) -> str:
        if len(items) > self.BATCH_LIMIT:
            raise ValueError(f"at most {self.BATCH_LIMIT} items per batch")
        batch = self.client.messages.batches.create(
            requests=[
                {"custom_id": str(item.id), "params": request_params(self.name, item)}
                for item in items
            ]
        )
        return str(batch.id)

    def batch_done(self, batch_id: str) -> bool:
        status = self.client.messages.batches.retrieve(batch_id).processing_status
        return bool(status == "ended")

    def batch_results(
        self, batch_id: str, log: Callable[[str], None] = lambda _: None
    ) -> dict[int, NewsLabel | None]:
        """Labels by announcement id. Failed requests come back as None."""
        found: dict[int, NewsLabel | None] = {}
        failed = 0
        for result in self.client.messages.batches.results(batch_id):
            label = None
            if result.result.type == "succeeded":
                self.usage.add(result.result.message)
                label = label_from_message(result.result.message)
            failed += label is None
            found[int(result.custom_id)] = label
        if failed:
            log(f"{failed} of {len(found)} announcements in batch {batch_id} got no label.")
        return found
