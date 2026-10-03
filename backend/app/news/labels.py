"""News labels: what kind of event an announcement is and whether it is good or bad news.

Two labellers. The rules read NSE's own subject line and are free, so every announcement
gets an event type. Routine filings (AGM notices, ESOP allotments, call schedules) stop
there with sentiment 0. Material ones (results, orders, ratings, resignations, general
updates...) also go to an LLM, which reads the text and returns the event type,
sentiment from -2 to +2 and a one-line reason as strict JSON. The LLM never sees or
produces prices, targets or stops.

The news score for a stock on day D adds up the labels of announcements made up to D,
each fading with age at a rate set by its event type.

Pure module: the database layer stores what this returns.
"""

import json
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# Change the prompt or the schema -> new version, so old labels stay comparable.
PROMPT_VERSION = "news-v1"
RULES_LABELLER = "rules"
REASON_LIMIT = 300


class EventType(StrEnum):
    RESULTS = "results"
    GUIDANCE = "guidance"
    ORDER_WIN = "order_win"
    REGULATORY_ACTION = "regulatory_action"
    PROMOTER_ACTIVITY = "promoter_activity"
    RATING_CHANGE = "rating_change"
    MANAGEMENT_CHANGE = "management_change"
    LITIGATION = "litigation"
    CORPORATE_ACTION = "corporate_action"
    OTHER = "other"


