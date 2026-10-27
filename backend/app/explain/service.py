"""Load one stock's facts from the database for the explain brief (app/explain/facts.py).
Everything comes from what Jeron already stored and computed; nothing is fetched."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.calendar.nse import TradingCalendar, UnknownCalendarYearError
from app.config import Settings, get_settings
from app.data import store
from app.data.adjust import AdjustedBar, adjust_bars, build_adjustments
from app.exits.job import due_session
from app.explain.facts import (
    Brief,
    FundInputs,
    NewsInputs,
    ScanInputs,
    SignalInputs,
    StockInputs,
    build_brief,
)
from app.explain.narrate import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    check,
    clean_question,
    fact_json,
    user_prompt,
)
from app.explain.writers import Writer
from app.fundamentals.job import stock_fundamentals
from app.journal.service import entry_views
from app.market.service import latest_ok_scan, mood_on
from app.models import (
    Announcement,
    Explanation,
    Instrument,
    JournalEntry,
    PaperAccount,
    ScanResult,
    SignalRecord,
)
from app.models import NewsLabel as NewsLabelRow
from app.news.job import api_error_message, budget, labeller_name, record_usage
from app.news.labels import PROMPT_VERSION as NEWS_PROMPT_VERSION
from app.news.labels import rule_label
from app.plan.service import events_ahead

NEWS_DAYS = 90


def _due(settings: Settings, now: datetime) -> date | None:
    try:
        return due_session(
            TradingCalendar.default(), now, time.fromisoformat(settings.schedule_daily)
        )
    except UnknownCalendarYearError:
        return None


def _scan(session: Session, symbol: str) -> ScanInputs | None:
    run = latest_ok_scan(session)
    if run is None:
        return None
    row = session.scalar(
        select(ScanResult).where(ScanResult.run_id == run.id, ScanResult.symbol == symbol)
    )
    if row is None:
        return None
    return ScanInputs(
        trade_date=run.trade_date,
        score=float(row.score),
        rank=row.rank,
        universe=run.universe_size or None,
        score_version=run.score_version,
        components=list(row.components or []),
        indicators=dict(row.indicators or {}),
    )


def _signal(
    session: Session, symbol: str, factor_on: dict[date, Decimal], adjusted: list[AdjustedBar]
) -> SignalInputs | None:
    """The newest signal, live before research-only on the same day, with its levels
    on today's price basis (splits and bonuses since the signal day applied)."""
    rows = session.execute(
        select(SignalRecord, PaperAccount.strategy_key)
        .join(PaperAccount, PaperAccount.id == SignalRecord.account_id)
        .where(SignalRecord.ticker == symbol)
        .order_by(SignalRecord.signal_date.desc(), SignalRecord.research_only)
        .limit(1)
    ).all()
    if not rows:
        return None
    rec, strategy = rows[0]
    p = rec.payload
    f = float(factor_on.get(rec.signal_date, Decimal(1)))

    def lvl(value: object) -> float:
        return round(float(str(value)) * f, 2)

    since = [
        (a.raw.trade_date, float(a.open), float(a.low), float(a.close))
        for a in adjusted
        if a.raw.trade_date > rec.signal_date
    ]
    return SignalInputs(
        signal_date=rec.signal_date,
        strategy=strategy,
        research_only=rec.research_only,
        setup_name=p["setup_name"],
        tier=p.get("tier", ""),
        entry_low=lvl(p["entry_zone"]["low"]),
        entry_high=lvl(p["entry_zone"]["high"]),
        valid_until=date.fromisoformat(p["entry_zone"]["valid_until"]),
        stop=lvl(p["stop"]["price"]),
        stop_reason=p["stop"].get("reason", ""),
        t1=lvl(p["targets"]["t1"]),
        t2=lvl(p["targets"]["t2"]),
        invalidation=p.get("invalidation", ""),
        why=list(p.get("why", [])),
        backtest=dict(p.get("backtest_stats") or {}),
        since=since,
    )


