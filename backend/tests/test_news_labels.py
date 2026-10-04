"""News labels: subject rules, the LLM's JSON, the news score and test-set accuracy.
Claude is replaced by a fake client: no API calls in tests."""

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.news.claude import ClaudeLabeller, Usage, request_params
from app.news.labels import (
    LABEL_SCHEMA,
    SYSTEM_PROMPT,
    DatedLabel,
    EventType,
    NewsItem,
    NewsLabel,
    accuracy,
    has_detail,
    needs_llm,
    news_score,
    parse_label,
    rule_label,
    user_prompt,
)

E = EventType
DAY = date(2026, 5, 4)


def test_rules_read_nse_subjects():
    assert rule_label("Credit Rating- Revision") == (E.RATING_CHANGE, True)
    assert rule_label("  bagging/receiving of  orders/contracts ") == (E.ORDER_WIN, True)
    assert rule_label("ESOP/ESOS/ESPS") == (E.CORPORATE_ACTION, False)
    assert rule_label("Shareholders meeting") == (E.OTHER, False)  # unknown: routine
    # No subject: the text's start says what it is (NSE's XBRL filings since 2023).
    text = "Board Meeting Intimation Waaree Limited has informed the Exchange about Board"
    assert rule_label(None, text) == (E.RESULTS, False)
    assert rule_label("", "Change in Directors/ Key Managerial Personnel UBL has") == (
        E.MANAGEMENT_CHANGE,
        True,
    )
    # Old lines whose subject can't be found: only the text can say.
    assert rule_label(None, "Infosys Limited has informed the Exchange that...") == (E.OTHER, True)


def test_detail_beyond_the_boilerplate():
    assert not has_detail(
        "Credit Rating", "Punjab National Bank has informed the Exchange about Credit Rating"
    )
    assert not has_detail(
        "Outcome of Board Meeting",
        "RBL Bank Limited has informed the Exchange regarding Outcome of Board Meeting held "
        "on April 11, 2026.",
    )
    assert has_detail(
        "Updates", "Mishra Dhatu Nigam Limited has informed the Exchange regarding 'Order Receipt'."
    )
    assert has_detail(
        "Dividend",
        "Bajaj Auto Limited has informed the Exchange that the Board declared an interim "
        "dividend of Rs 50 per share.",
    )
    assert not needs_llm(
        "Shareholders meeting", "X has informed the Exchange about an AGM on 5 May"
    )
    assert needs_llm(
        "Acquisition",
        "Tata Steel has informed the Exchange about Acquisition of equity stake in TSN Wires",
    )


def test_parse_label_accepts_only_the_schema():
    good = {"event_type": "order_win", "sentiment": 1, "reason": "  Won a  ₹500 cr order. "}
    label = parse_label(json.dumps(good))
    assert label == NewsLabel(event_type=E.ORDER_WIN, sentiment=1, reason="Won a ₹500 cr order.")
    assert parse_label("not json") is None
    assert parse_label(json.dumps({**good, "sentiment": 3})) is None
    assert parse_label(json.dumps({**good, "event_type": "buy"})) is None
    assert parse_label(json.dumps({**good, "target_price": 900})) is None  # nothing extra
    assert parse_label(json.dumps({"event_type": "other", "sentiment": 0})) is None
    assert parse_label(json.dumps({**good, "reason": ""})) is None


def test_schema_matches_the_model():
    assert LABEL_SCHEMA["required"] == ["event_type", "sentiment", "reason"]
    props = LABEL_SCHEMA["properties"]
    assert isinstance(props, dict)
    assert props["event_type"]["enum"] == [e.value for e in EventType]
    assert props["sentiment"]["enum"] == [-2, -1, 0, 1, 2]
    for word in ("target", "stop-loss"):
        assert word in SYSTEM_PROMPT  # forbidden, said so explicitly
    prompt = user_prompt(NewsItem(1, "TCS", DAY, None, "text", "Tata Consultancy Services"))
    assert "Tata Consultancy Services (TCS)" in prompt
    assert "NSE subject: not given" in prompt


def test_news_score_decays_and_ignores_the_future():
    assert news_score([], DAY) == 50
    good_results = DatedLabel(DAY, E.RESULTS, 2)
    assert news_score([good_results], DAY) == 75
    assert news_score([good_results], DAY + timedelta(days=30)) == pytest.approx(62.5)
    assert news_score([good_results], DAY + timedelta(days=121)) == 50  # past the horizon
    assert news_score([good_results], DAY - timedelta(days=1)) == 50  # not known yet
    bad = [DatedLabel(DAY, E.REGULATORY_ACTION, -2)] * 3
    assert news_score(bad, DAY) == 0  # clamped
    assert news_score([DatedLabel(DAY, E.OTHER, 0)], DAY) == 50


