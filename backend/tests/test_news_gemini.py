"""Gemini labeller without a network: the OpenAI-compatible address, thinking turned down
(and dropped when the model refuses it), Gemini's list-shaped errors, and `.env`."""

import json
from datetime import date

import httpx
import pytest

from app.config import Settings
from app.news import job
from app.news.deepseek import LabellerError
from app.news.gemini import GeminiLabeller
from app.news.labels import EventType, NewsItem

ITEM = NewsItem(1, "STOCK1", date(2025, 3, 3), "Bagging of orders", "Order worth Rs 500 crore")
LABEL = {"event_type": "order_win", "sentiment": 1, "reason": "Won an order."}


class FakeGemini:
    """Answers each request with the next reply: a label dict, or (status, error body)."""

    def __init__(self, *replies: object) -> None:
        self.replies, self.bodies, self.urls = list(replies), [], []

    def post(self, url, json, headers):  # noqa: A002 - httpx's own name
        self.urls.append(url)
        self.bodies.append(json)
        reply = self.replies.pop(0)
        if isinstance(reply, tuple):
            return httpx.Response(reply[0], json=reply[1])
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": _dumps(reply)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 700, "completion_tokens": 40},
            },
        )


def _dumps(value: object) -> str:
    return json.dumps(value)


def test_labels_through_the_openai_compatible_api():
    http = FakeGemini(LABEL)
    labeller = GeminiLabeller("secret", client=http, pause=0)  # type: ignore[arg-type]
    [label] = labeller.label([ITEM])
    assert label is not None and label.event_type == EventType.ORDER_WIN
    assert http.urls == ["https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"]
    body = http.bodies[0]
    assert body["model"] == "gemini-3.8-flash"
    assert body["response_format"] == {"type": "json_object"}
    assert body["reasoning_effort"] == "low"
    assert labeller.usage.requests == 1 and labeller.usage.output_tokens == 40


def test_a_model_that_refuses_the_reasoning_setting_is_asked_without_it():
    refused = (400, [{"error": {"message": "reasoning_effort is not supported by this model"}}])
    http = FakeGemini(refused, LABEL, LABEL)
    labeller = GeminiLabeller("secret", "gemini-2.0-flash", client=http, pause=0)  # type: ignore[arg-type]
    assert labeller.label([ITEM])[0] is not None
    assert "reasoning_effort" not in http.bodies[1]
    labeller.label([ITEM])
    assert "reasoning_effort" not in http.bodies[2]


def test_gemini_errors_read_in_its_own_words():
    bad_key = (400, [{"error": {"code": 400, "message": "API key not valid."}}])
    labeller = GeminiLabeller("secret", client=FakeGemini(bad_key), pause=0)  # type: ignore[arg-type]
    with pytest.raises(LabellerError, match="Gemini HTTP 400: API key not valid."):
        labeller.label([ITEM])


def test_env_picks_gemini():
    settings = Settings(
        news_provider="gemini", gemini_api_key="secret", gemini_model="gemini-2.5-flash-lite"
    )
    labeller = job.make_labeller(settings)
    assert isinstance(labeller, GeminiLabeller) and labeller.name == "gemini-2.5-flash-lite"
    assert settings.news_ready and job.labeller_name(settings) == "gemini-2.5-flash-lite"
    off = Settings(news_provider="gemini", gemini_api_key="")
    assert job.make_labeller(off) is None and not off.news_ready
    assert "JERON_GEMINI_API_KEY" in job.missing_key(off)
