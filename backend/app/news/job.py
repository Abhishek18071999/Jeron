"""News labels in the database: the free subject rules for every announcement, an LLM
for the material ones, the hand-labelled test set and the labels the news score reads.

Only stocks that could be traded get LLM labels: an announcement is sent when its
stock's median daily turnover in that calendar year was at least ₹5 crore (the
universe's liquidity floor). Labels are stored once per (announcement, labeller, prompt
version), so re-runs never pay twice.
"""

import csv
import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
from sqlalchemy import extract, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.data.store import NSE_BARS
from app.models import Announcement, DailyBar, Instrument, NewsBatch
from app.models import NewsLabel as NewsLabelRow
from app.news.claude import ClaudeLabeller, Labeller, Usage
from app.news.deepseek import DeepSeekLabeller, LabellerError
from app.news.labels import (
    PROMPT_VERSION,
    RULES_LABELLER,
    Accuracy,
    DatedLabel,
    EventType,
    NewsItem,
    NewsLabel,
    accuracy,
    needs_llm,
    rule_label,
)
from app.news.ollama import OllamaLabeller

IST = ZoneInfo("Asia/Kolkata")
RULES_VERSION = "rules-v1"
LIQUID_TURNOVER = Decimal("50000000")  # ₹5 crore median daily turnover
_CHUNK = 2000
# Commit after this many LLM labels, so a stopped run keeps what it paid for.
_SAVE_EVERY = 20

Log = Callable[[str], None]


def _quiet(_: str) -> None:
    pass


def liquid_years(session: Session) -> dict[str, set[int]]:
    """Symbol -> the calendar years its median daily EQ turnover reached ₹5 crore."""
    year = extract("year", DailyBar.trade_date)
    rows = session.execute(
        select(Instrument.symbol, year)
        .join(DailyBar, DailyBar.instrument_id == Instrument.id)
        .where(DailyBar.source == NSE_BARS, DailyBar.series == "EQ")
        .group_by(Instrument.symbol, year)
        .having(func.percentile_cont(0.5).within_group(DailyBar.turnover) >= LIQUID_TURNOVER)
    )
    found: dict[str, set[int]] = {}
    for symbol, yr in rows:
        found.setdefault(symbol, set()).add(int(yr))
    return found


def save_labels(
    session: Session,
    labeller: str,
    version: str,
    labels: Iterable[tuple[int, NewsLabel]],
) -> int:
    """Store labels not stored yet. Returns how many were new."""
    rows = [
        {
            "announcement_id": announcement_id,
            "labeller": labeller,
            "prompt_version": version,
            "event_type": label.event_type.value,
            "sentiment": label.sentiment,
            "reason": label.reason,
        }
        for announcement_id, label in labels
    ]
    new = 0
    for start in range(0, len(rows), _CHUNK):
        result = session.execute(
            pg_insert(NewsLabelRow)
            .values(rows[start : start + _CHUNK])
            .on_conflict_do_nothing()
            .returning(NewsLabelRow.id)
        )
        new += len(result.all())
    return new


def _unlabelled(labeller: str, version: str):  # type: ignore[no-untyped-def]
    return ~(
        select(NewsLabelRow.id)
        .where(
            NewsLabelRow.announcement_id == Announcement.id,
            NewsLabelRow.labeller == labeller,
            NewsLabelRow.prompt_version == version,
        )
        .exists()
    )


def label_rules(session: Session, log: Log = _quiet) -> int:
    """Give every announcement without one its subject-rule label (free)."""
    new = 0
    while True:
        rows = session.execute(
            select(Announcement.id, Announcement.subject, Announcement.text)
            .where(_unlabelled(RULES_LABELLER, RULES_VERSION))
            .order_by(Announcement.id)
            .limit(50_000)
        ).all()
        if not rows:
            break
        labels = []
        for announcement_id, subject, text in rows:
            event_type, material = rule_label(subject, text)
            reason = "Routine filing." if not material else f"NSE subject: {subject or 'none'}."
            labels.append(
                (announcement_id, NewsLabel(event_type=event_type, sentiment=0, reason=reason))
            )
        new += save_labels(session, RULES_LABELLER, RULES_VERSION, labels)
        session.commit()
        log(f"  {new} announcements labelled by subject so far.")
    return new


