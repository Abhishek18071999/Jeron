"""Google Gemini as the news labeller: the same prompt and checks, through Gemini's
OpenAI-compatible chat API in JSON mode.

Gemini's free tier allows only a few requests a minute (5 for gemini-3.8-flash) and a
daily number, so each request carries several announcements, as with Ollama (the long
instructions are sent once per group), and requests are spaced to stay under
`JERON_GEMINI_REQUESTS_PER_MINUTE`. A 429 waits the delay Google names and asks again;
a used-up daily quota stops the run with that said. Announcements a group reply leaves
out or gets wrong are asked again one at a time. Thinking is turned down to save
tokens; a model that refuses the setting is asked again without it. The key comes from
`JERON_GEMINI_API_KEY` in `.env` (aistudio.google.com/apikey) and is never logged.
"""

import re
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

import httpx

from app.news.deepseek import JSON_INSTRUCTIONS, DeepSeekLabeller, LabellerError, _error_text
from app.news.labels import SYSTEM_PROMPT, NewsItem, NewsLabel, user_prompt
from app.news.ollama import GROUP_INSTRUCTIONS, group_prompt, parse_group

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemini-3.8-flash"
REQUESTS_PER_MINUTE = 5
GROUP_SIZE = 10
# Room for any thinking the model still does before the labels.
MAX_TOKENS = 8192
# 429s to wait out before giving up on one request.
RATE_LIMIT_RETRIES = 8
RETRY_STATUSES = frozenset({500, 502, 503, 504})
RETRIES = 4

Result = tuple[list[NewsLabel | None], int, int]


def retry_delay(text: str) -> float | None:
    """Seconds Google asks to wait, from "Please retry in 1.7s" or "retryDelay": "2s"."""
    found = re.search(r"retry in ([\d.]+)\s*s", text, re.I) or re.search(
        r'"retryDelay":\s*"([\d.]+)s"', text
    )
    return float(found.group(1)) if found else None


def daily_quota(text: str) -> bool:
    """The 429 is the day's quota, which waiting a minute won't bring back."""
    return bool(re.search(r"per ?day", text, re.I))


class GeminiLabeller(DeepSeekLabeller):
    provider = "Gemini"
    default_base_url = DEFAULT_BASE_URL

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str | None = None,
        client: httpx.Client | None = None,
        workers: int = 1,
        pause: float = 5.0,
        requests_per_minute: float = REQUESTS_PER_MINUTE,
        group_size: int = GROUP_SIZE,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(api_key, model, base_url, client, workers, pause)
        self.group_size = max(1, group_size)
        self.save_every = self.group_size * self.workers
        self.spacing = 60.0 / requests_per_minute if requests_per_minute > 0 else 0.0
        self.sleep, self.clock = sleep, clock
        self._next_at = 0.0
        self._lock = threading.Lock()
        # Switched off again only if the model refuses the setting.
        self.low_reasoning = True

    def _body(self, system: str, user: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": MAX_TOKENS,
            "temperature": 0,
            "stream": False,
        }
        if self.low_reasoning:
            body["reasoning_effort"] = "low"
        return body

    def request_body(self, item: NewsItem) -> dict[str, Any]:
        return self._body(SYSTEM_PROMPT + JSON_INSTRUCTIONS, user_prompt(item))

    def group_body(self, items: Sequence[NewsItem]) -> dict[str, Any]:
        return self._body(SYSTEM_PROMPT + GROUP_INSTRUCTIONS, group_prompt(items))

    def _wait_turn(self) -> None:
        """Space requests to stay under the per-minute limit."""
        with self._lock:
            now = self.clock()
            start = max(now, self._next_at)
            self._next_at = start + self.spacing
        if start > now:
            self.sleep(start - now)

    def _send(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        limited = failed = 0
        while True:
            self._wait_turn()
            try:
                response = self.client.post(self.url, json=body, headers=headers)
            except httpx.TransportError as exc:
                failed += 1
                if failed >= RETRIES:
                    raise LabellerError(f"Gemini could not be reached: {exc}") from exc
                self.sleep(self.pause * 2**failed)
                continue
            if response.status_code == 200:
                data: dict[str, Any] = response.json()
                return data
            if response.status_code == 429:
                if daily_quota(response.text):
                    raise LabellerError(
                        "Gemini's daily quota is used up; run the same command again "
                        f"tomorrow. ({_error_text(self.provider, response)})"
                    )
                limited += 1
                if limited > RATE_LIMIT_RETRIES:
                    raise LabellerError(_error_text(self.provider, response))
                self.sleep((retry_delay(response.text) or self.spacing or self.pause) + 1)
                continue
            failed += 1
            if response.status_code not in RETRY_STATUSES or failed >= RETRIES:
                raise LabellerError(_error_text(self.provider, response))
            self.sleep(self.pause * 2**failed)

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._send(body)
        except LabellerError as exc:
            text = str(exc).lower()
            if "reasoning_effort" not in body or not ("reasoning" in text or "thinking" in text):
                raise
            self.low_reasoning = False
            return self._send({k: v for k, v in body.items() if k != "reasoning_effort"})

    def _content(self, data: dict[str, Any]) -> tuple[str | None, int, int]:
        usage = data.get("usage") or {}
        tokens = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
        choice = (data.get("choices") or [{}])[0]
        if choice.get("finish_reason") not in (None, "stop"):
            return None, *tokens
        return (choice.get("message") or {}).get("content") or "", *tokens

    def _group(self, items: Sequence[NewsItem]) -> Result:
        if len(items) == 1:
            label, input_tokens, output_tokens = self._one(items[0])
            return [label], input_tokens, output_tokens
        content, input_tokens, output_tokens = self._content(self._post(self.group_body(items)))
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
        labels: list[NewsLabel | None] = []
        for i in range(0, len(items), self.group_size):
            group_labels, input_tokens, output_tokens = self._group(items[i : i + self.group_size])
            self.usage.requests += 1
            self.usage.input_tokens += input_tokens
            self.usage.output_tokens += output_tokens
            labels.extend(group_labels)
        return labels
