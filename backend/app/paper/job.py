"""Paper trading (spec section 7, stage 2): every signal is paper-traded with the
rules that were backtested.

Each strategy version has one active paper account, opened with the grid point the
strategy's latest backtest run chose and the portfolio settings of the day (capital,
risk %, position limits, sector cap, correlation check); the account keeps them.

Every update replays the account with the backtest engine from its first day to the
newest scanned day, on the stored data. The replay is deterministic, so yesterday's
trades come out the same today, and a paper trade follows the backtested rules
exactly. Orders the engine places become signals (spec section 4), stored once and
never changed. Trades and daily equity are re-derived on each update.

A strategy that hasn't passed section 6 is still paper-traded, but its signals are
marked research only: they collect forward evidence and are never alerted.
"""

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import numpy as np
from pydantic import ValidationError
from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.backtest.costs import CostModel
from app.backtest.engine import Order, PortfolioRules, SimResult, Skip, Trade, Variant, simulate
from app.backtest.job import load_inputs
from app.backtest.market import Market, build_market
from app.backtest.stats import curve_stats, drawdown_series, risk_profile, trade_stats
from app.backtest.strategies import STRATEGIES, Strategy, Tier, params_label
from app.calendar.nse import TradingCalendar, UnknownCalendarYearError
from app.config import Settings
from app.data import store
from app.models import (
    BacktestRun,
    PaperAccount,
    PaperDay,
    PaperEvent,
    PaperTrade,
    ScanRun,
    SignalRecord,
)
from app.paper.proposals import FORWARD_SESSIONS, signal_context
from app.scan.job import LOOKBACK_SESSIONS
from app.scan.score import SCORE_VERSION
from app.settings_store import effective_settings
from app.signals.build import IST, SignalContext, backtest_stats, build_signal

Log = Callable[[str], None]
# The correlation check (spec section 5: "3 banks != 3 separate trades"): a stock may
# move with at most one stock already held.
MAX_CORRELATED = 2


def _quiet(_: str) -> None:
    pass


def portfolio_rules(
    settings: Settings, tier: Tier, results_blackout: bool = False
) -> PortfolioRules:
    max_positions = {
        Tier.SWING: settings.max_positions_swing,
        Tier.POSITIONAL: settings.max_positions_positional,
        Tier.INVEST: settings.max_positions_invest,
    }[tier]
    return PortfolioRules(
        capital=settings.capital,
        risk_pct=settings.risk_pct,
        max_positions=max_positions,
        sector_cap_pct=settings.sector_cap_pct,
        max_correlated=MAX_CORRELATED,
        results_blackout=results_blackout,
    )


@dataclass
class AccountOutcome:
    strategy_key: str
    account_id: int | None
    status: str  # "ok", "no_backtest", "retired"
    new_signals: int = 0
    open_positions: int = 0
    equity: float = 0.0
    notes: list[str] = field(default_factory=list)


@dataclass
class PaperOutcome:
    trade_date: date
    status: str  # "ok" or "blocked"
    reasons: list[str] = field(default_factory=list)
    accounts: list[AccountOutcome] = field(default_factory=list)


def blocking_reasons(session: Session, day: date) -> list[str]:
    """The paper job runs only on a day the scan ran: the same data checks apply."""
    run = session.scalar(
        select(ScanRun).where(ScanRun.trade_date == day, ScanRun.score_version == SCORE_VERSION)
    )
    if run is None:
        return [f"No scan for {day}; run the scan first."]
    if run.status != "ok":
        return [f"The scan for {day} was blocked: {r}" for r in run.details.get("reasons", [])]
    return []


def latest_scan_date(session: Session) -> date | None:
    return session.scalar(
        select(ScanRun.trade_date)
        .where(ScanRun.status == "ok", ScanRun.score_version == SCORE_VERSION)
        .order_by(ScanRun.trade_date.desc())
        .limit(1)
    )


def day_signals(session: Session, day: date) -> list[tuple[SignalRecord, str]]:
    """The day's stored signals with their strategy key, live ones first."""
    return [
        (r, key)
        for r, key in session.execute(
            select(SignalRecord, PaperAccount.strategy_key)
            .join(PaperAccount, PaperAccount.id == SignalRecord.account_id)
            .where(SignalRecord.signal_date == day)
            .order_by(SignalRecord.research_only, PaperAccount.id, SignalRecord.ticker)
        )
    ]


