"""The pre-open check (spec section 5, 08:30 IST): every open position in my journal
against the exit rules, upcoming results and corporate actions, sent as one message.

It also re-checks the entries: every live signal valid for today with no journal
entry yet is planned on the real account as the Trade page would (heat, positions,
guardrails, results blackout, the kill switch), skipped if it was held by the quality
check or has an ex-date today, and turned into the order to place: a limit at the top
of the entry zone, not bought above it or at the stop. Jeron has only end-of-day
prices, so the open itself (gaps, circuits, news after the evening run) is checked by
me at 09:08. The positions' tax timing notes (`app.portfolio.calc.tax_notes`) are
added as information only.

Paper positions need nothing from me (the paper job exits them), so they are only
counted. If the latest prices are missing, the check says so and gives no actions.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.channels import Channel, channels_from
from app.alerts.format import inr
from app.alerts.job import NOT_SET_UP, AlertOutcome, _send
from app.backtest.strategies import Tier
from app.backups import configured_status
from app.calendar.nse import TradingCalendar, UnknownCalendarYearError
from app.config import Settings
from app.data import store
from app.data.adjust import SHARE_COUNT_ACTIONS, Adjustment, adjust_bars, build_adjustments
from app.data.events import next_results
from app.enums import CorporateActionType
from app.exits.rules import Action, ExitBar, ExitPlan, exit_plan
from app.halt import halt_state
from app.indicators import atr
from app.journal.service import EntryView, entry_views, pending_signals
from app.models import DailyBar, JournalEntry, PaperTrade
from app.settings_store import effective_settings
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
class EntryCheck:
    """A live signal waiting for today's open, re-checked at the pre-open: the real
    account's trade plan (heat, positions, guardrails, results blackout, kill switch)
    and what changed overnight that Jeron can know without live prices."""

    ticker: str
    strategy_key: str
    signal_date: date
    zone_high: Decimal
    stop: Decimal
    shares: int
    skip: list[str] = field(default_factory=list)  # why not to buy; empty: buy
    notes: list[str] = field(default_factory=list)


@dataclass
class PreOpen:
    day: date  # the session the check is for
    data_as_of: date | None
    expected: date  # the session whose close the check needs
    positions: list[PositionCheck]
    paper_open: int
    paper_accounts: int
    entries: list[EntryCheck] = field(default_factory=list)

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


def due_session(calendar: TradingCalendar, at: datetime, daily_at: time) -> date:
    """The newest session whose data the daily run should have by `at` (IST): today
    once the daily time has passed on a trading day, else the session before."""
    at = at.astimezone(IST)
    if is_session(calendar, at.date()) and at.time() >= daily_at:
        return at.date()
    day = at.date() - timedelta(days=1)
    while not is_session(calendar, day):
        day -= timedelta(days=1)
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


def _price_factor_on(adjustments: Sequence[Adjustment], day: date) -> float:
    """The adjustment from `day`'s prices to today's that is not a share-count change
    (rights issues, demergers). Splits and bonuses are already in the journal position
    (`app.journal.basis`), which restates the shares as well as the prices."""
    factor = 1.0
    for adj in adjustments:
        if adj.ex_date > day and adj.action.action_type not in SHARE_COUNT_ACTIONS:
            factor *= float(adj.factor)
    return factor


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
    # An ex-date after the last close isn't in its prices yet (the events say it's coming).
    adjustments = [a for a in build_adjustments(bars, actions) if a.ex_date <= bars[-1].trade_date]
    adjusted = adjust_bars(bars, adjustments)
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
    factor = _price_factor_on(adjustments, pos.first_date)
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
    held = store.held_drops(session, data_as_of) if data_as_of else {}
    for c in checks:
        if c.ticker in held and c.plan is not None:
            # Quality check #9: an unadjusted demerger or rights issue would trip the stop.
            c.problem = (
                f"{held[c.ticker]}; if it is a demerger or rights issue, the stop needs "
                f"adjusting. The rules alone say: {c.plan.action.value}, {c.plan.reason}"
            )
            c.plan = None
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


def entry_checks(session: Session, p: PreOpen, settings: Settings) -> list[EntryCheck]:
    """Re-check every live signal valid for `p.day` that has no journal entry yet. Each
    is planned on the real account as the Trade page would plan it, one after another,
    so two buys together can't pass the heat or position limits that each passes alone.
    Nothing when the prices are stale (the check says so instead)."""
    from app.plan.service import context, plan_for, tier_of  # they build on this module

    if p.stale or p.data_as_of is None:
        return []
    signals = [
        s
        for s in pending_signals(session, since=p.data_as_of, include_research=False)
        if str(s.payload.get("entry_zone", {}).get("valid_until", "")) >= p.day.isoformat()
    ]
    if not signals:
        return []
    held = store.held_drops(session, p.data_as_of)
    today = store.actions_between(
        session, store.NSE_ACTIONS, p.day, p.day, [s.ticker for s in signals]
    )
    added_risk, added_by_tier = Decimal(0), dict[str, int]()
    out = []
    for s in sorted(signals, key=lambda x: (-int(x.payload.get("conviction", 0)), x.ticker)):
        zone = s.payload["entry_zone"]
        check = EntryCheck(
            s.ticker,
            s.strategy_key,
            s.signal_date,
            Decimal(str(zone["high"])),
            Decimal(str(s.payload["stop"]["price"])),
            0,
        )
        tier = tier_of(s.payload.get("tier"))
        ctx = context(session, s.ticker, signal_id=s.signal_id, settings=settings)
        if ctx is None:
            check.skip.append("no prices stored for the stock")
        else:
            account = ctx.account
            if account is not None and added_by_tier:
                by_tier = dict(account.open_by_tier)
                for k, n in added_by_tier.items():
                    by_tier[k] = by_tier.get(k, 0) + n
                account = replace(
                    account,
                    open_by_tier=by_tier,
                    entries_week=account.entries_week + sum(added_by_tier.values()),
                )
            ctx = replace(ctx, open_risk=ctx.open_risk + added_risk, account=account)
            plan = plan_for(ctx, check.zone_high, check.stop, tier)
            check.shares = plan.shares
            check.skip += plan.blockers
            if added_risk and not plan.blockers:
                check.notes.append("planned after the buys above (their risk counted)")
        if s.ticker in held:
            check.skip.append(f"{held[s.ticker]}: check by hand")
        for a in today:
            if a.symbol != s.ticker:
                continue
            if a.action_type == CorporateActionType.DIVIDEND:
                amount = f" {inr(a.amount)}" if a.amount else ""
                check.notes.append(
                    f"ex-dividend{amount} today: expect the open that much lower; zone and "
                    "stop unchanged"
                )
            else:
                check.skip.append(
                    f"{a.action_type.value} ex-date today ({a.raw_text or a.action_type.value}): "
                    "the price resets at the open, so the zone and stop no longer apply"
                )
        if not check.skip:
            added_risk += (check.zone_high - check.stop) * check.shares
            added_by_tier[tier.value] = added_by_tier.get(tier.value, 0) + 1
        out.append(check)
    return out


def _entry_line(e: EntryCheck) -> str:
    head = f"- {e.ticker} ({e.strategy_key}, signal {e.signal_date:%a %-d %b})"
    if e.skip:
        return "\n".join([f"{head}: SKIP", *(f"  {r}" for r in e.skip)])
    lines = [
        f"{head}: buy {e.shares} sh, LIMIT {inr(e.zone_high)}, only if the pre-open price "
        f"is above the stop {inr(e.stop)}; then a GTT stop at {inr(e.stop)}."
    ]
    return "\n".join([*lines, *(f"  {n}" for n in e.notes)])


def broker_stop(c: PositionCheck) -> tuple[int, float] | None:
    """The stop order to keep at the broker (a Zerodha GTT sell) after the next open:
    shares and trigger. A position the plan sells in full needs none; after booking half
    at T1 (the engine sells the lower half), the rest at the plan's stop."""
    if c.plan is None or c.plan.action == Action.SELL_ALL:
        return None
    shares = c.shares - c.shares // 2 if c.plan.action == Action.SELL_HALF else c.shares
    return (shares, c.plan.stop) if shares > 0 else None