def pending_items(
    session: Session,
    labeller: str,
    start: date | None = None,
    end: date | None = None,
    symbols: Sequence[str] | None = None,
    limit: int | None = None,
    version: str = PROMPT_VERSION,
) -> list[NewsItem]:
    """Material announcements of liquid stocks that `labeller` hasn't labelled, newest
    first (recent news matters most if a run is cut short)."""
    stmt = (
        select(
            Announcement.id,
            Announcement.symbol,
            Announcement.day,
            Announcement.subject,
            Announcement.text,
        )
        .where(_unlabelled(labeller, version))
        .order_by(Announcement.day.desc(), Announcement.id)
    )
    if start:
        stmt = stmt.where(Announcement.day >= start)
    if end:
        stmt = stmt.where(Announcement.day <= end)
    if symbols:
        stmt = stmt.where(Announcement.symbol.in_(list(symbols)))
    liquid = liquid_years(session)
    names = dict(
        session.execute(
            select(Instrument.symbol, Instrument.name).where(Instrument.name.is_not(None))
        ).all()
    )
    items: list[NewsItem] = []
    for row in session.execute(stmt):
        if row.day.year not in liquid.get(row.symbol, ()) or not needs_llm(row.subject, row.text):
            continue
        items.append(
            NewsItem(row.id, row.symbol, row.day, row.subject, row.text, names.get(row.symbol))
        )
        if limit and len(items) >= limit:
            break
    return items


@dataclass
class LabelRun:
    sent: int = 0
    labelled: int = 0
    failed: int = 0


def label_news(
    session: Session,
    labeller: Labeller,
    items: Sequence[NewsItem],
    log: Log = _quiet,
) -> LabelRun:
    """Label `items` one request at a time, saving as it goes."""
    run = LabelRun()
    for start in range(0, len(items), _SAVE_EVERY):
        chunk = items[start : start + _SAVE_EVERY]
        labels = labeller.label(chunk)
        good = [(item.id, label) for item, label in zip(chunk, labels, strict=True) if label]
        run.sent += len(chunk)
        run.labelled += save_labels(session, labeller.name, PROMPT_VERSION, good)
        run.failed += len(chunk) - len(good)
        session.commit()
        if run.sent % 500 < _SAVE_EVERY:
            log(f"  {run.sent} of {len(items)} sent, {run.labelled} labelled.")
    return run


def submit_batches(
    session: Session, labeller: ClaudeLabeller, items: Sequence[NewsItem], log: Log = _quiet
) -> list[str]:
    """Send `items` as Message Batches (half price, back within a day)."""
    ids: list[str] = []
    for start in range(0, len(items), labeller.BATCH_LIMIT):
        chunk = items[start : start + labeller.BATCH_LIMIT]
        batch_id = labeller.submit_batch(chunk)
        session.add(
            NewsBatch(
                batch_id=batch_id,
                labeller=labeller.name,
                prompt_version=PROMPT_VERSION,
                items=len(chunk),
            )
        )
        session.commit()
        log(f"  Sent batch {batch_id} with {len(chunk)} announcements.")
        ids.append(batch_id)
    return ids


def collect_batches(
    session: Session, labeller: ClaudeLabeller, log: Log = _quiet
) -> tuple[int, int]:
    """Store the labels of finished batches. Returns (new labels, batches still running)."""
    new = running = 0
    batches = session.scalars(
        select(NewsBatch).where(
            NewsBatch.collected_at.is_(None),
            NewsBatch.labeller == labeller.name,
            NewsBatch.prompt_version == PROMPT_VERSION,
        )
    ).all()
    for batch in batches:
        if not labeller.batch_done(batch.batch_id):
            running += 1
            continue
        found = labeller.batch_results(batch.batch_id, log=log)
        good = [(i, label) for i, label in found.items() if label]
        new += save_labels(session, labeller.name, PROMPT_VERSION, good)
        batch.collected_at = datetime.now(IST)
        session.commit()
        log(f"  Batch {batch.batch_id}: {len(good)} of {batch.items} labelled.")
    return new, running


# Test set ------------------------------------------------------------------------

TEST_COLUMNS = ["id", "symbol", "company", "date", "subject", "text", "event_type", "sentiment"]


def export_test_set(
    session: Session, path: Path, size: int = 100, since: date = date(2023, 1, 1), seed: int = 6
) -> int:
    """Write `size` real announcements for hand labelling, spread across event types
    (by the subject rules) so every type is tested. The label columns are left empty."""
    # Every material announcement of a liquid stock: no label is ever stored under
    # this labeller name.
    items = pending_items(session, labeller="test-set", start=since)
    by_type: dict[EventType, list[NewsItem]] = {}
    for item in items:
        by_type.setdefault(rule_label(item.subject, item.text)[0], []).append(item)
    rng = random.Random(seed)
    for group in by_type.values():
        rng.shuffle(group)
    chosen: list[NewsItem] = []
    while len(chosen) < size and any(by_type.values()):
        for group in by_type.values():
            if group and len(chosen) < size:
                chosen.append(group.pop())
    rng.shuffle(chosen)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(TEST_COLUMNS)
        for item in chosen:
            writer.writerow(
                [item.id, item.symbol, item.company or "", item.day, item.subject or "",
                 item.text, "", ""]
            )  # fmt: skip
    return len(chosen)


