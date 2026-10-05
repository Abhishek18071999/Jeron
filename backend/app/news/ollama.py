"""Ollama Cloud as the news labeller: the same prompt and checks, through Ollama's chat
API with the reply constrained to the label's JSON schema (`format`).

To spend fewer tokens (Ollama Cloud has a daily limit), each request carries several
announcements, so the long instructions are sent once per group rather than once per
announcement, and thinking is switched off (a thinking model otherwise writes several
times more tokens than the label itself). Announcements a group reply leaves out or gets
wrong are asked again one at a time. Groups run a few at a time in parallel. The key
comes from `JERON_OLLAMA_API_KEY` in `.env` and is never logged.
"""

import json
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pydantic import ValidationError

from app.news.deepseek import DeepSeekLabeller, LabellerError
from app.news.labels import (
    LABEL_SCHEMA,
    SYSTEM_PROMPT,
    NewsItem,
    NewsLabel,
    parse_label,
    user_prompt,
)

DEFAULT_BASE_URL = "https://ollama.com"
DEFAULT_MODEL = "gemma4:31b"
GROUP_SIZE = 10
JSON_INSTRUCTIONS = "\n\nReply with one JSON object and nothing else."
GROUP_INSTRUCTIONS = """

You get several announcements, numbered. Label each one on its own, from its own text.
Reply with one JSON object and nothing else: {"labels": [...]}, one entry per
announcement, each with its number as "id"."""

_LABEL_PROPERTIES: dict[str, Any] = LABEL_SCHEMA["properties"]  # type: ignore[assignment]
GROUP_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "labels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, **_LABEL_PROPERTIES},
                "required": ["id", "event_type", "sentiment", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["labels"],
    "additionalProperties": False,
}

Result = tuple[list[NewsLabel | None], int, int]


def group_prompt(items: Sequence[NewsItem]) -> str:
    return "\n\n".join(f"Announcement {n}:\n{user_prompt(item)}" for n, item in enumerate(items, 1))


def parse_group(text: str, size: int) -> list[NewsLabel | None]:
    """One label per announcement, in order; None where the reply has no valid one."""
    found: list[NewsLabel | None] = [None] * size
    try:
        entries = json.loads(text)["labels"]
    except (ValueError, KeyError, TypeError):
        return found
    if not isinstance(entries, list):
        return found
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        number = entry.pop("id", None)
        if not isinstance(number, int) or not 1 <= number <= size or found[number - 1]:
            continue
        try:
            found[number - 1] = NewsLabel.model_validate(entry)
        except ValidationError:
            continue
    return found


class OllamaLabeller(DeepSeekLabeller):
    provider = "Ollama"
    path = "/api/chat"
    default_base_url = DEFAULT_BASE_URL

    def __init__(self, *args: Any, group_size: int = GROUP_SIZE, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.group_size = max(1, group_size)
        # Enough announcements per save for every worker to have a group.
        self.save_every = self.group_size * self.workers
        # Switched on again only if the model refuses the setting.
        self.no_thinking = True

    def _body(self, system: str, user: str, schema: dict[str, object]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": schema,
            "stream": False,
            "options": {"temperature": 0},
        }
        if self.no_thinking:
            body["think"] = False
        return body

    def request_body(self, item: NewsItem) -> dict[str, Any]:
        return self._body(SYSTEM_PROMPT + JSON_INSTRUCTIONS, user_prompt(item), LABEL_SCHEMA)

    def group_body(self, items: Sequence[NewsItem]) -> dict[str, Any]:
        return self._body(SYSTEM_PROMPT + GROUP_INSTRUCTIONS, group_prompt(items), GROUP_SCHEMA)

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            return super()._post(body)
        except LabellerError as exc:
            # A model that can't turn thinking off says so; ask again without the setting.
            if "think" not in body or "think" not in str(exc).lower():
                raise
            self.no_thinking = False
            return super()._post({k: v for k, v in body.items() if k != "think"})

    def _reply(self, data: dict[str, Any]) -> tuple[str | None, int, int]:
        tokens = int(data.get("prompt_eval_count") or 0), int(data.get("eval_count") or 0)
        if data.get("done_reason") not in (None, "stop"):
            return None, *tokens
        return (data.get("message") or {}).get("content") or "", *tokens

    def read(self, data: dict[str, Any]) -> tuple[NewsLabel | None, int, int]:
        content, input_tokens, output_tokens = self._reply(data)
        return (parse_label(content) if content else None), input_tokens, output_tokens

    def _group(self, items: Sequence[NewsItem]) -> Result:
        if len(items) == 1:
            label, input_tokens, output_tokens = self._one(items[0])
            return [label], input_tokens, output_tokens
        content, input_tokens, output_tokens = self._reply(self._post(self.group_body(items)))
        labels: list[NewsLabel | None] = (
            parse_group(content, len(items)) if content else [None] * len(items)
        )
        for n, item in enumerate(items):
            if labels[n] is None:
                labels[n], more_in, more_out = self._one(item)
                input_tokens += more_in
                output_tokens += more_out
        return labels, input_tokens, output_tokens

    def label(self, items: Sequence[NewsItem]) -> list[NewsLabel | None]:
        groups = [items[i : i + self.group_size] for i in range(0, len(items), self.group_size)]
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            results = list(pool.map(self._group, groups))
        labels: list[NewsLabel | None] = []
        for group_labels, input_tokens, output_tokens in results:
            self.usage.requests += 1
            self.usage.input_tokens += input_tokens
            self.usage.output_tokens += output_tokens
            labels.extend(group_labels)
        return labels