def _stop_line(c: PositionCheck) -> str | None:
    order = broker_stop(c)
    if order is None or c.plan is None:
        return None
    shares, trigger = order
    line = f"- {c.ticker}: sell {shares} sh, trigger {inr(round(trigger, 2))}"
    if c.plan.stop_raised and c.plan.stop_before is not None:
        line += f" (CHANGED: raised from {inr(round(c.plan.stop_before, 2))} at the last close)"
    elif c.plan.action == Action.SELL_HALF:
        line += " (after selling half)"
    return line


def backup_note(session: Session, settings: Settings) -> str | None:
    """What is wrong with the backups (app/backups.py), if anything. "No backup yet" is
    only said once the journal has something to lose."""
    status = configured_status(settings.backups_mount, settings.backup_dir)
    if status is None or status.problem is None:
        return None
    if status.newest is None and not session.scalar(select(func.count(JournalEntry.id))):
        return None
    return status.problem


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


def preopen_message(
    p: PreOpen,
    web_url: str = "",
    cash_action: str | None = None,
    calendar_note: str | None = None,
    backup_note: str | None = None,
    tax_notes: Sequence[str] = (),
    halted: str | None = None,
) -> str:
    lines = [f"Jeron pre-open check, {p.day:%a %-d %b %Y}"]
    if halted:
        lines += ["", halted]
    if p.stale:
        when = "never"
        if p.data_as_of:
            # The year only when it isn't this one: a long-stopped install shows its age.
            fmt = "%a %-d %b" if p.data_as_of.year == p.day.year else "%a %-d %b %Y"
            when = f"{p.data_as_of:{fmt}}"
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
        stops = [line for c in p.positions if (line := _stop_line(c))]
        if stops:
            lines += [
                "",
                "STOPS AT THE BROKER (GTT sell; set the limit a little below the trigger "
                "so a fast fall still fills)",
                *stops,
            ]
        problems = [c for c in p.positions if c.plan is None]
        if problems:
            lines += ["", "CHECK BY HAND"]
            lines += [f"- {c.ticker} {c.shares} sh: {c.problem or 'no plan'}" for c in problems]
    if p.entries:
        lines += [
            "",
            "BUYS AT THE OPEN (live signals, re-checked against your account now)",
            "Jeron has no live prices: at 09:08 look at the pre-open price. Above the limit, "
            "don't chase; at or below the stop, or locked at the upper circuit, no trade.",
            *(_entry_line(e) for e in p.entries),
        ]
    if tax_notes and not p.stale:
        lines += ["", "TAX (information only; the exit plan comes first)"]
        lines += [f"- {n}" for n in tax_notes]
    events = [(c.ticker, e) for c in p.positions for e in c.events]
    if events:
        lines += ["", f"EVENTS (next {EVENT_SESSIONS} sessions)"]
        lines += [f"- {t}: {e}" for t, e in events]
    if cash_action and not p.stale:
        lines += ["", "CASH", f"- {cash_action}"]
    if calendar_note:
        lines += ["", "CALENDAR", f"- {calendar_note}"]
    if backup_note:
        lines += ["", "BACKUP", f"- {backup_note}"]
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
    settings = settings or effective_settings(session)
    now = now or datetime.now(IST)
    calendar = TradingCalendar.default()
    day = day or check_day(calendar, now)
    p = build_preopen(session, day, calendar)
    from app.portfolio.service import portfolio  # it builds on this module

    totals = portfolio(session, settings=settings, pre=p).totals
    halt = halt_state(session)
    if halt is None:
        p.entries = entry_checks(session, p, settings)
    text = preopen_message(
        p,
        settings.web_url,
        totals.cash_action,
        calendar.coverage_warning(day),
        backup_note(session, settings),
        totals.tax_notes,
        halt.headline() if halt else None,
    )
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