E = EventType
# NSE subject (lower case) -> (event type, material: worth an LLM read).
SUBJECT_RULES: dict[str, tuple[EventType, bool]] = {
    # Results.
    "financial results": (E.RESULTS, True),
    "financial results updates": (E.RESULTS, True),
    "outcome of board meeting": (E.RESULTS, True),
    "limited review report": (E.RESULTS, False),
    "clarification - financial results": (E.RESULTS, False),
    "reply to clarification- financial results": (E.RESULTS, False),
    "statement of deviation(s) or variation(s) under reg. 32": (E.RESULTS, False),
    "publish audited results": (E.RESULTS, False),
    "declaration for audit reports with unmodified opinion(s)": (E.RESULTS, False),
    # Guidance and business updates.
    "investor presentation": (E.GUIDANCE, True),
    "monthly business updates": (E.GUIDANCE, True),
    "analysts/institutional investor meet/con. call updates": (E.GUIDANCE, False),
    # Orders and agreements.
    "bagging/receiving of orders/contracts": (E.ORDER_WIN, True),
    "awarding of order(s)/contract(s)": (E.ORDER_WIN, True),
    "agreements": (E.ORDER_WIN, True),
    "memorandum of understanding/agreements": (E.ORDER_WIN, True),
    "arrangements for strategic, technical, manufacturing, or marketing tie up": (
        E.ORDER_WIN,
        True,
    ),
    # Regulators and the exchange.
    "action(s) taken or orders passed": (E.REGULATORY_ACTION, True),
    "action(s) initiated or orders passed": (E.REGULATORY_ACTION, True),
    "suspension of trading": (E.REGULATORY_ACTION, True),
    "revocation of suspension of securities": (E.REGULATORY_ACTION, True),
    "corporate insolvency resolution process": (E.REGULATORY_ACTION, True),
    "default": (E.REGULATORY_ACTION, True),
    "fraud/default/arrest": (E.REGULATORY_ACTION, True),
    "granting/withdrawal/surrender/cancellation/suspension of key licenses/ regulatory approvals": (
        E.REGULATORY_ACTION,
        True,
    ),
    # Promoters.
    "disclosure under sebi takeover regulations": (E.PROMOTER_ACTIVITY, True),
    "disc. under reg.30 of sebi (sast) reg.2011": (E.PROMOTER_ACTIVITY, True),
    "pledge": (E.PROMOTER_ACTIVITY, True),
    "open offer": (E.PROMOTER_ACTIVITY, True),
    "public announcement-open offer": (E.PROMOTER_ACTIVITY, True),
    "trading plan under pit": (E.PROMOTER_ACTIVITY, False),
    # Credit ratings.
    "credit rating": (E.RATING_CHANGE, True),
    "credit rating- new": (E.RATING_CHANGE, True),
    "credit rating- others": (E.RATING_CHANGE, True),
    "credit rating- revision": (E.RATING_CHANGE, True),
    # Management and auditors.
    "appointment": (E.MANAGEMENT_CHANGE, True),
    "resignation": (E.MANAGEMENT_CHANGE, True),
    "change in management": (E.MANAGEMENT_CHANGE, True),
    "change in auditors": (E.MANAGEMENT_CHANGE, True),
    "resignation of statutory auditor": (E.MANAGEMENT_CHANGE, True),
    "demise": (E.MANAGEMENT_CHANGE, True),
    "change in director(s)": (E.MANAGEMENT_CHANGE, False),
    "cessation": (E.MANAGEMENT_CHANGE, False),
    "retirement": (E.MANAGEMENT_CHANGE, False),
    "reappointment": (E.MANAGEMENT_CHANGE, False),
    "change in company secretary/compliance officer": (E.MANAGEMENT_CHANGE, False),
    # Litigation.
    "pendency of litigation(s)/dispute(s) or the outcome impacting the company": (
        E.LITIGATION,
        True,
    ),
    # Corporate actions and deals.
    "acquisition": (E.CORPORATE_ACTION, True),
    "amalgamation/merger": (E.CORPORATE_ACTION, True),
    "scheme of arrangement": (E.CORPORATE_ACTION, True),
    "restructuring": (E.CORPORATE_ACTION, True),
    "diversification/disinvestment": (E.CORPORATE_ACTION, True),
    "joint venture": (E.CORPORATE_ACTION, True),
    "buy back": (E.CORPORATE_ACTION, True),
    "buyback": (E.CORPORATE_ACTION, True),
    "bonus": (E.CORPORATE_ACTION, True),
    "dividend": (E.CORPORATE_ACTION, True),
    "issue of securities": (E.CORPORATE_ACTION, True),
    "qualified institutional placement": (E.CORPORATE_ACTION, True),
    "preferential issue": (E.CORPORATE_ACTION, True),
    "raising of funds": (E.CORPORATE_ACTION, True),
    "stock split": (E.CORPORATE_ACTION, True),
    "sale or disposal": (E.CORPORATE_ACTION, True),
    "public announcement - buyback of shares": (E.CORPORATE_ACTION, True),
    "post buyback public announcement": (E.CORPORATE_ACTION, False),
    "incorporation": (E.CORPORATE_ACTION, False),
    "daily buy-back of equity shares": (E.CORPORATE_ACTION, False),
    "dividend updates": (E.CORPORATE_ACTION, False),
    "date of payment of dividend": (E.CORPORATE_ACTION, False),
    "allotment of securities": (E.CORPORATE_ACTION, False),
    "esop/esos/esps": (E.CORPORATE_ACTION, False),
    "allotment of esop/esps": (E.CORPORATE_ACTION, False),
    "amendment to aoa/moa": (E.CORPORATE_ACTION, False),
    # Other news worth reading.
    "updates": (E.OTHER, True),
    "general updates": (E.OTHER, True),
    "press release": (E.OTHER, True),
    "press release (revised)": (E.OTHER, True),
    "capacity addition": (E.OTHER, True),
    "commencement of commercial production/operations": (E.OTHER, True),
    "clarification": (E.OTHER, True),
    "news clarification": (E.OTHER, True),
    "reply to clarification sought": (E.OTHER, True),
    "disclosure of material issue": (E.OTHER, True),
    "rumour verification - regulation 30(11)": (E.OTHER, True),
    "strikes/lockouts/disturbances": (E.OTHER, True),
    "product launch": (E.OTHER, True),
}


# Since 2023 NSE leaves some subjects out of the subject field and starts the text with
# them instead ("Board Meeting Intimation Waaree Renewable ... has informed").
TEXT_PREFIX_RULES: list[tuple[str, EventType, bool]] = [
    ("change in directors/", E.MANAGEMENT_CHANGE, True),
    ("board meeting intimation", E.RESULTS, False),  # the results calendar has these
    ("notice of shareholders", E.OTHER, False),
    ("analyst/investor meet", E.GUIDANCE, False),
    ("monitoring agency report", E.OTHER, False),
    ("alteration of capital", E.CORPORATE_ACTION, False),
    ("annual secretarial compliance", E.OTHER, False),
    ("sale or disposal", E.CORPORATE_ACTION, True),
    ("integrated filing- financial", E.RESULTS, True),
    ("integrated filing", E.OTHER, False),
    ("amalgamation or merger", E.CORPORATE_ACTION, True),
    ("options to purchase", E.CORPORATE_ACTION, False),
    ("pendency of any", E.LITIGATION, True),
    ("structural digital database", E.OTHER, False),
    ("isd for buyback", E.CORPORATE_ACTION, False),
    ("revised record date", E.OTHER, False),
]


