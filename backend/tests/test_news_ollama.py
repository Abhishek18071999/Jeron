"""Ollama Cloud labeller without a network: groups of announcements per request, thinking
off, and the fallbacks when a reply is incomplete or the model refuses `think`."""

import json
from datetime import date

import httpx

from app.news.labels import EventType, NewsItem
from app.news.ollama import OllamaLabeller, parse_group


def _item(n: int) -> NewsItem:
    return NewsItem(n, f"STOCK{n}", date(2025, 3, 3), "Bagging of orders", f"Order number {n}")


def _label(**extra: object) -> dict[str, object]:
    return {"event_type": "order_win", "sentiment": 1, "reason": "Won an order.", **extra}


class FakeOllama:
    """Answers each request with the next reply in `replies` (a dict, or a status code)."""

    def __init__(self, *replies: object) -> None:
        self.replies, self.bodies = list(replies), []

    def post(self, url, json, headers):  # noqa: A002 - httpx's own name
        self.bodies.append(json)
        reply = self.replies.pop(0)
        if isinstance(reply, int):
            return httpx.Response(reply, json={"error": '"model" does not support thinking'})
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": _json(reply)},
                "done_reason": "stop",
                "prompt_eval_count": 600,
                "eval_count": 100,
            },
        )


def _json(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def _labeller(http: FakeOllama, group_size: int = 3) -> OllamaLabeller:
    return OllamaLabeller(
        "secret",
        "glm-5.3",
        client=http,
        pause=0,
        workers=1,
        group_size=group_size,  # type: ignore[arg-type]
    )


def test_one_request_per_group_with_thinking_off():
    http = FakeOllama(
        {"labels": [_label(id=1), _label(id=2, sentiment=0), _label(id=3)]},
        _label(event_type="results"),
    )
    labeller = _labeller(http)
    labels = labeller.label([_item(n) for n in range(1, 5)])

    assert [label.sentiment for label in labels] == [1, 0, 1, 1]  # type: ignore[union-attr]
    assert labels[3].event_type == EventType.RESULTS  # type: ignore[union-attr]
    first, last = http.bodies
    assert first["think"] is False and first["stream"] is False
    assert first["format"]["properties"]["labels"]["type"] == "array"
    prompt = first["messages"][1]["content"]
    assert "Announcement 1:" in prompt and "Announcement 3:" in prompt and "STOCK3" in prompt
    assert "Announcement 4:" not in prompt
    # A group of one is a plain single request.
    assert last["format"]["required"] == ["event_type", "sentiment", "reason"]
    assert labeller.usage.requests == 2 and labeller.usage.input_tokens == 1200
    assert labeller.save_every == 3


def test_missing_or_bad_entries_are_asked_one_at_a_time():
    http = FakeOllama(
        {"labels": [_label(id=1), _label(id=3, sentiment=9), _label(id=7)]},
        _label(sentiment=-1),  # announcement 2 alone
        "not json",  # announcement 3 alone: still nothing, retried on the next run
    )
    labels = _labeller(http).label([_item(n) for n in range(1, 4)])
    assert labels[0] and labels[0].sentiment == 1
    assert labels[1] and labels[1].sentiment == -1
    assert labels[2] is None
    assert "Announcement" not in http.bodies[1]["messages"][1]["content"]


def test_model_that_cannot_turn_thinking_off():
    group = {"labels": [_label(id=1), _label(id=2)]}
    http = FakeOllama(400, group, {"labels": []}, _label(), _label())
    labeller = _labeller(http, group_size=2)
    assert all(labeller.label([_item(1), _item(2)]))
    assert "think" not in http.bodies[1]
    assert labeller.no_thinking is False
    labeller.label([_item(3), _item(4)])
    assert all("think" not in body for body in http.bodies[1:])


def test_parse_group():
    good = json.dumps({"labels": [_label(id=2), _label(id=1, sentiment=-2)]})
    labels = parse_group(good, 2)
    assert labels[0] and labels[0].sentiment == -2
    assert labels[1] and labels[1].sentiment == 1
    duplicate = json.dumps({"labels": [_label(id=1), _label(id=1, sentiment=-2)]})
    assert parse_group(duplicate, 2)[0].sentiment == 1  # type: ignore[union-attr]
    assert parse_group(json.dumps({"labels": "x"}), 2) == [None, None]
    assert parse_group("[]", 1) == [None]
    assert parse_group(json.dumps({"labels": [_label(id=1, extra=1)]}), 1) == [None]