def _news(session: Session, symbol: str, today: date, labeller: str) -> list[NewsInputs]:
    rows = session.execute(
        select(Announcement.id, Announcement.day, Announcement.subject, Announcement.text)
        .where(Announcement.symbol == symbol, Announcement.day >= today - timedelta(NEWS_DAYS))
        .order_by(Announcement.day.desc(), Announcement.id.desc())
        .limit(40)
    ).all()
    labels = {
        i: (t, s, why)
        for i, t, s, why in session.execute(
            select(
                NewsLabelRow.announcement_id,
                NewsLabelRow.event_type,
                NewsLabelRow.sentiment,
                NewsLabelRow.reason,
            ).where(
                NewsLabelRow.announcement_id.in_([r.id for r in rows]),
                NewsLabelRow.labeller == labeller,
                NewsLabelRow.prompt_version == NEWS_PROMPT_VERSION,
            )
        )
    }
    out = []
    for r in rows:
        kind, material = rule_label(r.subject, r.text)
        found = labels.get(r.id)
        if found is not None:
            out.append(NewsInputs(r.day, r.subject or "", found[0], found[1], found[2], labeller))
        elif material:
            out.append(NewsInputs(r.day, r.subject or "", kind.value, None, "", None))
    return out


def _fundamentals(session: Session, symbol: str, day: date) -> FundInputs | None:
    found = stock_fundamentals(session, symbol, day)
    if found is None:
        return None
    s = found.score
    newest = found.quarters[-1] if found.quarters else None
    filed = max((q.disseminated_at for q in found.quarters), default=None)
    return FundInputs(
        score=s.score,
        quality=s.quality,
        valuation=s.valuation,
        rejected=s.rejected,
        version=s.version,
        newest_quarter=newest.period_end if newest else None,
        filed=filed.date() if filed else None,
        facts=dict(s.facts),
        notes=list(s.notes),
    )


def _holding(session: Session, symbol: str) -> tuple[int, float, float | None] | None:
    entries = session.scalars(select(JournalEntry).where(JournalEntry.ticker == symbol)).all()
    held, cost, stop = 0, 0.0, None
    for v in entry_views(session, entries):
        p = v.position
        if p.status != "open" or not p.held or p.avg_entry is None:
            continue
        held += p.held
        cost += p.held * float(p.avg_entry)
        if v.stop is not None:
            stop = float(v.stop) if stop is None else max(stop, float(v.stop))
    return (held, round(cost / held, 2), stop) if held else None


def stock_inputs(
    session: Session, symbol: str, *, now: datetime | None = None
) -> StockInputs | None:
    """Everything Jeron knows about `symbol` today; None when no prices are stored."""
    symbol = symbol.strip().upper()
    settings = get_settings()
    now = now or datetime.now(ZoneInfo(settings.timezone))
    instrument = session.scalar(select(Instrument).where(Instrument.symbol == symbol))
    bars = store.symbol_bars(session, symbol, store.NSE_BARS)
    if instrument is None or not bars:
        return None
    actions = [
        a.record for a in store.symbol_actions(session, symbol) if a.source == store.NSE_ACTIONS
    ]
    adjusted = adjust_bars(bars, build_adjustments(bars, actions))
    factor_on = {a.raw.trade_date: a.factor for a in adjusted}
    last = bars[-1]
    today = now.astimezone(ZoneInfo(settings.timezone)).date()
    mood = mood_on(session)
    events = events_ahead(session, symbol, last.trade_date)
    return StockInputs(
        symbol=symbol,
        name=instrument.name,
        sector=instrument.sector,
        today=today,
        last_date=last.trade_date,
        last_close=float(last.close),
        due=_due(settings, now),
        scan=_scan(session, symbol),
        mood=None if mood is None else (mood.day, mood.mode.value, mood.reason),
        results_date=events.results_date,
        results_line=events.results_line,
        blackout=events.blackout,
        ex_dates=list(events.ex_dates),
        signal=_signal(session, symbol, factor_on, adjusted),
        fundamentals=_fundamentals(session, symbol, last.trade_date),
        news=_news(session, symbol, today, labeller_name(settings)),
        news_ready=settings.news_ready,
        holding=_holding(session, symbol),
    )