def rule_label(subject: str | None, text: str = "") -> tuple[EventType, bool]:
    """(event type, material) from NSE's subject, or from the start of the text when
    the subject is missing. Old lines whose subject can't be found are material (only
    the text says what they are); unknown subjects are routine."""
    if subject and subject.strip():
        return SUBJECT_RULES.get(" ".join(subject.lower().split()), (E.OTHER, False))
    head = " ".join(text[:80].lower().split())
    for prefix, event_type, material in TEXT_PREFIX_RULES:
        if head.startswith(prefix):
            return event_type, material
    return E.OTHER, True


_BOILERPLATE = re.compile(
    r"^.*?has (?:informed|submitted to) the exchange,?\s*(?:about|regarding|that)?\s*", re.I | re.S
)
_HELD_ON = re.compile(r"\b(?:held|to be held) on [^.]*", re.I)
# Fewer characters than this left after the boilerplate: nothing for an LLM to read.
DETAIL_MIN = 12


def has_detail(subject: str | None, text: str) -> bool:
    """Whether the text says more than "X has informed the Exchange about <subject>"
    (the substance is then in the attached PDF, which Jeron doesn't read)."""
    rest = _BOILERPLATE.sub("", text, count=1)
    if subject:
        rest = re.sub(re.escape(subject), "", rest, flags=re.I)
    rest = _HELD_ON.sub("", rest)
    return len(rest.strip(" .,'\"-:")) >= DETAIL_MIN


def needs_llm(subject: str | None, text: str) -> bool:
    return rule_label(subject, text)[1] and has_detail(subject, text)


@dataclass(frozen=True)
class NewsItem:
    """One announcement to label."""

    id: int
    symbol: str
    day: date
    subject: str | None
    text: str
    company: str | None = None


class NewsLabel(BaseModel):
    """What the LLM must return. Every field required, nothing else allowed."""

    model_config = ConfigDict(extra="forbid")

    event_type: EventType
    sentiment: int = Field(ge=-2, le=2)
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def _short(cls, value: str) -> str:
        return " ".join(value.split())[:REASON_LIMIT]


