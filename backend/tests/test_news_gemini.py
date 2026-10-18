"""Gemini labeller without a network: the OpenAI-compatible address, groups of
announcements per request, requests spaced for the free tier, 429s waited out, thinking
turned down (and dropped when the model refuses it), and `.env`."""

import json
from datetime import date

import httpx
import pytest

from app.config import Settings
from app.news import job
from app.news.deepseek import LabellerError
from app.news.gemini import GeminiLabeller, daily_quota, retry_delay
from app.news.labels import EventType, NewsItem

LABEL = {"event_type": "order_win", "sentiment": 1, "reason": "Won an order."}
RATE_LIMITED = (
    429,
    [
        {
            "error": {
                "code": 429,
                "message": "You exceeded your current quota. * Quota exceeded for metric: "
                "generativelanguage.googleapis.com/generate_content_free_tier_requests, "
                "limit: 5, model: gemini-3.8-flash\nPlease retry in 1.717150342s.",
                "details": [
                    {
                        "violations": [
                            {"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}
                        ]
                    },
                    {"retryDelay": "1s"},
                ],
            }
        }
    ],
)


def _item(n: int) -> NewsItem:
    return NewsItem(n, f"STOCK{n}", date(2025, 3, 3), "Bagging of orders", f"Order number {n}")


class FakeGemini:
    """Answers each request with the next reply: a dict to send as the content, or
    (status, error body)."""

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


class Clock:
    """A clock that `sleep` moves forward, recording each wait."""

    def __init__(self) -> None:
        self.now, self.waits = 0.0, []

    def sleep(self, seconds: float) -> None:
        self.waits.append(round(seconds, 2))
        self.now += seconds


def _labeller(http: FakeGemini, clock: Clock, **kwargs) -> GeminiLabeller:
    return GeminiLabeller(
        "secret",
        client=http,  # type: ignore[arg-type]
        sleep=clock.sleep,
        clock=lambda: clock.now,
        **kwargs,
    )


def test_labels_a_group_per_request_through_the_openai_compatible_api():
    http = FakeGemini({"labels": [{"id": 1, **LABEL}, {"id": 2, **LABEL, "sentiment": 0}]})
    labeller = _labeller(http, Clock())
    labels = labeller.label([_item(1), _item(2)])
    assert [label.sentiment for label in labels if label] == [1, 0]
    assert labels[0] and labels[0].event_type == EventType.ORDER_WIN
    assert http.urls == ["https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"]
    body = http.bodies[0]
    assert body["model"] == "gemini-3.8-flash"
    assert body["response_format"] == {"type": "json_object"}
    assert body["reasoning_effort"] == "low"
    assert "Announcement 2:" in body["messages"][1]["content"]
    assert labeller.usage.requests == 1 and labeller.usage.output_tokens == 40


def test_requests_are_spaced_for_the_free_tier():
    clock = Clock()
    http = FakeGemini(LABEL, LABEL, LABEL)
    labeller = _labeller(http, clock, group_size=1)
    assert all(labeller.label([_item(1), _item(2), _item(3)]))
    assert clock.waits == [12.0, 12.0]  # 5 a minute: the first at once, then every 12 s


def test_a_rate_limit_waits_the_delay_google_names_and_asks_again():
    clock = Clock()
    http = FakeGemini(RATE_LIMITED, RATE_LIMITED, LABEL)
    labeller = _labeller(http, clock, requests_per_minute=600)
    assert labeller.label([_item(1)])[0] is not None
    assert len(http.bodies) == 3
    assert 2.72 in clock.waits  # 1.7 s named, plus a second


def test_a_used_up_daily_quota_stops_the_run_and_says_so():
    per_day = (429, [{"error": {"message": "Quota exceeded: GenerateRequestsPerDayPerProject"}}])
    labeller = _labeller(FakeGemini(per_day), Clock())
    with pytest.raises(LabellerError, match="daily quota is used up"):
        labeller.label([_item(1)])


def test_retry_delay_and_daily_quota_are_read_from_the_error():
    text = json.dumps(RATE_LIMITED[1])
    assert retry_delay(text) == pytest.approx(1.717150342)
    assert retry_delay('{"retryDelay": "30s"}') == 30
    assert retry_delay("no delay") is None
    assert not daily_quota(text) and daily_quota("GenerateRequestsPerDayPerProject")


def test_a_model_that_refuses_the_reasoning_setting_is_asked_without_it():
    refused = (400, [{"error": {"message": "reasoning_effort is not supported by this model"}}])
    http = FakeGemini(refused, LABEL, LABEL)
    labeller = _labeller(http, Clock(), group_size=1)
    assert labeller.label([_item(1)])[0] is not None
    assert "reasoning_effort" not in http.bodies[1]
    labeller.label([_item(2)])
    assert "reasoning_effort" not in http.bodies[2]


def test_gemini_errors_read_in_its_own_words():
    bad_key = (400, [{"error": {"code": 400, "message": "API key not valid."}}])
    labeller = _labeller(FakeGemini(bad_key), Clock())
    with pytest.raises(LabellerError, match="Gemini HTTP 400: API key not valid."):
        labeller.label([_item(1)])


def test_env_picks_gemini():
    settings = Settings(
        news_provider="gemini",
        gemini_api_key="secret",
        gemini_model="gemini-3.8-flash",
        gemini_requests_per_minute=30,
    )
    labeller = job.make_labeller(settings)
    assert isinstance(labeller, GeminiLabeller) and labeller.name == "gemini-3.8-flash"
    assert labeller.spacing == 2.0
    assert settings.news_ready and job.labeller_name(settings) == "gemini-3.8-flash"
    off = Settings(news_provider="gemini", gemini_api_key="")
    assert job.make_labeller(off) is None and not off.news_ready
    assert "JERON_GEMINI_API_KEY" in job.missing_key(off)
