"""News labels on a real Postgres: rules for all, Claude (a fake client) for the material
announcements of liquid stocks, batches, the test set and the news score's inputs."""

import csv
import json
from datetime import date

from sqlalchemy import func, select

from app.data import store
from app.data.news import Announcement
from app.models import NewsBatch
from app.models import NewsLabel as NewsLabelRow
from app.news import job
from app.news.claude import ClaudeLabeller
from app.news.labels import RULES_LABELLER, DatedLabel, EventType, NewsItem
from tests.conftest import requires_db
from tests.test_alerts_db import empty_session as empty_session  # noqa: F401 - the fixture
from tests.test_backtest_db import _bar
from tests.test_news_labels import FakeClient, _message

pytestmark = requires_db

MODEL = "claude-opus-5-5"
ORDER = json.dumps({"event_type": "order_win", "sentiment": 2, "reason": "Large order."})


def _setup(s):
    # LIQUID trades ₹10 crore a day in 2025 (liquid), THIN ₹10 lakh (never labelled).
    store.save_bars(s, store.NSE_BARS, [_bar("LIQUID", date(2025, 3, 3), 1000)])
    store.save_bars(s, store.NSE_BARS, [_bar("THIN", date(2025, 3, 3), 0.1)])
    items = [
        Announcement(
            "LIQUID", date(2025, 3, 3), "Bagging/Receiving of orders/contracts",
            "Liquid Ltd has informed the Exchange about an ORDER worth Rs 900 crore from NHAI",
        ),
        Announcement(
            "LIQUID", date(2025, 3, 4), "Credit Rating",
            "Liquid Ltd has informed the Exchange about Credit Rating",  # nothing more to read
        ),
        Announcement(
            "LIQUID", date(2025, 3, 5), "ESOP/ESOS/ESPS",
            "Liquid Ltd has informed the Exchange about allotment of 1,000 shares under ESOP",
        ),
        Announcement(
            "LIQUID", date(2024, 6, 3), "Acquisition",  # 2024: not liquid that year
            "Liquid Ltd has informed the Exchange about Acquisition of a stake in Foo Pvt Ltd",
        ),
        Announcement(
            "THIN", date(2025, 3, 3), "Acquisition",
            "Thin Ltd has informed the Exchange about Acquisition of a stake in Bar Pvt Ltd",
        ),
    ]  # fmt: skip
    store.save_announcements(s, items, "test")
    s.commit()


def _labels(s, labeller):
    return s.scalar(
        select(func.count()).select_from(NewsLabelRow).where(NewsLabelRow.labeller == labeller)
    )


def test_rules_then_claude_for_material_liquid_news(empty_session):
    s = empty_session
    _setup(s)
    assert job.run_news(s, None) == 0  # no key: rules only
    assert _labels(s, RULES_LABELLER) == 5
    assert _labels(s, MODEL) == 0

    pending = job.pending_items(s, MODEL)
    assert [(i.symbol, i.day) for i in pending] == [("LIQUID", date(2025, 3, 3))]

    client = FakeClient({"ORDER": _message(ORDER)})
    labeller = ClaudeLabeller("key", MODEL, client=client)
    logged: list[str] = []
    assert job.run_news(s, labeller, log=logged.append) == 0
    assert len(client.requests) == 1
    assert _labels(s, MODEL) == 1
    assert "about US$" in logged[-1]
    # Stored once: a re-run sends nothing.
    assert job.run_news(s, labeller) == 0
    assert len(client.requests) == 1
    assert job.label_rules(s) == 0

    assert job.dated_labels(s, ["LIQUID"], MODEL) == {
        "LIQUID": [DatedLabel(date(2025, 3, 3), EventType.ORDER_WIN, 2)]
    }
    assert job.dated_labels(s, ["LIQUID"], MODEL, end=date(2025, 3, 2)) == {}


def test_failed_labels_are_retried_later(empty_session):
    s = empty_session
    _setup(s)
    broken = ClaudeLabeller("key", MODEL, client=FakeClient({"ORDER": _message("oops")}))
    assert job.run_news(s, broken) == 0
    assert _labels(s, MODEL) == 0
    assert len(job.pending_items(s, MODEL)) == 1


def test_too_many_for_one_by_one(empty_session, monkeypatch):
    s = empty_session
    _setup(s)
    monkeypatch.setattr(job, "SYNC_LIMIT", 0)
    labeller = ClaudeLabeller("key", MODEL, client=FakeClient())
    logged: list[str] = []
    assert job.run_news(s, labeller, log=logged.append) == 1
    assert "--batch" in logged[-1]


def test_batch_submit_and_collect(empty_session):
    s = empty_session
    _setup(s)
    client = FakeClient({"ORDER": _message(ORDER)})
    labeller = ClaudeLabeller("key", MODEL, client=client)
    assert job.run_news(s, labeller, batch=True) == 0
    batch = s.scalars(select(NewsBatch)).one()
    assert batch.items == 1 and batch.collected_at is None
    # Still running: nothing collected, nothing sent again.
    assert job.collect_batches(s, labeller) == (0, 1)
    assert job.run_news(s, labeller, batch=True) == 0
    assert len(client.messages.batches.created) == 2  # the item is still pending
    client.messages.batches.status = "ended"
    new, running = job.collect_batches(s, labeller)
    assert (new, running) == (1, 0)
    assert _labels(s, MODEL) == 1
    assert job.pending_items(s, MODEL) == []


