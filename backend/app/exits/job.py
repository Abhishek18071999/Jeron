"""The pre-open check (spec section 5, 08:30 IST): every open position in my journal
against the exit rules, upcoming results and corporate actions, sent as one message.

Paper positions need nothing from me (the paper job exits them), so they are only
counted. If the latest prices are missing, the check says so and gives no actions.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.channels import Channel, channels_from
from app.alerts.format import inr
from app.alerts.job import NOT_SET_UP, AlertOutcome, _send
from app.backtest.strategies import Tier
from app.calendar.nse import TradingCalendar, UnknownCalendarYearError
from app.config import Settings, get_settings
from app.data import store
from app.data.adjust import AdjustedBar, adjust_bars, build_adjustments
from app.data.events import next_results
from app.enums import CorporateActionType
from app.exits.rules import Action, ExitBar, ExitPlan, exit_plan
from app.indicators import atr
from app.journal.service import EntryView, entry_views
from app.models import DailyBar, JournalEntry, PaperTrade
from app.signals.build import IST

Log = Callable[[str], None]
# Results meetings and ex-dates this many sessions ahead are flagged (spec section 5's
# blackout window).
EVENT_SESSIONS = 3


def _quiet(_: str) -> None:
    pass


@dataclass
class PositionCheck:
    entry_id: int
    ticker: str
    strategy_key: str | None
    tier: Tier
    tier_assumed: bool  # a trade without a signal: swing rules
    shares: int
    avg_entry: Decimal
    last_close: float | None
    r_now: float | None
    plan: ExitPlan | None
    problem: str | None = None
    events: list[str] = field(default_factory=list)

    @property
    def action(self) -> Action | None:
        return self.plan.action if self.plan else None


@dataclass
class PreOpen:
    day: date  # the session the check is for
    data_as_of: date | None
    expected: date  # the session whose close the check needs
    positions: list[PositionCheck]
    paper_open: int
    paper_accounts: int

    @property
    def stale(self) -> bool:
        return self.data_as_of is None or self.data_as_of < self.expected


def is_session(calendar: TradingCalendar, day: date) -> bool:
    """A trading day; a weekday when NSE's holiday list doesn't cover the year."""
    try:
        return calendar.is_trading_day(day)
    except UnknownCalendarYearError:
        return day.weekday() < 5


def next_session(calendar: TradingCalendar, day: date) -> date:
    day += timedelta(days=1)
    while not is_session(calendar, day):
        day += timedelta(days=1)
    return day


def _previous_session(session: Session, calendar: TradingCalendar, day: date) -> date:
    """The session before `day`. Without the year's holiday list, weekdays NSE marked as
    not published (holidays) are skipped."""
    try:
        return calendar.previous_trading_day(day)
    except UnknownCalendarYearError:
        statuses = store.source_statuses(session, store.NSE_BARS, day - timedelta(days=14), day)
        day -= timedelta(days=1)
        while day.weekday() >= 5 or statuses.get(day) == "not_published":
            day -= timedelta(days=1)
        return day


def check_day(calendar: TradingCalendar, now: datetime) -> date:
    """The session a check run at `now` is for: today if it trades and the market
    hasn't closed, else the next session."""
    today = now.astimezone(IST).date()
    if is_session(calendar, today) and now.astimezone(IST).hour < 16:
        return today
    return next_session(calendar, today)


def _tier(view: EntryView) -> tuple[Tier, bool]:
    if view.signal is not None:
        return Tier(view.signal.payload.get("tier", Tier.SWING.value)), False
    return Tier.SWING, True


def _factor_on(adjusted: Sequence[AdjustedBar], day: date) -> float:
    for a in adjusted:
        if a.raw.trade_date >= day:
            return float(a.factor)
    return 1.0


def position_check(session: Session, view: EntryView, data_as_of: date | None) -> PositionCheck:
    pos = view.position
    tier, assumed = _tier(view)
    check = PositionCheck(
        view.entry.id,
        view.entry.ticker,
        view.entry.strategy_key,
        tier,
        assumed,
        pos.held,
        pos.avg_entry or Decimal(0),
        None,
        None,
        None,
    )
    if view.stop is None:
        check.problem = "no stop set: add one in the journal"
        return check
    if pos.avg_entry is None or pos.first_date is None:
        return check
    bars = store.symbol_bars(session, view.entry.ticker, store.NSE_BARS, end=data_as_of)
    if not bars:
        check.problem = "no prices stored"
        return check
    actions = [
        a.record
        for a in store.symbol_actions(session, view.entry.ticker)
        if a.source == store.NSE_ACTIONS
    ]
    adjusted = adjust_bars(bars, build_adjustments(bars, actions))
    highs = [float(a.high) for a in adjusted]
    lows = [float(a.low) for a in adjusted]
    closes = [float(a.close) for a in adjusted]
    atrs = [math.nan if v is None else v for v in atr(highs, lows, closes)]
    since = [
        ExitBar(
            a.raw.trade_date,
            float(a.open),
            float(a.high),
            float(a.low),
            float(a.close),
            atrs[i],
        )
        for i, a in enumerate(adjusted)
        if a.raw.trade_date >= pos.first_date
    ]
    if not since:
        check.problem = f"no prices since the first buy on {pos.first_date:%d %b}"
        return check
    factor = _factor_on(adjusted, pos.first_date)
    entry, stop = float(pos.avg_entry) * factor, float(view.stop) * factor
    check.last_close = since[-1].close
    if stop >= entry:
        check.problem = f"stop {inr(view.stop)} is not below the average entry {inr(pos.avg_entry)}"
        return check
    check.r_now = (since[-1].close - entry) / (entry - stop)
    half_booked = pos.sold > 0 and pos.sold >= pos.bought // 2
    check.plan = exit_plan(entry, stop, tier, since, half_booked)
    return check