def latest_backtest(session: Session, strategy: Strategy) -> BacktestRun | None:
    return session.scalar(
        select(BacktestRun)
        .where(BacktestRun.strategy_version == strategy.version)
        .order_by(BacktestRun.id.desc())
        .limit(1)
    )


def active_account(session: Session, strategy: Strategy) -> PaperAccount | None:
    return session.scalar(
        select(PaperAccount)
        .where(PaperAccount.strategy_version == strategy.version, PaperAccount.status == "active")
        .order_by(PaperAccount.id.desc())
        .limit(1)
    )


def retired_account(session: Session, strategy: Strategy) -> PaperAccount | None:
    """The weekly revalidation retired this strategy version (spec section 6)."""
    return session.scalar(
        select(PaperAccount)
        .where(PaperAccount.strategy_version == strategy.version, PaperAccount.status == "retired")
        .order_by(PaperAccount.id.desc())
        .limit(1)
    )


def open_account(
    session: Session, strategy: Strategy, run: BacktestRun, start: date, settings: Settings
) -> PaperAccount:
    params = {k: float(v) for k, v in run.summary["schedule"][-1]["params"].items()}
    rules = portfolio_rules(settings, strategy.tier, strategy.results_blackout)
    account = PaperAccount(
        strategy_key=strategy.key,
        strategy_version=strategy.version,
        params=params,
        params_label=params_label(params),
        backtest_run_id=run.id,
        live_eligible=run.live_eligible,
        start_date=start,
        capital=Decimal(f"{rules.capital:.2f}"),
        rules=asdict(rules),
        status="active",
        summary={},
    )
    session.add(account)
    session.flush()
    return account


def next_session(calendar: TradingCalendar, day: date) -> tuple[date, str | None]:
    """The session after `day`, and a note when the holiday list doesn't cover it
    (then the next weekday is assumed)."""
    try:
        return calendar.next_trading_day(day), None
    except UnknownCalendarYearError:
        nxt = day + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        return nxt, (
            f"NSE's {nxt.year} holiday list isn't in the calendar, so the entry zone is dated "
            f"the next weekday ({nxt}); if that is a holiday, it holds for the next session."
        )


def _raw(m: Market, s: int, t: int, value: float) -> Decimal:
    """An adjusted price as rupees per share on day t."""
    return Decimal(f"{value / m.factor[s, t]:.4f}")


def _money(value: float) -> Decimal:
    return Decimal(f"{value:.2f}")


def _trade_row(
    account_id: int,
    seq: int,
    trade: Trade,
    m: Market,
    end: int,
    signal_ids: dict[tuple[date, str], UUID],
) -> dict[str, Any]:
    s, days = trade.s, m.days
    is_open = not trade.exits or trade.remaining > 1e-9
    traded = np.flatnonzero(~np.isnan(m.close[s, : end + 1]))
    mark_day = int(traded[-1]) if len(traded) else trade.entry_day
    mark = float(m.close[s, mark_day])
    # An open trade's P&L marks the shares still held at the close, before the
    # costs of selling them.
    pnl = trade.net_pnl + (trade.remaining * (mark - trade.entry) if is_open else 0.0)
    exit_day = trade.exit_day
    return {
        "account_id": account_id,
        "seq": seq,
        "signal_id": signal_ids.get((days[trade.signal_day], trade.symbol)),
        "ticker": trade.symbol,
        "status": "open" if is_open else "closed",
        "signal_date": days[trade.signal_day],
        "entry_date": days[trade.entry_day],
        "entry_price": _raw(m, s, trade.entry_day, trade.entry),
        "initial_stop": _raw(m, s, trade.entry_day, trade.stop0),
        "target_t1": _raw(m, s, trade.entry_day, trade.t1),
        "shares": trade.raw_shares,
        "current_stop": _raw(m, s, end, trade.stop) if is_open else None,
        "last_close": _raw(m, s, mark_day, mark) if is_open else None,
        "shares_held": round(trade.remaining * m.factor[s, end]) if is_open else 0,
        "exit_date": None if is_open else days[exit_day],
        "exit_price": None if is_open else _raw(m, s, exit_day, trade.exit_price),
        "exit_reason": None if is_open else trade.exit_reason,
        "charges": _money(trade.charges),
        "dividends": _money(trade.dividends),
        "net_pnl": _money(pnl),
        "r_multiple": Decimal(f"{pnl / trade.risk if trade.risk > 0 else 0.0:.4f}"),
        "sessions": (end if is_open else exit_day) - trade.entry_day,
        "exits": [
            {
                "date": str(days[f.day]),
                "price": str(_raw(m, s, f.day, f.price)),
                "shares": round(f.shares * m.factor[s, f.day]),
                "reason": f.reason,
            }
            for f in trade.exits
        ],
        "context": signal_context(m, s, trade.signal_day),
    }