def test_test_set_round_trip(empty_session, tmp_path):
    s = empty_session
    _setup(s)
    path = tmp_path / "testset.csv"
    assert job.export_test_set(s, path, size=10, since=date(2025, 1, 1)) == 1
    with path.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["symbol"] == "LIQUID" and rows[0]["event_type"] == ""
    rows[0]["event_type"], rows[0]["sentiment"] = "order_win", "+2"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=job.TEST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    labeller = ClaudeLabeller("key", MODEL, client=FakeClient({"ORDER": _message(ORDER)}))
    result = job.evaluate_test_set(s, path, labeller)
    assert (result.llm.count, result.llm.type_correct, result.llm.sentiment_error) == (1, 1, 0)
    # The free rules get the type right too, but call every item neutral.
    assert (result.rules.type_correct, result.rules.sentiment_error) == (1, 2)
    assert result.problems == []


def test_api_errors_are_a_message_not_a_crash(empty_session):
    import anthropic
    import httpx2

    s = empty_session
    _setup(s)
    error = anthropic.APIError(
        "Error code: 400",
        httpx2.Request("POST", "https://api.anthropic.com/v1/messages"),
        body={"type": "error", "error": {"message": "Your credit balance is too low."}},
    )

    def no_credit(**params):
        raise error

    client = FakeClient()
    client.messages.create = no_credit
    logged: list[str] = []
    labeller = ClaudeLabeller("key", MODEL, client=client)
    assert job.run_news(s, labeller, log=logged.append) == 1
    assert "News API error: Your credit balance is too low." in logged
    assert _labels(s, RULES_LABELLER) == 5  # the free labels are kept


class FakeHttp:
    """Answers like DeepSeek's chat API."""

    def __init__(self, status=200, content=ORDER):
        self.status, self.content, self.bodies = status, content, []

    def post(self, url, json, headers):
        import httpx

        self.bodies.append(json)
        assert url == "https://api.deepseek.com/chat/completions"
        assert headers["Authorization"] == "Bearer secret"
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "Insufficient Balance"}})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": self.content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 600, "completion_tokens": 40},
            },
        )


def test_deepseek_labels_the_same_way(empty_session):
    from app.news.deepseek import DeepSeekLabeller

    s = empty_session
    _setup(s)
    http = FakeHttp()
    labeller = DeepSeekLabeller("secret", client=http, pause=0)  # type: ignore[arg-type]
    logged: list[str] = []
    assert job.run_news(s, labeller, batch=True, log=logged.append) == 0
    assert "Batches are for Claude only" in logged[1]
    body = http.bodies[0]
    assert body["model"] == "deepseek-chat"
    assert body["response_format"] == {"type": "json_object"}
    assert "JSON" in body["messages"][0]["content"]
    assert _labels(s, "deepseek-chat") == 1
    assert "600 input and 40 output tokens" in logged[-1]

    bad = DeepSeekLabeller("secret", client=FakeHttp(content="not json"), pause=0)  # type: ignore[arg-type]
    item = NewsItem(1, "LIQUID", date(2025, 3, 3), None, "text")
    assert bad.label([item]) == [None]  # JSON mode, but not the schema: dropped

    broke = DeepSeekLabeller("secret", client=FakeHttp(status=402), pause=0)  # type: ignore[arg-type]
    broke.name = "deepseek-other"
    logged.clear()
    assert job.run_news(s, broke, log=logged.append) == 1
    assert "News API error: DeepSeek HTTP 402: Insufficient Balance" in logged


def test_settings_pick_the_labeller():
    from app.config import Settings
    from app.news.deepseek import DeepSeekLabeller

    assert job.make_labeller(Settings(anthropic_api_key="")) is None
    assert isinstance(job.make_labeller(Settings(anthropic_api_key="k")), ClaudeLabeller)
    deep = Settings(news_provider="deepseek", deepseek_api_key="k")
    assert isinstance(job.make_labeller(deep), DeepSeekLabeller)
    assert "JERON_DEEPSEEK_API_KEY" in job.missing_key(Settings(news_provider="deepseek"))


class FakeOllama:
    """Answers like Ollama Cloud's chat API."""

    def __init__(self, status=200, content=ORDER):
        self.status, self.content, self.bodies = status, content, []

    def post(self, url, json, headers):
        import httpx

        self.bodies.append(json)
        assert url == "https://ollama.com/api/chat"
        assert headers["Authorization"] == "Bearer secret"
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "unauthorized"})
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": self.content},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 550,
                "eval_count": 30,
            },
        )


def test_ollama_cloud_labels_the_same_way(empty_session):
    from app.news.ollama import OllamaLabeller

    s = empty_session
    _setup(s)
    http = FakeOllama()
    labeller = OllamaLabeller("secret", "gemma4:31b", "https://ollama.com", client=http, pause=0)  # type: ignore[arg-type]
    logged: list[str] = []
    assert job.run_news(s, labeller, log=logged.append) == 0
    body = http.bodies[0]
    assert body["format"]["required"] == ["event_type", "sentiment", "reason"]
    assert body["stream"] is False
    assert _labels(s, "gemma4:31b") == 1
    assert "550 input and 30 output tokens" in logged[-1]

    broke = OllamaLabeller("secret", "other:1b", client=FakeOllama(status=401), pause=0)  # type: ignore[arg-type]
    logged.clear()
    assert job.run_news(s, broke, log=logged.append) == 1
    assert "News API error: Ollama HTTP 401: unauthorized" in logged


def test_settings_pick_ollama():
    from app.config import Settings
    from app.news.ollama import OllamaLabeller

    cloud = Settings(news_provider="ollama", ollama_api_key="k")
    labeller = job.make_labeller(cloud)
    assert isinstance(labeller, OllamaLabeller) and labeller.name == "gemma4:31b"
    assert "JERON_OLLAMA_API_KEY" in job.missing_key(Settings(news_provider="ollama"))