def read_test_set(path: Path) -> tuple[list[NewsItem], dict[int, NewsLabel], list[str]]:
    """(items, hand labels by id, problems). Rows without both labels are skipped."""
    items: list[NewsItem] = []
    truth: dict[int, NewsLabel] = {}
    problems: list[str] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            kind = (row.get("event_type") or "").strip().lower().replace(" ", "_")
            sentiment = (row.get("sentiment") or "").strip().replace("+", "")
            if not kind and not sentiment:
                continue
            try:
                label = NewsLabel(event_type=EventType(kind), sentiment=int(sentiment), reason="-")
                item = NewsItem(
                    int(row["id"]),
                    row["symbol"],
                    date.fromisoformat(row["date"]),
                    row["subject"] or None,
                    row["text"],
                    row["company"] or None,
                )
            except (ValueError, KeyError) as exc:
                problems.append(f"row {n}: {exc}")
                continue
            items.append(item)
            truth[item.id] = label
    return items, truth, problems


@dataclass
class Evaluation:
    llm: Accuracy
    rules: Accuracy
    problems: list[str]


def evaluate_test_set(
    session: Session, path: Path, labeller: Labeller, log: Log = _quiet
) -> Evaluation:
    """Compare the LLM's labels (and the free subject rules) with the hand labels.
    Test items the LLM hasn't labelled yet are labelled now (about 100 requests)."""
    items, truth, problems = read_test_set(path)
    stored = _labels(session, [i.id for i in items], labeller.name, PROMPT_VERSION)
    missing = [i for i in items if i.id not in stored]
    if missing:
        log(f"Labelling {len(missing)} test announcements with {labeller.name}...")
        label_news(session, labeller, missing, log)
        stored = _labels(session, [i.id for i in items], labeller.name, PROMPT_VERSION)
    llm_pairs = []
    for item in items:
        if item.id in stored:
            llm_pairs.append((truth[item.id], stored[item.id]))
        else:
            problems.append(f"{item.symbol} {item.day}: the model gave no valid label")
    rules_pairs = [
        (
            truth[i.id],
            NewsLabel(event_type=rule_label(i.subject, i.text)[0], sentiment=0, reason="rules"),
        )
        for i in items
    ]
    return Evaluation(accuracy(llm_pairs), accuracy(rules_pairs), problems)


def _labels(
    session: Session, ids: Sequence[int], labeller: str, version: str
) -> dict[int, NewsLabel]:
    rows = session.execute(
        select(
            NewsLabelRow.announcement_id,
            NewsLabelRow.event_type,
            NewsLabelRow.sentiment,
            NewsLabelRow.reason,
        ).where(
            NewsLabelRow.announcement_id.in_(list(ids)),
            NewsLabelRow.labeller == labeller,
            NewsLabelRow.prompt_version == version,
        )
    )
    return {
        i: NewsLabel(event_type=EventType(t), sentiment=s, reason=r or "-") for i, t, s, r in rows
    }


def dated_labels(
    session: Session, symbols: Sequence[str], labeller: str, end: date | None = None
) -> dict[str, list[DatedLabel]]:
    """Each stock's LLM labels with a sentiment, for the news score (subject-rule labels
    all have sentiment 0, so they would add nothing)."""
    stmt = (
        select(
            Announcement.symbol, Announcement.day, NewsLabelRow.event_type, NewsLabelRow.sentiment
        )
        .join(NewsLabelRow, NewsLabelRow.announcement_id == Announcement.id)
        .where(
            Announcement.symbol.in_(list(symbols)),
            NewsLabelRow.labeller == labeller,
            NewsLabelRow.prompt_version == PROMPT_VERSION,
            NewsLabelRow.sentiment != 0,
        )
        .order_by(Announcement.day)
    )
    if end:
        stmt = stmt.where(Announcement.day <= end)
    found: dict[str, list[DatedLabel]] = {}
    for symbol, day, kind, sentiment in session.execute(stmt):
        found.setdefault(symbol, []).append(DatedLabel(day, EventType(kind), sentiment))
    return found


# The command ----------------------------------------------------------------------

# Above this many announcements, a one-by-one run should be a batch instead.
SYNC_LIMIT = 2000
DAILY_LOOKBACK_DAYS = 7


def make_labeller(settings: Settings, model: str | None = None) -> Labeller | None:
    """The labeller `.env` asks for (`JERON_NEWS_PROVIDER`); None without its key."""
    if settings.news_provider == "ollama":
        if not settings.ollama_api_key:
            return None
        return OllamaLabeller(
            settings.ollama_api_key, model or settings.ollama_model, settings.ollama_base_url
        )
    if settings.news_provider == "deepseek":
        if not settings.deepseek_api_key:
            return None
        return DeepSeekLabeller(
            settings.deepseek_api_key,
            model or settings.deepseek_model,
            settings.deepseek_base_url,
        )
    if not settings.anthropic_api_key:
        return None
    return ClaudeLabeller(settings.anthropic_api_key, model or settings.news_model)