# Skips decided at the open after the signal; the rest are decided at the signal close.
FILL_DAY_SKIPS = (
    "did not trade the next day",
    "locked at the upper circuit",
    "opened below the stop",
    "opened above the entry zone",
    "not enough cash",
)


def skip_reason(reason: str) -> str:
    """A skip's reason without the names and numbers that make each one different."""
    if reason.startswith("sector "):
        return "sector cap"
    if reason.startswith("moves with "):
        return "moves with a stock held"
    if reason.startswith("already ordered by"):
        return "already ordered"
    return reason


def _signal_day(m: Market, skip: Skip) -> int:
    return skip.day - 1 if skip.reason in FILL_DAY_SKIPS else skip.day


def forward_move_r(m: Market, s: int, t: int, stop_atr: float) -> float | None:
    """The close `FORWARD_SESSIONS` sessions after day t against day t's close, in R
    (a stop `stop_atr` x ATR away = 1R). None when those sessions haven't happened."""
    later = t + FORWARD_SESSIONS
    if later >= len(m.days):
        return None
    c0, c1, atr = float(m.close[s, t]), float(m.close[s, later]), float(m.atr14[s, t])
    if not (np.isfinite(c0) and np.isfinite(c1) and np.isfinite(atr)) or atr <= 0:
        return None
    return (c1 - c0) / (stop_atr * atr)


def missed_summary(
    m: Market, sim: SimResult, trades: Sequence[Trade], start: int, end: int, stop_atr: float
) -> dict[str, Any]:
    """Signals the rules skipped, by reason, with the stock's move over the next
    `FORWARD_SESSIONS` sessions; the same move for the signals that were traded, so
    the two can be compared. Only sessions up to `end` are used."""

    def line(moves: list[float | None], count: int) -> dict[str, Any]:
        known = [v for v in moves if v is not None]
        return {
            "count": count,
            "measured": len(known),
            "avg_move_r": round(sum(known) / len(known), 4) if known else None,
            "share_up": round(sum(v > 0 for v in known) / len(known), 4) if known else None,
        }

    def move(s: int, t: int) -> float | None:
        return forward_move_r(m, s, t, stop_atr) if t + FORWARD_SESSIONS <= end else None

    by: dict[str, list[float | None]] = {}
    for skip in sim.skipped:
        t = _signal_day(m, skip)
        if t < start:
            continue
        by.setdefault(skip_reason(skip.reason), []).append(move(skip.s, t))
    taken = [move(tr.s, tr.signal_day) for tr in trades]
    return {
        "forward_sessions": FORWARD_SESSIONS,
        "taken": line(taken, len(taken)),
        "skipped": {
            reason: line(moves, len(moves))
            for reason, moves in sorted(by.items(), key=lambda kv: -len(kv[1]))
        },
    }


def performance_summary(
    m: Market, sim: SimResult, start: int, end: int, rules: PortfolioRules
) -> dict[str, Any]:
    """Return and risk of the account's curve against Nifty 500 over the same sessions."""
    index = m.nifty500[start : end + 1]
    known = index[np.isfinite(index)]
    return {
        "curve": curve_stats(sim.equity, rules.cash_rate_pct).to_dict(),
        "profile": risk_profile(sim.equity, sim.cash, sim.trades, rules.cash_rate_pct).to_dict(),
        "benchmark": curve_stats(known, rules.cash_rate_pct).to_dict() if len(known) else None,
        "cash_rate_pct": rules.cash_rate_pct,
    }


