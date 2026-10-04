"""DeepSeek as the news labeller: the same prompt and checks as Claude, through DeepSeek's
OpenAI-style chat API in JSON mode.

DeepSeek has no batch API here, so requests run a few at a time in parallel. JSON mode
guarantees JSON but not the schema, so every reply is checked against `NewsLabel` and
anything else is dropped (and retried on the next run). The key comes from
`JERON_DEEPSEEK_API_KEY` in `.env` and is never logged.
"""

import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from app.news.claude import Usage
from app.news.labels import SYSTEM_PROMPT, NewsItem, NewsLabel, parse_label, user_prompt

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
MAX_TOKENS = 300
WORKERS = 8
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
RETRIES = 4

# JSON mode needs the word "json" and an example of the output in the prompt.
JSON_INSTRUCTIONS = """

Reply with one JSON object and nothing else, in exactly this shape:
{"event_type": "order_win", "sentiment": 1, "reason": "Won a large order from NHAI."}"""


class LabellerError(RuntimeError):
    """The news API refused the request (bad key, no balance...) after retries."""


class DeepSeekLabeller:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.Client | None = None,
        workers: int = WORKERS,
        pause: float = 2.0,
    ) -> None:
        self.client = client or httpx.Client(timeout=60)
        self.api_key = api_key
        self.name = model
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.workers = workers
        self.pause = pause
        self.usage = Usage()

    def request_body(self, item: NewsItem) -> dict[str, Any]:
        return {
            "model": self.name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT + JSON_INSTRUCTIONS},
                {"role": "user", "content": user_prompt(item)},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": MAX_TOKENS,
            "temperature": 0,
            "stream": False,
        }

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        for attempt in range(RETRIES):
            try:
                response = self.client.post(self.url, json=body, headers=headers)
            except httpx.TransportError as exc:
                if attempt == RETRIES - 1:
                    raise LabellerError(f"DeepSeek could not be reached: {exc}") from exc
            else:
                if response.status_code == 200:
                    data: dict[str, Any] = response.json()
                    return data
                if response.status_code not in RETRY_STATUSES or attempt == RETRIES - 1:
                    raise LabellerError(_error_text(response))
            time.sleep(self.pause * 2**attempt)
        raise LabellerError("DeepSeek did not answer")  # not reached

    def _one(self, item: NewsItem) -> tuple[NewsLabel | None, dict[str, Any]]:
        data = self._post(self.request_body(item))
        choice = (data.get("choices") or [{}])[0]
        if choice.get("finish_reason") not in (None, "stop"):
            return None, data
        content = (choice.get("message") or {}).get("content") or ""
        return parse_label(content), data

    def label(self, items: Sequence[NewsItem]) -> list[NewsLabel | None]:
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            results = list(pool.map(self._one, items))
        for _, data in results:
            usage = data.get("usage") or {}
            self.usage.requests += 1
            self.usage.input_tokens += int(usage.get("prompt_tokens") or 0)
            self.usage.output_tokens += int(usage.get("completion_tokens") or 0)
        return [label for label, _ in results]


def _error_text(response: httpx.Response) -> str:
    """DeepSeek's own words ("Insufficient Balance", "Authentication Fails")."""
    try:
        error = response.json().get("error") or {}
        message = error.get("message") if isinstance(error, dict) else None
    except ValueError:
        message = None
    return f"DeepSeek HTTP {response.status_code}: {message or response.text[:200]}"