# The JSON schema sent to the API (structured outputs). Written out rather than
# generated so it only uses what structured outputs accept (enums, no min/max).
LABEL_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "event_type": {"type": "string", "enum": [e.value for e in EventType]},
        "sentiment": {"type": "integer", "enum": [-2, -1, 0, 1, 2]},
        "reason": {"type": "string"},
    },
    "required": ["event_type", "sentiment", "reason"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You label company announcements filed with India's National Stock \
Exchange (NSE) for a stock-research tool.

For each announcement return:
- event_type, one of:
  results: financial results, board meetings approving results, results commentary.
  guidance: outlook, business or sales updates, investor presentations, capex plans.
  order_win: orders, contracts, agreements or MoUs won or signed.
  regulatory_action: actions or orders by SEBI, the exchange, tax or other regulators, \
suspensions, defaults, insolvency, fraud.
  promoter_activity: promoter buying, selling, pledging or releasing shares; takeover \
disclosures.
  rating_change: credit ratings assigned, upgraded, downgraded, reaffirmed or withdrawn.
  management_change: appointments, resignations or deaths of directors, the CEO, CFO or \
auditors.
  litigation: lawsuits, disputes, arbitration and their outcomes.
  corporate_action: acquisitions, mergers, demergers, buybacks, dividends, bonus issues, \
splits, fund raising.
  other: anything else.
- sentiment: the likely effect on the company's business and shareholders, as the text \
states it:
  -2 clearly bad (big loss, downgrade, default, regulator's penalty, auditor or CEO quits \
suddenly), -1 somewhat bad, 0 neutral, routine or unclear, +1 somewhat good, +2 clearly \
good (large order relative to the company, upgrade, strong results stated in the text).
  Most filings are routine notices whose details are in an attached PDF: if the text \
does not say whether the news is good or bad, use 0. Do not guess from the company's \
reputation.
- reason: one short sentence (under 25 words) saying why, from the text only.

Never mention share prices, price targets, stop-losses or whether to buy or sell."""


def user_prompt(item: NewsItem) -> str:
    company = f"{item.company} ({item.symbol})" if item.company else item.symbol
    return (
        f"Company: {company}\n"
        f"Date: {item.day:%d %b %Y}\n"
        f"NSE subject: {item.subject or 'not given'}\n"
        f"Text: {item.text}"
    )


def parse_label(text: str) -> NewsLabel | None:
    """The model's reply as a label; None when it isn't valid JSON for the schema."""
    try:
        return NewsLabel.model_validate(json.loads(text))
    except (ValueError, ValidationError):
        return None


# News score ------------------------------------------------------------------------

# Event type -> (weight, half-life in calendar days).
SCORE_WEIGHTS: dict[EventType, tuple[float, float]] = {
    E.RESULTS: (1.0, 30),
    E.GUIDANCE: (0.8, 30),
    E.ORDER_WIN: (0.6, 20),
    E.REGULATORY_ACTION: (1.0, 60),
    E.PROMOTER_ACTIVITY: (0.8, 30),
    E.RATING_CHANGE: (0.8, 45),
    E.MANAGEMENT_CHANGE: (0.6, 30),
    E.LITIGATION: (0.7, 60),
    E.CORPORATE_ACTION: (0.6, 30),
    E.OTHER: (0.3, 10),
}
# Labels older than this many half-lives are ignored.
SCORE_HORIZON_HALF_LIVES = 4
# Points per unit of weighted sentiment; +2 results today -> 50 + 25 = 75.
SCORE_SCALE = 12.5


@dataclass(frozen=True)
class DatedLabel:
    day: date  # the day NSE listed the announcement
    event_type: EventType
    sentiment: int


def news_score(labels: Iterable[DatedLabel], day: date) -> float:
    """0-100, 50 = no news or only neutral news. Only announcements made on or before
    `day` count, each fading with its event type's half-life."""
    total = 0.0
    for label in labels:
        age = (day - label.day).days
        weight, half_life = SCORE_WEIGHTS[label.event_type]
        if age < 0 or age > half_life * SCORE_HORIZON_HALF_LIVES or label.sentiment == 0:
            continue
        total += label.sentiment * weight * math.pow(0.5, age / half_life)
    return max(0.0, min(100.0, 50.0 + SCORE_SCALE * total))


# Accuracy on the hand-labelled test set ---------------------------------------------


@dataclass(frozen=True)
class Accuracy:
    count: int
    type_correct: int
    sentiment_error: float  # mean absolute error, -2..+2 scale
    direction_correct: int  # same sign (bad, neutral, good)
    per_type: dict[str, tuple[int, int]]  # true type -> (correct, total)

    @property
    def type_accuracy(self) -> float:
        return self.type_correct / self.count if self.count else 0.0

    @property
    def direction_accuracy(self) -> float:
        return self.direction_correct / self.count if self.count else 0.0


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


def accuracy(pairs: Sequence[tuple[NewsLabel, NewsLabel]]) -> Accuracy:
    """Compare (truth, predicted) pairs."""
    per_type: dict[str, list[int]] = {}
    type_correct = direction = 0
    error = 0
    for truth, predicted in pairs:
        hit = truth.event_type == predicted.event_type
        type_correct += hit
        direction += _sign(truth.sentiment) == _sign(predicted.sentiment)
        error += abs(truth.sentiment - predicted.sentiment)
        counts = per_type.setdefault(truth.event_type.value, [0, 0])
        counts[0] += hit
        counts[1] += 1
    return Accuracy(
        count=len(pairs),
        type_correct=type_correct,
        sentiment_error=error / len(pairs) if pairs else 0.0,
        direction_correct=direction,
        per_type={k: (v[0], v[1]) for k, v in sorted(per_type.items())},
    )