def audit_events(
    account_id: int,
    m: Market,
    trades: Sequence[Trade],
    sim: SimResult,
    start: int,
    signals: dict[tuple[date, str], SignalRecord],
    now: datetime,
) -> list[dict[str, Any]]:
    """Every signal, entry, exit and skip the replay shows, as audit rows; those
    already stored are left as they were (`record_events`)."""
    days = m.days
    rows: list[dict[str, Any]] = []

    def add(kind: str, t: int, ticker: str, ref: str, detail: dict[str, Any]) -> None:
        rows.append(
            {
                "account_id": account_id,
                "kind": kind,
                "event_date": days[t],
                "ticker": ticker,
                "ref": ref,
                "detail": detail,
                "recorded_at": now,
            }
        )

    for (signal_date, ticker), rec in signals.items():
        payload = rec.payload
        rows.append(
            {
                "account_id": account_id,
                "kind": "signal",
                "event_date": signal_date,
                "ticker": ticker,
                "ref": str(rec.signal_id),
                "detail": {
                    "entry_zone": payload.get("entry_zone"),
                    "stop": (payload.get("stop") or {}).get("price"),
                    "t1": (payload.get("targets") or {}).get("t1"),
                    "shares": payload.get("shares"),
                    "why": payload.get("why"),
                    "research_only": rec.research_only,
                },
                "recorded_at": now,
            }
        )
    for tr in trades:
        s, ref = tr.s, str(days[tr.signal_day])
        add(
            "entry",
            tr.entry_day,
            tr.symbol,
            ref,
            {
                "price": str(_raw(m, s, tr.entry_day, tr.entry)),
                "shares": tr.raw_shares,
                "stop": str(_raw(m, s, tr.entry_day, tr.stop0)),
                "charges": round(tr.entry_charges, 2),
            },
        )
        for i, f in enumerate(tr.exits):
            last = i == len(tr.exits) - 1 and tr.remaining <= 1e-9
            add(
                "exit" if last else "partial_exit",
                f.day,
                tr.symbol,
                f"{ref}/{i + 1}",
                {
                    "price": str(_raw(m, s, f.day, f.price)),
                    "shares": round(f.shares * m.factor[s, f.day]),
                    "reason": f.reason,
                    "charges": round(f.charges, 2),
                },
            )
    for skip in sim.skipped:
        if _signal_day(m, skip) < start:
            continue
        add("skip", skip.day, m.symbols[skip.s], skip_reason(skip.reason), {"reason": skip.reason})
    return rows


def record_events(session: Session, rows: Sequence[dict[str, Any]]) -> int:
    """Store the audit rows not stored yet; returns how many were new."""
    new = 0
    for i in range(0, len(rows), 1000):
        result = session.execute(
            pg_insert(PaperEvent)
            .values(list(rows[i : i + 1000]))
            .on_conflict_do_nothing(
                index_elements=["account_id", "kind", "event_date", "ticker", "ref"]
            )
            .returning(PaperEvent.id)
        )
        new += len(result.all())
    return new


def order_notes(
    m: Market, sim: SimResult, orders: Sequence[Order], rules: PortfolioRules
) -> dict[int, list[str]]:
    """Per pending order: the portfolio heat with it (warned at 5%) and whether its
    sector could be checked."""
    notes: dict[int, list[str]] = {}
    equity = float(sim.equity[-1])
    heat = float(sim.heat_pct[-1]) / 100 * equity
    for order in orders:
        n: list[str] = []
        heat += (
            (order.zone_high - order.stop) * order.raw_shares / m.factor[order.s, order.signal_day]
        )
        pct = heat / equity * 100 if equity > 0 else 0.0
        if pct >= rules.heat_warn_pct:
            n.append(
                f"Portfolio heat would be {pct:.1f}% with this trade (warning at "
                f"{rules.heat_warn_pct:g}%, new entries blocked above {rules.heat_block_pct:g}%)."
            )
        if not m.sectors[order.s]:
            n.append(
                "No sector known (not in the Nifty 500 list), so the sector cap wasn't checked."
            )
        notes[id(order)] = n
    return notes


