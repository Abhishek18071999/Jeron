"""Google Gemini as the news labeller: the same prompt and checks, through Gemini's
OpenAI-compatible chat API in JSON mode (the DeepSeek labeller with another address).

Thinking is turned down to save tokens; a model that refuses the setting is asked again
without it. The free tier allows only a few requests a minute, so requests run two at a
time and a 429 waits longer before the retry. The key comes from `JERON_GEMINI_API_KEY`
in `.env` (aistudio.google.com/apikey) and is never logged.
"""

from typing import Any

import httpx

from app.news.deepseek import DeepSeekLabeller, LabellerError
from app.news.labels import NewsItem

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemini-2.5-flash"
# Room for any thinking the model still does before the label.
MAX_TOKENS = 4096
WORKERS = 2


class GeminiLabeller(DeepSeekLabeller):
    provider = "Gemini"
    default_base_url = DEFAULT_BASE_URL

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str | None = None,
        client: httpx.Client | None = None,
        workers: int = WORKERS,
        pause: float = 5.0,
    ) -> None:
        super().__init__(api_key, model, base_url, client, workers, pause)
        # Switched off again only if the model refuses the setting.
        self.low_reasoning = True

    def request_body(self, item: NewsItem) -> dict[str, Any]:
        body = super().request_body(item)
        body["max_tokens"] = MAX_TOKENS
        if self.low_reasoning:
            body["reasoning_effort"] = "low"
        return body

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            return super()._post(body)
        except LabellerError as exc:
            text = str(exc).lower()
            if "reasoning_effort" not in body or not ("reasoning" in text or "thinking" in text):
                raise
            self.low_reasoning = False
            return super()._post({k: v for k, v in body.items() if k != "reasoning_effort"})
