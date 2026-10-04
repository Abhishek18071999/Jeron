"""Ollama Cloud as the news labeller: the same prompt and checks, through Ollama's chat
API with the reply constrained to the label's JSON schema (`format`).

Requests run a few at a time in parallel, like DeepSeek. The key comes from
`JERON_OLLAMA_API_KEY` in `.env` and is never logged.
"""

from typing import Any

from app.news.deepseek import DeepSeekLabeller
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
JSON_INSTRUCTIONS = "\n\nReply with one JSON object and nothing else."


class OllamaLabeller(DeepSeekLabeller):
    provider = "Ollama"
    path = "/api/chat"
    default_base_url = DEFAULT_BASE_URL

    def request_body(self, item: NewsItem) -> dict[str, Any]:
        return {
            "model": self.name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT + JSON_INSTRUCTIONS},
                {"role": "user", "content": user_prompt(item)},
            ],
            "format": LABEL_SCHEMA,
            "stream": False,
            "options": {"temperature": 0},
        }

    def read(self, data: dict[str, Any]) -> tuple[NewsLabel | None, int, int]:
        tokens = int(data.get("prompt_eval_count") or 0), int(data.get("eval_count") or 0)
        if data.get("done_reason") not in (None, "stop"):
            return None, *tokens
        content = (data.get("message") or {}).get("content") or ""
        return parse_label(content), *tokens