def update_account(
    session: Session,
    account: PaperAccount,
    market: Market,
    day: date,
    calendar: TradingCalendar,
    run: BacktestRun,
    now: datetime,
) -> AccountOutcome:
    strategy = STRATEGIES[account.strategy_key]
    # Accounts opened before engine-v3 stored neither rule and keep engine-v2's fill and
    # no band check, so their replay doesn't change.
    rules = PortfolioRules(**{"zone_touch_fill": True, "min_band_pct": None, **account.rules})
    costs = CostModel()
    m = market
    start, end = m.day_index(account.start_date), m.day_index(day)
    params = {k: float(v) for k, v in account.params.items()}
    variant = Variant(
        account.params_label, params, strategy.entries(m, params), strategy.exits(m, params)
    )
    sim = simulate(
        m,
        strategy.tier,
        [(start, variant)],
        start,
        end,
        rules,
        costs,
        close_at_end=False,
        orders_on_last_day=True,
    )

    recorded = {
        (r.signal_date, r.ticker): r
        for r in session.scalars(select(SignalRecord).where(SignalRecord.account_id == account.id))
    }
    stats = backtest_stats(run.summary)
    notes_for = order_notes(m, sim, sim.pending, rules)
    notes: list[str] = []
    new = 0
    for order in sim.orders:
        key = (m.days[order.signal_day], m.symbols[order.s])
        if key in recorded:
            continue
        signal_date = key[0]
        valid_until, calendar_note = next_session(calendar, signal_date)
        ctx = SignalContext(
            strategy=strategy,
            params=params,
            rules=rules,
            costs=costs,
            backtest=stats,
            research_only=not account.live_eligible,
            created_at=now,
            next_session=valid_until,
            notes=notes_for.get(id(order), []) + ([calendar_note] if calendar_note else []),
        )
        try:
            signal = build_signal(m, order, ctx)
        except ValidationError as exc:
            reason = "; ".join(e["msg"] for e in exc.errors())
            notes.append(f"Rejected signal {key[1]} on {signal_date}: {reason}")
            continue
        row = SignalRecord(
            signal_id=signal.signal_id,
            version=1,
            account_id=account.id,
            ticker=signal.ticker,
            signal_date=signal_date,
            research_only=signal.research_only,
            late=signal_date < day,
            payload=signal.model_dump(mode="json"),
            created_at=now,
        )
        session.add(row)
        recorded[key] = row
        new += 1
    replayed = {(m.days[o.signal_day], m.symbols[o.s]) for o in sim.orders}
    for (signal_date, ticker), _ in sorted(recorded.items()):
        if signal_date <= day and (signal_date, ticker) not in replayed:
            notes.append(
                f"The replay no longer gives the {signal_date} signal for {ticker} "
                "(the stored data changed since); the signal is kept as issued."
            )
    session.flush()

    signal_ids = {k: r.signal_id for k, r in recorded.items()}
    trades = sorted(
        [*sim.trades, *sim.open_trades], key=lambda tr: (tr.entry_day, tr.symbol, tr.signal_day)
    )
    session.execute(delete(PaperTrade).where(PaperTrade.account_id == account.id))
    rows = [_trade_row(account.id, i, tr, m, end, signal_ids) for i, tr in enumerate(trades, 1)]
    if rows:
        session.execute(insert(PaperTrade), rows)

    dd = drawdown_series(sim.equity)
    open_counts = np.zeros(end - start + 1, dtype=int)
    closed_ids = {id(tr) for tr in sim.trades}
    for tr in trades:
        last = tr.exit_day - 1 if id(tr) in closed_ids else end
        open_counts[tr.entry_day - start : max(last, tr.entry_day) - start + 1] += 1
    session.execute(delete(PaperDay).where(PaperDay.account_id == account.id))
    session.execute(
        insert(PaperDay),
        [
            {
                "account_id": account.id,
                "trade_date": m.days[start + i],
                "equity": _money(float(v)),
                "drawdown_pct": Decimal(f"{dd[i]:.3f}"),
                "heat_pct": Decimal(f"{sim.heat_pct[i]:.3f}"),
                "open_positions": int(open_counts[i]),
            }
            for i, v in enumerate(sim.equity)
        ],
    )

    closed_stats = trade_stats(sim.trades)
    record_events(session, audit_events(account.id, m, trades, sim, start, recorded, now))
    today_skips = Counter(s.reason for s in sim.skipped if s.day == end)
    latest = latest_backtest_params(session, strategy)
    if latest is not None and latest != account.params_label:
        notes.append(
            f"The latest backtest chose {latest}; this account keeps {account.params_label}. "
            "Run `paper --restart` to open a new account with it."
        )
    equity = float(sim.equity[-1])
    account.last_date = day
    account.summary = {
        "as_of": str(day),
        "equity": round(equity, 2),
        "return_pct": round((equity / rules.capital - 1) * 100, 3),
        "drawdown_pct": round(float(dd[-1]), 3),
        "max_drawdown_pct": round(float(dd.max()), 3),
        "heat_pct": round(float(sim.heat_pct[-1]), 3),
        "open_positions": len(sim.open_trades),
        "pending_orders": len(sim.pending),
        "closed_trades": closed_stats.to_dict(),
        "skipped_today": dict(today_skips.most_common()),
        "brake_events": [{"date": str(m.days[t]), "event": e} for t, e in sim.brake_events],
        "cost_model": costs.name,
        "performance": performance_summary(m, sim, start, end, rules),
        "missed": missed_summary(m, sim, trades, start, end, params["stop_atr"]),
        "notes": notes,
    }
    session.commit()
    return AccountOutcome(strategy.key, account.id, "ok", new, len(sim.open_trades), equity, notes)


