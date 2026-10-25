"""Explain a stock from Jeron's own numbers, optionally worded by the LLM, and compare a
few side by side (docs/plans/explain-v1.md, decision 0016). Read-only except for the
stored narration: nothing here places, sizes or changes an order."""

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.data import store
from app.db import get_session
from app.explain.facts import Brief, Fact
from app.explain.narrate import MAX_QUESTION_CHARS, PROMPT_VERSION
from app.explain.service import NarrationRefusedError, explain, latest_narration, narrate
from app.explain.writers import make_writer
from app.models import Explanation
from app.news.job import budget
from app.settings_store import effective_settings

router = APIRouter(tags=["explain"])
SessionDep = Annotated[Session, Depends(get_session)]
MAX_COMPARE = 3


class FactOut(BaseModel):
    id: str
    topic: str
    label: str
    value: str
    kind: str
    source: str
    as_of: date | None
    stance: str
    number: float | None


class CheckOut(BaseModel):
    label: str
    status: str
    detail: str
    facts: list[str]


class SetupOut(BaseModel):
    state: str
    still_valid: bool
    reasons: list[str]
    facts: list[str]


class NarrationOut(BaseModel):
    id: int
    status: str  # "ok" / "rejected" / "failed"
    model: str
    prompt_version: str
    question: str | None
    points: list[dict[str, Any]]
    problems: list[str]
    cost_usd: Decimal | None
    created_at: datetime


class WriterOut(BaseModel):
    ready: bool
    model: str | None
    note: str | None
    budget_cap_usd: Decimal
    budget_spent_usd: Decimal


class BriefOut(BaseModel):
    symbol: str
    name: str | None
    as_of: date | None
    stale: bool
    facts: list[FactOut]
    why_in_scan: list[str]
    supporting: list[str]
    against: list[str]
    cancels: list[str]
    scenarios: dict[str, str]
    checklist: list[CheckOut]
    unknowns: list[str]
    setup: SetupOut | None
    strategy: str | None
    research_only: bool | None


class CompareOut(BaseModel):
    briefs: list[BriefOut]
    # What was asked for and matched no stock with prices.
    not_found: list[str]


class ExplainOut(BaseModel):
    brief: BriefOut
    narration: NarrationOut | None
    writer: WriterOut
    prompt_version: str = PROMPT_VERSION


class NarrateIn(BaseModel):
    question: str | None = Field(default=None, max_length=MAX_QUESTION_CHARS)


def _fact(f: Fact) -> FactOut:
    return FactOut(
        id=f.id,
        topic=f.topic,
        label=f.label,
        value=f.value,
        kind=f.kind.value,
        source=f.source,
        as_of=f.as_of,
        stance=f.stance.value,
        number=f.number,
    )


def brief_out(b: Brief) -> BriefOut:
    return BriefOut(
        symbol=b.symbol,
        name=b.name,
        as_of=b.as_of,
        stale=b.stale,
        facts=[_fact(f) for f in b.facts],
        why_in_scan=b.why_in_scan,
        supporting=b.supporting,
        against=b.against,
        cancels=b.cancels,
        scenarios=b.scenarios,
        checklist=[CheckOut(**asdict(c)) for c in b.checklist],
        unknowns=b.unknowns,
        setup=None if b.setup is None else SetupOut(**asdict(b.setup)),
        strategy=b.strategy,
        research_only=b.research_only,
    )


def narration_out(e: Explanation) -> NarrationOut:
    return NarrationOut(
        id=e.id,
        status=e.status,
        model=e.model,
        prompt_version=e.prompt_version,
        question=e.question,
        points=list(e.points),
        problems=[str(p) for p in e.problems],
        cost_usd=e.cost_usd,
        created_at=e.created_at,
    )


def _writer(session: Session) -> WriterOut:
    settings = effective_settings(session)
    writer = make_writer(settings)
    money = budget(session)
    note = None
    if writer is None:
        note = "No LLM key in .env: Jeron's own brief only (it needs no LLM)."
    elif money.reached:
        note = "This month's LLM cap is reached."
    return WriterOut(
        ready=writer is not None and not money.reached,
        model=writer.name if writer else None,
        note=note,
        budget_cap_usd=money.cap,
        budget_spent_usd=money.spent,
    )


def _brief(session: Session, symbol: str) -> Brief:
    found = explain(session, symbol)
    if found is None:
        raise HTTPException(404, f"No prices stored for {symbol.upper()}")
    return found[1]


@router.get("/stocks/compare")
def compare(
    session: SessionDep,
    symbols: Annotated[str, Query(min_length=1, max_length=200)],
) -> CompareOut:
    """Up to three stocks' briefs, in the order asked. No LLM. Each entry is a symbol or,
    failing that, what the search box would match first (a company name, a short name, an
    old symbol); one that matches nothing is listed in `not_found` instead of failing
    the rest."""
    wanted = list(dict.fromkeys(s.strip().upper() for s in symbols.split(",") if s.strip()))
    if not 1 <= len(wanted) <= MAX_COMPARE:
        raise HTTPException(422, f"Compare 1 to {MAX_COMPARE} stocks, separated by commas.")
    briefs: dict[str, Brief] = {}
    not_found: list[str] = []
    for asked in wanted:
        found = explain(session, asked)
        if found is None:
            match = next(iter(store.stock_search(session, asked, 1)), None)
            found = None if match is None else explain(session, match.symbol)
        if found is None:
            not_found.append(asked)
        else:
            briefs.setdefault(found[1].symbol, found[1])
    return CompareOut(briefs=[brief_out(b) for b in briefs.values()], not_found=not_found)


@router.get("/stocks/{symbol}/explain")
def stock_explain(symbol: str, session: SessionDep) -> ExplainOut:
    """Jeron's brief (facts with sources and dates, built without an LLM) and the
    newest stored wording of it, if any."""
    b = _brief(session, symbol)
    stored = latest_narration(session, b)
    return ExplainOut(
        brief=brief_out(b),
        narration=None if stored is None else narration_out(stored),
        writer=_writer(session),
    )


@router.post("/stocks/{symbol}/explain/narrate")
def stock_narrate(symbol: str, body: NarrateIn, session: SessionDep) -> NarrationOut:
    """Ask the LLM to word the brief (or answer a question from its facts). Every reply
    is checked; one that adds a number or reads as advice is stored as rejected."""
    b = _brief(session, symbol)
    try:
        row = narrate(session, b, body.question, make_writer(effective_settings(session)))
    except NarrationRefusedError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return narration_out(row)
