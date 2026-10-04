"""Backtest vs paper vs real from the database, one row per paper account (a strategy
version with its parameters), plus my trades without a signal."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.compare import (
    ClosedTrade,
    Divergence,
    Gate,
    Pair,
    Record,
    divergence,
    paper_gate,
    real_gate,
    record,
    stage,
)
from app.journal.service import EntryView, entry_views
from app.models import BacktestRun, BacktestTrade, PaperAccount, PaperDay, PaperTrade, SignalRecord


@dataclass
class StrategyCompare:
    account_id: int | None  # None: my trades without a signal
    strategy_key: str | None
    strategy_version: str | None
    params_label: str | None
    live_eligible: bool
    account_status: str | None
    backtest_run_id: int | None
    backtest: Record | None
    paper: Record | None
    real: Record
    paper_gate: Gate | None
    real_gate: Gate | None
    paper_range: tuple[float, float] | None
    real_range: tuple[float, float] | None
    stage: str
    divergence: Divergence | None


def _num(value: Any) -> float | None:
    if value is None or value in ("inf", "-inf"):
        return None
    return float(value)


def backtest_record(run: BacktestRun) -> Record:
    oos = run.summary.get("out_of_sample", {})
    t, curve = oos.get("trades", {}), oos.get("curve", {})
    periods = run.summary.get("periods", {}).get("out_of_sample") or [None, None]
    return Record(
        trades=int(t.get("trades", 0)),
        win_rate=_num(t.get("win_rate")),
        expectancy_r=_num(t.get("expectancy_r")),
        profit_factor=_num(t.get("profit_factor")),
        avg_sessions=_num(t.get("avg_sessions")),
        max_drawdown=_num(curve.get("max_drawdown_pct")),
        drawdown_unit="%",
        start=date.fromisoformat(periods[0]) if periods[0] else None,
        end=date.fromisoformat(periods[1]) if periods[1] else None,
    )


def _sessions(start: date | None, end: date | None) -> int:
    if start is None or end is None:
        return 0
    return int(np.busday_count(start, end))


def _real(views: list[EntryView]) -> list[ClosedTrade]:
    out = []
    for v in views:
        p = v.position
        if p.status == "closed" and p.r_multiple is not None and p.last_date is not None:
            out.append(
                ClosedTrade(
                    float(p.r_multiple),
                    float(p.realised_pnl),
                    _sessions(p.first_date, p.last_date),
                    p.last_date,
                )
            )
    return out


def _first_buy(views: list[EntryView]) -> date | None:
    days = [v.position.first_date for v in views if v.position.first_date is not None]
    return min(days) if days else None


def compare(session: Session, as_of: date | None = None) -> list[StrategyCompare]:
    as_of = as_of or date.today()
    views = [v for v in entry_views(session) if v.position.bought > 0 or v.signal is not None]
    by_signal = {v.entry.signal_id: v for v in views if v.entry.signal_id}
    signal_account = {
        sid: aid
        for sid, aid in session.execute(select(SignalRecord.signal_id, SignalRecord.account_id))
    }
    real_by_account: dict[int, list[EntryView]] = defaultdict(list)
    own: list[EntryView] = []
    for v in views:
        if v.position.bought == 0:
            continue
        account_id = signal_account.get(v.entry.signal_id) if v.entry.signal_id else None
        if account_id is None:
            own.append(v)
        else:
            real_by_account[account_id].append(v)

    rows: list[StrategyCompare] = []
    accounts = session.scalars(
        select(PaperAccount).order_by(PaperAccount.strategy_key, PaperAccount.id)
    ).all()
    for account in accounts:
        run = session.get(BacktestRun, account.backtest_run_id)
        backtest = backtest_record(run) if run else None
        backtest_rs = [
            float(r)
            for r in session.scalars(
                select(BacktestTrade.r_multiple).where(
                    BacktestTrade.run_id == account.backtest_run_id, BacktestTrade.segment == "oos"
                )
            )
        ]
        trades = session.scalars(
            select(PaperTrade).where(PaperTrade.account_id == account.id)
        ).all()
        closed = [t for t in trades if t.status == "closed" and t.exit_date is not None]
        paper_closed = [
            ClosedTrade(float(t.r_multiple), float(t.net_pnl), t.sessions, t.exit_date)
            for t in closed
            if t.exit_date is not None
        ]
        worst = session.scalar(
            select(func.max(PaperDay.drawdown_pct)).where(PaperDay.account_id == account.id)
        )
        base = record(paper_closed, account.start_date, account.last_date)
        paper = Record(
            base.trades, base.win_rate, base.expectancy_r, base.profit_factor,
            base.avg_sessions, None if worst is None else float(worst), "%",
            base.start, base.end,
        )  # fmt: skip
        paper_days = ((account.last_date or account.start_date) - account.start_date).days
        p_gate, p_range = paper_gate(paper, paper_days, backtest_rs)

        mine = real_by_account.get(account.id, [])
        real = record(_real(mine), _first_buy(mine), as_of)
        first = _first_buy(mine)
        r_gate, r_range = real_gate(
            real, (as_of - first).days if first else 0, [t.r for t in paper_closed]
        )

        by_trade_signal = {t.signal_id: t for t in trades if t.signal_id}
        pairs = []
        for v in mine:
            if v.entry.signal_id is None:
                continue
            t = by_trade_signal.get(v.entry.signal_id)
            p = v.position
            if t is None or p.avg_entry is None or p.first_date is None:
                continue
            pairs.append(
                Pair(
                    t.signal_date, t.ticker, float(t.entry_price), float(t.initial_stop),
                    t.entry_date, float(t.r_multiple) if t.status == "closed" else None,
                    float(p.avg_entry), p.first_date,
                    float(p.r_multiple) if p.status == "closed" and p.r_multiple is not None
                    else None,
                )
            )  # fmt: skip
        skipped_rs = []
        if account.live_eligible:
            for t in closed:
                decided = by_signal.get(t.signal_id) if t.signal_id else None
                if decided is None or (
                    decided.entry.decision == "skipped" and decided.position.bought == 0
                ):
                    skipped_rs.append(float(t.r_multiple))
        rows.append(
            StrategyCompare(
                account.id,
                account.strategy_key,
                account.strategy_version,
                account.params_label,
                account.live_eligible,
                account.status,
                account.backtest_run_id,
                backtest,
                paper,
                real,
                p_gate,
                r_gate,
                p_range,
                r_range,
                stage(account.live_eligible, p_gate, r_gate),
                divergence(pairs, skipped_rs) if (pairs or skipped_rs) else None,
            )
        )
    if own:
        rows.append(
            StrategyCompare(
                None, None, None, None, False, None, None, None, None,
                record(_real(own), _first_buy(own), as_of),
                None, None, None, None, "own ideas", None,
            )
        )  # fmt: skip
    return rows