def latest_backtest_params(session: Session, strategy: Strategy) -> str | None:
    run = latest_backtest(session, strategy)
    if run is None:
        return None
    return params_label({k: float(v) for k, v in run.summary["schedule"][-1]["params"].items()})


def run_paper(
    session: Session,
    day: date | None = None,
    keys: Sequence[str] | None = None,
    *,
    restart: bool = False,
    settings: Settings | None = None,
    calendar: TradingCalendar | None = None,
    market: Market | None = None,
    now: datetime | None = None,
    log: Log = _quiet,
) -> PaperOutcome:
    """Update every strategy's paper account to `day` (default: the newest scanned
    day), opening accounts that don't exist yet."""
    settings = settings or effective_settings(session)
    calendar = calendar or TradingCalendar.default()
    now = now or datetime.now(IST)
    day = day or latest_scan_date(session)
    if day is None:
        reason = "No scan has run yet; run the scan first."
        log(f"Paper trading blocked: {reason}")
        return PaperOutcome(date.min, "blocked", [reason])
    reasons = blocking_reasons(session, day)
    if reasons:
        for reason in reasons:
            log(f"Paper trading blocked: {reason}")
        return PaperOutcome(day, "blocked", reasons)

    outcome = PaperOutcome(day, "ok")
    work: list[tuple[PaperAccount, BacktestRun]] = []
    for key in keys or list(STRATEGIES):
        strategy = STRATEGIES[key]
        account = active_account(session, strategy)
        if account is not None and restart:
            account.status = "closed"
            account = None
        if account is not None:
            if account.start_date > day:
                raise ValueError(f"{key}: the paper account starts on {account.start_date}")
            work.append((account, session.get_one(BacktestRun, account.backtest_run_id)))
            continue
        retired = retired_account(session, strategy)
        if retired is not None and not restart:
            message = (
                f"Retired on {retired.retired_on} ({retired.retired_reason}); a new strategy "
                "version is needed to paper-trade it again."
            )
            log(f"{key}: {message}")
            outcome.accounts.append(AccountOutcome(key, retired.id, "retired", notes=[message]))
            continue
        run = latest_backtest(session, strategy)
        if run is None:
            message = "No backtest run for this strategy version; run the backtest first."
            log(f"{key}: {message}")
            outcome.accounts.append(AccountOutcome(key, None, "no_backtest", notes=[message]))
            continue
        account = open_account(session, strategy, run, day, settings)
        log(f"{key}: opened paper account {account.id} from {day} ({account.params_label})")
        work.append((account, run))
    session.commit()
    if not work:
        return outcome

    if market is None:
        first = min(a.start_date for a, _ in work)
        window_start = _window_start(session, first)
        market = build_market(load_inputs(session, window_start, day))
    for account, run in work:
        result = update_account(session, account, market, day, calendar, run, now)
        outcome.accounts.append(result)
        stage = "paper" if account.live_eligible else "research only"
        log(
            f"{account.strategy_key} ({stage}): {result.new_signals} new signals, "
            f"{result.open_positions} open positions, equity {result.equity:,.0f}"
        )
        for note in result.notes:
            log(f"  - {note}")
    return outcome


def _window_start(session: Session, first: date) -> date:
    """Enough sessions before an account's first day for every indicator to settle
    (as the scan loads)."""
    days = store.ok_dates(session, store.NSE_BARS, end=first)
    return days[-LOOKBACK_SESSIONS] if len(days) >= LOOKBACK_SESSIONS else days[0]