def adjusted_closes(session: Session, symbol: str) -> list[tuple[date, float]]:
    """Split/bonus-adjusted closes, oldest first (for Compare's performance)."""
    bars = store.symbol_bars(session, symbol.strip().upper(), store.NSE_BARS)
    if not bars:
        return []
    actions = [
        a.record for a in store.symbol_actions(session, symbol) if a.source == store.NSE_ACTIONS
    ]
    return [
        (a.raw.trade_date, float(a.close))
        for a in adjust_bars(bars, build_adjustments(bars, actions))
    ]


def sector_industry(session: Session, symbol: str) -> tuple[str | None, str | None]:
    row = session.execute(
        select(Instrument.sector, Instrument.industry).where(
            Instrument.symbol == symbol.strip().upper()
        )
    ).first()
    return (None, None) if row is None else (row[0], row[1])


# --- The optional LLM wording ---------------------------------------------------------

DAILY_LIMIT = 50  # narrations a day, whatever the cap


class NarrationRefusedError(RuntimeError):
    """No narration: no API key, the monthly cap is reached, or the daily limit."""


def explain(
    session: Session, symbol: str, *, now: datetime | None = None
) -> tuple[StockInputs, Brief] | None:
    found = stock_inputs(session, symbol, now=now)
    return None if found is None else (found, build_brief(found))


def latest_narration(session: Session, brief: Brief) -> Explanation | None:
    """The newest narration without a question that passed and was made from exactly
    this brief's facts (its fact ids point at the same facts)."""
    facts = [fact_json(f) for f in brief.facts]
    rows = session.scalars(
        select(Explanation)
        .where(
            Explanation.symbol == brief.symbol,
            Explanation.as_of == brief.as_of,
            Explanation.question.is_(None),
            Explanation.status == "ok",
            Explanation.prompt_version == PROMPT_VERSION,
        )
        .order_by(Explanation.id.desc())
        .limit(10)
    )
    return next((r for r in rows if r.facts == facts), None)


def _usage_name(model: str) -> str:
    return f"explain:{model}"


def narrate(
    session: Session,
    brief: Brief,
    question: str | None,
    writer: Writer | None,
    *,
    now: datetime | None = None,
) -> Explanation:
    """Ask the model to word `brief`, check the reply, store it either way. Without a
    question, a narration of the same day that passed is returned instead of a new one."""
    question = clean_question(question)
    if writer is None:
        raise NarrationRefusedError(
            "No LLM key is set (the news provider's key in .env), so only Jeron's own "
            "brief is shown."
        )
    if question is None:
        cached = latest_narration(session, brief)
        if cached is not None and cached.model == writer.name:
            return cached
    money = budget(session, now)
    if money.reached:
        raise NarrationRefusedError(
            f"The monthly LLM cap of US${money.cap:.2f} is reached (about "
            f"US${money.spent:.2f} used); raise it on the Settings page."
        )
    local = (now or datetime.now(ZoneInfo(get_settings().timezone))).astimezone(
        ZoneInfo(get_settings().timezone)
    )
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    made_today = session.scalar(
        select(func.count(Explanation.id)).where(Explanation.created_at >= midnight)
    )
    if (made_today or 0) >= DAILY_LIMIT:
        raise NarrationRefusedError(f"The limit of {DAILY_LIMIT} explanations a day is reached.")

    facts = [fact_json(f) for f in brief.facts]
    row = Explanation(
        symbol=brief.symbol,
        as_of=brief.as_of,
        question=question,
        model=writer.name,
        prompt_version=PROMPT_VERSION,
        facts=facts,
        points=[],
        problems=[],
    )
    try:
        reply, used = writer.write(SYSTEM_PROMPT, user_prompt(brief, question))
    except Exception as exc:  # the provider's error, told to the owner, never retried here
        row.status = "failed"
        row.problems = [api_error_message(exc)[:300]]
        session.add(row)
        session.flush()
        return row
    cost = used.cost(writer.name)
    row.cost_usd = None if cost is None else Decimal(str(round(cost, 4)))
    record_usage(session, writer.name, used, name=_usage_name(writer.name))
    checked = check(reply, brief)
    row.status = "ok" if checked.ok else "rejected"
    row.points = checked.points
    row.problems = checked.problems
    session.add(row)
    session.flush()
    return row