def _n(value: Decimal | None) -> str:
    return "?" if value is None else f"{value.normalize():f}"


def _events(session: Session, checks: Sequence[PositionCheck], day: date, last: date) -> None:
    symbols = [c.ticker for c in checks]
    results = store.results_dates(session, symbols)
    for c in checks:
        upcoming = next_results(results.get(c.ticker, []), day)
        if upcoming is not None and upcoming.meeting_date <= last:
            c.events.append(f"results board meeting on {upcoming.meeting_date:%a %-d %b}")
    for a in store.actions_between(session, store.NSE_ACTIONS, day, last, symbols):
        what = a.action_type.value
        if a.action_type in (CorporateActionType.SPLIT, CorporateActionType.BONUS):
            what += f" {_n(a.ratio_new)}:{_n(a.ratio_old)}"
        elif a.amount:
            what += f" {inr(a.amount)}"
        for c in checks:
            if c.ticker == a.symbol:
                c.events.append(f"{what}, ex-date {a.ex_date:%a %-d %b}: stop and shares change")


def build_preopen(session: Session, day: date, calendar: TradingCalendar | None = None) -> PreOpen:
    calendar = calendar or TradingCalendar.default()
    expected = _previous_session(session, calendar, day)
    data_as_of = session.scalar(
        select(func.max(DailyBar.trade_date)).where(
            DailyBar.source == store.NSE_BARS, DailyBar.trade_date <= expected
        )
    )
    entries = session.scalars(select(JournalEntry).order_by(JournalEntry.ticker)).all()
    views = [
        v for v in entry_views(session, entries, as_of=data_as_of) if v.position.status == "open"
    ]
    checks = [position_check(session, v, data_as_of) for v in views]
    last = day
    for _ in range(EVENT_SESSIONS - 1):
        last = next_session(calendar, last)
    _events(session, checks, day, last)
    paper = session.execute(
        select(func.count(), func.count(func.distinct(PaperTrade.account_id))).where(
            PaperTrade.status == "open"
        )
    ).one()
    return PreOpen(day, data_as_of, expected, checks, paper[0], paper[1])


ORDER = (Action.SELL_ALL, Action.SELL_HALF, Action.HOLD)
HEADINGS = {
    Action.SELL_ALL: "SELL ALL at the open",
    Action.SELL_HALF: "SELL HALF",
    Action.HOLD: "HOLD",
}


def _line(c: PositionCheck) -> str:
    head = f"- {c.ticker} {c.shares} sh"
    if c.r_now is not None:
        head += f", {c.r_now:+.2f}R"
    text = f"{head}: {c.plan.reason}" if c.plan else head
    extra = list(c.plan.notes) if c.plan else []
    if c.tier_assumed:
        extra.append("no signal: swing rules assumed")
    return "\n".join([text, *(f"  {n}" for n in extra)])


def preopen_message(p: PreOpen, web_url: str = "") -> str:
    lines = [f"Jeron pre-open check, {p.day:%a %-d %b %Y}"]
    if p.stale:
        when = f"{p.data_as_of:%a %-d %b}" if p.data_as_of else "never"
        lines += [
            "",
            f"Prices for {p.expected:%a %-d %b} are not loaded (latest: {when}). No actions "
            "today: run the daily job first, then this check again.",
        ]
    elif not p.positions:
        lines += ["", "No open positions in the journal."]
    else:
        lines[0] += f" (closes to {p.data_as_of:%a %-d %b})"
        for action in ORDER:
            group = [c for c in p.positions if c.action == action]
            if group:
                lines += ["", HEADINGS[action], *(_line(c) for c in group)]
        problems = [c for c in p.positions if c.plan is None]
        if problems:
            lines += ["", "CHECK BY HAND"]
            lines += [f"- {c.ticker} {c.shares} sh: {c.problem or 'no plan'}" for c in problems]
    events = [(c.ticker, e) for c in p.positions for e in c.events]
    if events:
        lines += ["", f"EVENTS (next {EVENT_SESSIONS} sessions)"]
        lines += [f"- {t}: {e}" for t, e in events]
    if p.paper_open:
        lines += [
            "",
            f"Paper: {p.paper_open} open positions in {p.paper_accounts} accounts, "
            "handled automatically.",
        ]
    if web_url:
        lines += ["", f"Journal: {web_url.rstrip('/')}/journal"]
    return "\n".join(lines)


def run_preopen(
    session: Session,
    day: date | None = None,
    *,
    settings: Settings | None = None,
    channels: Sequence[Channel] | None = None,
    now: datetime | None = None,
    send: bool = True,
    log: Log = _quiet,
) -> tuple[PreOpen, AlertOutcome]:
    settings = settings or get_settings()
    now = now or datetime.now(IST)
    calendar = TradingCalendar.default()
    day = day or check_day(calendar, now)
    p = build_preopen(session, day, calendar)
    text = preopen_message(p, settings.web_url)
    log(text)
    outcome = AlertOutcome(day, "ok")
    if not send:
        return p, outcome
    channels = channels_from(settings) if channels is None else channels
    if not channels:
        log(NOT_SET_UP)
        outcome.status = "not_configured"
        return p, outcome
    # A stale check isn't stored as sent, so the run after the daily job still goes out.
    key = f"preopen:{day}" if not p.stale else f"preopen-stale:{day}:{now:%H%M}"
    _send(session, channels, key, "preopen", text, f"Jeron pre-open {day}", outcome, now, day)
    return p, outcome