def labeller_name(settings: Settings) -> str:
    """The model whose labels the news score reads (the provider in `.env`)."""
    return {
        "deepseek": settings.deepseek_model,
        "ollama": settings.ollama_model,
    }.get(settings.news_provider, settings.news_model)


def labels_exist(session: Session, labeller: str) -> bool:
    return (
        session.scalar(
            select(NewsLabelRow.id)
            .where(NewsLabelRow.labeller == labeller, NewsLabelRow.prompt_version == PROMPT_VERSION)
            .limit(1)
        )
        is not None
    )


def missing_key(settings: Settings) -> str:
    name = {"deepseek": "DEEPSEEK", "ollama": "OLLAMA"}.get(settings.news_provider, "ANTHROPIC")
    return (
        f"No JERON_{name}_API_KEY in .env: the news brain is off; only the free "
        "subject labels were made."
    )


def run_news(
    session: Session,
    labeller: Labeller | None,
    start: date | None = None,
    end: date | None = None,
    limit: int | None = None,
    batch: bool = False,
    log: Log = _quiet,
    no_labeller: str = "No news API key in .env: only the free subject labels were made.",
) -> int:
    """Label announcements: subject rules for all (free), then the LLM for the material
    ones of liquid stocks. Returns a process exit code."""
    new = label_rules(session)
    if new:
        log(f"{new} announcements labelled by subject (free).")
    if labeller is None:
        log(no_labeller)
        return 0
    try:
        return _run_llm(session, labeller, start, end, limit, batch, log)
    except (anthropic.APIError, LabellerError) as exc:
        session.rollback()
        log(f"News API error: {api_error_message(exc)}")
        log("Labels made before the error are kept; run the same command again once fixed.")
        return 1


def api_error_message(exc: Exception) -> str:
    """The API's own words ("Your credit balance is too low..."), not the raw response."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    return str(getattr(exc, "message", None) or exc)


def spent(labeller: Labeller) -> str:
    """What a run used: US$ for Claude, tokens for others (see their own bill)."""
    usage: Usage | None = getattr(labeller, "usage", None)
    if usage is None:
        return ""
    cost = usage.cost(labeller.name)
    if cost is not None:
        return f"about US${cost:.2f}"
    return (
        f"{usage.input_tokens:,} input and {usage.output_tokens:,} output tokens "
        "(the exact cost is on your provider's billing page)"
    )


def _run_llm(
    session: Session,
    labeller: Labeller,
    start: date | None,
    end: date | None,
    limit: int | None,
    batch: bool,
    log: Log,
) -> int:
    claude = labeller if isinstance(labeller, ClaudeLabeller) else None
    if claude:
        stored, running = collect_batches(session, claude, log)
        if stored or running:
            log(f"{stored} labels from finished batches; {running} batches still running.")
    if batch and not claude:
        log(f"Batches are for Claude only; {labeller.name} labels several at a time instead.")
        batch = False
    items = pending_items(session, labeller.name, start, end, limit=limit)
    if not items:
        log("Nothing new to label.")
        return 0
    if batch and claude:
        submit_batches(session, claude, items, log)
        log(
            f"{len(items)} announcements sent as a batch (half price). Batches usually "
            "finish within an hour, at most a day: run `news-label --collect` later."
        )
        return 0
    if claude and len(items) > SYNC_LIMIT:
        log(
            f"{len(items)} announcements to label: too many to send one by one. Use "
            "--batch (half price), or --limit or --start to label fewer."
        )
        return 1
    log(f"Labelling {len(items)} announcements with {labeller.name}...")
    run = label_news(session, labeller, items, log)
    used = spent(labeller)
    log(
        f"Done: {run.labelled} labelled, {run.failed} without a valid label"
        + (f"; used {used}." if used else ".")
    )
    return 0


def run_daily_news(session: Session, settings: Settings, day: date, log: Log = _quiet) -> None:
    """The daily job's step: the last week's new announcements. A failure here (the API
    down, the key wrong) is logged and doesn't stop the scan or the alerts."""
    try:
        start = date.fromordinal(day.toordinal() - DAILY_LOOKBACK_DAYS)
        run_news(
            session,
            make_labeller(settings),
            start=start,
            end=day,
            limit=SYNC_LIMIT,
            log=log,
            no_labeller=missing_key(settings),
        )
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        log(f"News labels skipped: {type(exc).__name__}: {exc}")
