"""The weekly summary (spec section 8) and the weekly revalidation (spec section 6).

Summary, after the last session of each week:
- my real edge: closed trades, win rate, average R and P&L, this week and to date;
- my mistakes, found from the data: stop moved below the signal's, exits earlier than
  the rules (paper held on and did better), signals taken late, skipped winners, and
  trades I marked as deviating from the plan;
- what strict rule-following would have made: the paper results of the same signals.

Revalidation: a strategy whose rolling 50-trade expectancy (paper, or my real trades)
falls below 0, or whose paper drawdown exceeds 1.5 x its backtest maximum, is retired:
its paper account stops issuing signals, and the summary says so. Retired accounts are
kept, never deleted.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.channels import Channel, channels_from
from app.alerts.format import inr
from app.alerts.job import NOT_SET_UP, AlertOutcome, _send
from app.config import Settings, get_settings
from app.journal.service import EntryView, entry_views
from app.models import BacktestRun, PaperAccount, PaperDay, PaperTrade
from app.signals.build import IST

Log = Callable[[str], None]
ROLLING_TRADES = 50
DRAWDOWN_MULTIPLE = 1.5
LATE_DAYS = 2  # a first buy this many calendar days after the paper entry is late


def _quiet(_: str) -> None:
    pass


@dataclass
class Edge:
    trades: int = 0
    wins: int = 0
    r_total: float = 0.0
    pnl: Decimal = Decimal(0)

    def add(self, r: float | None, pnl: Decimal) -> None:
        self.trades += 1
        self.wins += pnl > 0
        self.r_total += r or 0.0
        self.pnl += pnl

    def line(self, label: str) -> str:
        if not self.trades:
            return f"{label}: no closed trades"
        return (
            f"{label}: {self.trades} closed, {self.wins} won ({self.wins / self.trades:.0%}), "
            f"average {self.r_total / self.trades:+.2f}R, P&L {inr(self.pnl, 0)}"
        )


@dataclass
class Retirement:
    account_id: int
    strategy_version: str
    reason: str


@dataclass
class Weekly:
    week_start: date
    day: date
    week: Edge
    to_date: Edge
    mistakes: list[str] = field(default_factory=list)
    mine_r: float = 0.0  # my closed R this week on signals paper also closed
    strict_r: float = 0.0  # paper's R on the same signals plus the ones I skipped
    strict_count: int = 0
    retired: list[Retirement] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _signal_stop(v: EntryView) -> Decimal | None:
    if v.signal is None:
        return None
    return Decimal(str(v.signal.payload["stop"]["price"]))


def revalidate(session: Session, day: date, retire: bool = True) -> list[Retirement]:
    """Check every active account; retire those that broke a rule."""
    out = []
    views = entry_views(session)
    signal_account = {
        sid: aid
        for sid, aid in session.execute(
            select(PaperTrade.signal_id, PaperTrade.account_id).where(
                PaperTrade.signal_id.is_not(None)
            )
        )
    }
    for account in session.scalars(
        select(PaperAccount).where(PaperAccount.status == "active").order_by(PaperAccount.id)
    ):
        reasons = []
        closed = session.scalars(
            select(PaperTrade.r_multiple)
            .where(PaperTrade.account_id == account.id, PaperTrade.status == "closed")
            .order_by(PaperTrade.exit_date.desc(), PaperTrade.seq.desc())
            .limit(ROLLING_TRADES)
        ).all()
        if len(closed) >= ROLLING_TRADES and sum(closed) < 0:
            reasons.append(
                f"paper rolling {ROLLING_TRADES}-trade expectancy "
                f"{float(sum(closed)) / ROLLING_TRADES:+.2f}R"
            )
        real = sorted(
            (
                v
                for v in views
                if v.signal is not None
                and v.position.status == "closed"
                and v.position.r_multiple is not None
                and signal_account.get(v.signal.signal_id) == account.id
            ),
            key=lambda v: v.position.last_date or date.min,
        )[-ROLLING_TRADES:]
        if len(real) >= ROLLING_TRADES:
            mean = sum(float(v.position.r_multiple or 0) for v in real) / ROLLING_TRADES
            if mean < 0:
                reasons.append(f"my rolling {ROLLING_TRADES}-trade expectancy {mean:+.2f}R")
        run = session.get(BacktestRun, account.backtest_run_id)
        backtest_dd = (
            run.summary.get("out_of_sample", {}).get("curve", {}).get("max_drawdown_pct")
            if run
            else None
        )
        worst = session.scalar(
            select(func.max(PaperDay.drawdown_pct)).where(PaperDay.account_id == account.id)
        )
        if backtest_dd and worst is not None and float(worst) > DRAWDOWN_MULTIPLE * backtest_dd:
            reasons.append(
                f"paper drawdown {float(worst):.1f}% above {DRAWDOWN_MULTIPLE:g} x the "
                f"backtest's {backtest_dd:.1f}%"
            )
        if reasons:
            reason = "; ".join(reasons)
            out.append(Retirement(account.id, account.strategy_version, reason))
            if retire:
                account.status = "retired"
                account.retired_reason = reason[:300]
                account.retired_on = day
    session.commit()
    return out


def build_weekly(session: Session, day: date, retire: bool = True) -> Weekly:
    start = week_start(day)
    w = Weekly(start, day, Edge(), Edge())
    views = entry_views(session)
    paper_by_signal = {
        t.signal_id: t
        for t in session.scalars(
            select(PaperTrade)
            .join(PaperAccount, PaperAccount.id == PaperTrade.account_id)
            .where(PaperTrade.signal_id.is_not(None))
        )
    }
    live_accounts = set(
        session.scalars(select(PaperAccount.id).where(PaperAccount.live_eligible.is_(True)))
    )
    for v in views:
        p = v.position
        closed = p.status == "closed" and p.last_date is not None and p.last_date <= day
        this_week = closed and p.last_date is not None and p.last_date >= start
        r = float(p.r_multiple) if p.r_multiple is not None else None
        if closed:
            w.to_date.add(r, p.realised_pnl)
        if this_week:
            w.week.add(r, p.realised_pnl)
        paper = paper_by_signal.get(v.entry.signal_id) if v.entry.signal_id else None
        stop = _signal_stop(v)
        if (
            v.entry.stop is not None
            and stop is not None
            and v.entry.stop < stop
            and p.bought
            and (p.status == "open" or this_week)
        ):
            w.mistakes.append(
                f"{v.entry.ticker}: stop {inr(v.entry.stop)} is below the signal's {inr(stop)}"
            )
        if this_week and v.entry.followed_plan is False:
            w.mistakes.append(f"{v.entry.ticker}: marked as not following the plan")
        if paper is None:
            continue
        paper_closed = (
            paper.status == "closed" and paper.exit_date is not None and paper.exit_date <= day
        )
        # Compared in the week the second of the two trades closed.
        settled = (
            max(p.last_date, paper.exit_date)
            if closed and paper_closed and p.last_date and paper.exit_date
            else None
        )
        if settled is not None and start <= settled <= day and r is not None:
            w.mine_r += r
            w.strict_r += float(paper.r_multiple)
            w.strict_count += 1
            if (
                p.last_date is not None
                and paper.exit_date is not None
                and p.last_date < paper.exit_date
                and r < float(paper.r_multiple)
            ):
                w.mistakes.append(
                    f"{v.entry.ticker}: sold on {p.last_date:%d %b}, before the rules did "
                    f"({paper.exit_date:%d %b}); {r:+.2f}R against paper's "
                    f"{float(paper.r_multiple):+.2f}R"
                )
        if (
            p.first_date is not None
            and p.first_date >= start
            and (p.first_date - paper.entry_date).days >= LATE_DAYS
        ):
            w.mistakes.append(
                f"{v.entry.ticker}: bought {(p.first_date - paper.entry_date).days} days after "
                "the paper entry"
            )
    # Skipped (or never decided) signals of live strategies whose paper trade closed
    # this week.
    decided = {v.entry.signal_id: v for v in views if v.entry.signal_id}
    for signal_id, paper in paper_by_signal.items():
        if signal_id is None:
            continue
        if (
            paper.account_id not in live_accounts
            or paper.status != "closed"
            or paper.exit_date is None
            or not start <= paper.exit_date <= day
        ):
            continue
        mine = decided.get(signal_id)
        if mine is not None and mine.position.bought:
            continue
        r = float(paper.r_multiple)
        w.strict_r += r
        w.strict_count += 1
        if r > 0:
            what = "skipped" if mine is not None else "not acted on"
            w.mistakes.append(f"{paper.ticker}: {what}; paper made {r:+.2f}R")
    w.retired = revalidate(session, day, retire)
    return w


def weekly_message(w: Weekly, web_url: str = "") -> str:
    lines = [
        f"Jeron weekly summary, week of {w.week_start:%a %-d %b %Y}",
        "",
        "MY REAL EDGE",
        w.week.line("This week"),
        w.to_date.line("To date"),
    ]
    lines += ["", "MISTAKES"]
    lines += [f"- {m}" for m in w.mistakes] or ["None found in the data."]
    lines += ["", "STRICT RULE-FOLLOWING"]
    if w.strict_count:
        lines.append(
            f"Every signal of a live strategy, traded by the rules: {w.strict_r:+.2f}R over "
            f"{w.strict_count} trades closed this week. Mine on the same signals: "
            f"{w.mine_r:+.2f}R."
        )
    else:
        lines.append("No signals of live strategies closed this week.")
    if w.retired:
        lines += ["", "RETIRED BY THE WEEKLY REVALIDATION"]
        lines += [f"- {r.strategy_version}: {r.reason}" for r in w.retired]
    if web_url:
        lines += ["", f"Compare: {web_url.rstrip('/')}/compare"]
    return "\n".join(lines)


def run_weekly(
    session: Session,
    day: date | None = None,
    *,
    settings: Settings | None = None,
    channels: Sequence[Channel] | None = None,
    now: datetime | None = None,
    send: bool = True,
    log: Log = _quiet,
) -> tuple[Weekly, AlertOutcome]:
    settings = settings or get_settings()
    now = now or datetime.now(IST)
    day = day or now.astimezone(IST).date()
    w = build_weekly(session, day)
    text = weekly_message(w, settings.web_url)
    log(text)
    outcome = AlertOutcome(day, "ok")
    if not send:
        return w, outcome
    channels = channels_from(settings) if channels is None else channels
    if not channels:
        log(NOT_SET_UP)
        outcome.status = "not_configured"
        return w, outcome
    year, week, _ = day.isocalendar()
    _send(
        session, channels, f"weekly:{year}-W{week:02d}", "weekly", text,
        f"Jeron weekly summary {w.week_start}", outcome, now, day,
    )  # fmt: skip
    return w, outcome