def test_accuracy_per_type():
    def lab(kind, sentiment):
        return NewsLabel(event_type=kind, sentiment=sentiment, reason="-")

    acc = accuracy(
        [
            (lab(E.RESULTS, 2), lab(E.RESULTS, 1)),
            (lab(E.RESULTS, -1), lab(E.OTHER, 0)),
            (lab(E.ORDER_WIN, 1), lab(E.ORDER_WIN, 1)),
        ]
    )
    assert (acc.count, acc.type_correct, acc.direction_correct) == (3, 2, 2)
    assert acc.sentiment_error == pytest.approx(2 / 3)
    assert acc.per_type == {"order_win": (1, 1), "results": (1, 2)}
    assert accuracy([]).type_accuracy == 0


# The Claude labeller, against a fake client ----------------------------------------


def _message(text, stop_reason="end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=500, output_tokens=100, cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )  # fmt: skip


class FakeBatches:
    def __init__(self, client):
        self.client, self.created, self.status = client, [], "in_progress"

    def create(self, requests):
        self.created.append(requests)
        return SimpleNamespace(id=f"msgbatch_{len(self.created)}")

    def retrieve(self, batch_id):
        return SimpleNamespace(processing_status=self.status)

    def results(self, batch_id):
        for request in self.created[int(batch_id.split("_")[1]) - 1]:
            message = self.client.reply(request["params"])
            result = (
                SimpleNamespace(type="succeeded", message=message)
                if message
                else SimpleNamespace(type="errored")
            )
            yield SimpleNamespace(custom_id=request["custom_id"], result=result)


class FakeClient:
    """Answers like the Messages API. `replies` maps a word in the text to the reply."""

    def __init__(self, replies=None):
        self.replies = replies or {}
        self.requests = []
        self.messages = SimpleNamespace(create=self.create, batches=FakeBatches(self))

    def reply(self, params):
        text = params["messages"][0]["content"]
        for word, reply in self.replies.items():
            if word in text:
                return reply
        return _message(json.dumps({"event_type": "other", "sentiment": 0, "reason": "Routine."}))

    def create(self, **params):
        self.requests.append(params)
        return self.reply(params)


def test_request_uses_structured_outputs_and_caches_the_prompt():
    item = NewsItem(1, "TCS", DAY, "Updates", "text")
    params = request_params("claude-opus-5-5", item)
    assert params["output_config"] == {
        "format": {"type": "json_schema", "schema": LABEL_SCHEMA},
        "effort": "low",
    }
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "thinking" not in params and "temperature" not in params
    # Haiku 4.5 takes no effort setting.
    assert "effort" not in request_params("claude-haiku-4-5", item)["output_config"]


def test_claude_labeller_parses_and_rejects():
    order = json.dumps({"event_type": "order_win", "sentiment": 2, "reason": "Big order."})
    client = FakeClient(
        {
            "ORDER": _message(order),
            "REFUSE": _message("", stop_reason="refusal"),
            "CUT": _message('{"event_type": "ord', stop_reason="max_tokens"),
            "BAD": _message("I think this is good news"),
        }
    )
    labeller = ClaudeLabeller("key", "claude-opus-5-5", client=client)
    items = [NewsItem(i, "X", DAY, None, word) for i, word in enumerate(
        ["ORDER", "REFUSE", "CUT", "BAD", "plain"]
    )]  # fmt: skip
    labels = labeller.label(items)
    assert labels[0] == NewsLabel(event_type=E.ORDER_WIN, sentiment=2, reason="Big order.")
    assert labels[1:4] == [None, None, None]
    assert labels[4] is not None and labels[4].sentiment == 0
    assert labeller.usage.requests == 5
    # 5 x (500 in at $4/M + 100 out at $20/M) = $0.02
    assert labeller.usage.cost("claude-opus-5-5") == pytest.approx(0.02)
    assert labeller.usage.cost("claude-opus-5-5", batch=True) == pytest.approx(0.01)
    assert Usage().cost("some-other-model") is None


def test_batches_round_trip():
    client = FakeClient({"BAD": _message("nope")})
    labeller = ClaudeLabeller("key", "claude-sonnet-5-5", client=client)
    items = [NewsItem(7, "X", DAY, None, "fine"), NewsItem(9, "Y", DAY, None, "BAD")]
    batch_id = labeller.submit_batch(items)
    assert not labeller.batch_done(batch_id)
    client.messages.batches.status = "ended"
    assert labeller.batch_done(batch_id)
    logged = []
    found = labeller.batch_results(batch_id, log=logged.append)
    assert set(found) == {7, 9} and found[9] is None and found[7] is not None
    assert "1 of 2" in logged[0]
