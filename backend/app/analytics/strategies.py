"""Every strategy version in one place: its status, the evidence behind it, and
whether its paper record still looks like its backtest (decision 0018). Also the
registry of everything ever tried, so the number of variants behind a result is
never hidden (the multiple-testing risk).

Served at `/strategies` and `/strategies/registry`; `strategy-status` sets a status.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics import status as st
from app.analytics.compare import Gate
from app.analytics.health import Health, assess
from app.analytics.service import StrategyCompare, compare
from app.backtest.strategies import COMBINED, STRATEGIES
from app.models import (
    BacktestRun,
    BacktestTrade,
    BacktestVariant,
    Instrument,
    PaperAccount,
    PaperDay,
    PaperTrade,
    StrategyStatusChange,
)


@dataclass
class StrategyView:
    key: str
    version: str
    name: str
    tier: str
    status: st.StatusView
    run_id: int | None
    run_date: date | None
    live_eligible: bool
    failed_gates: list[str]
    evidence: dict[str, Any] | None  # the latest run's confidence.evidence, if rated
    account_id: int | None
    stage: str | None
    paper_gate: Gate | None
    real_gate: Gate | None
    health: Health | None
    history: list[st.Change] = field(default_factory=list)


def _latest_runs(session: Session) -> dict[str, BacktestRun]:
    newest = (
        select(BacktestRun.strategy_version, func.max(BacktestRun.id).label("id"))
        .group_by(BacktestRun.strategy_version)
        .subquery()
    )
    runs = session.scalars(select(BacktestRun).join(newest, newest.c.id == BacktestRun.id))
    return {r.strategy_version: r for r in runs}


def _changes(session: Session) -> dict[str, list[st.Change]]:
    out: dict[str, list[st.Change]] = defaultdict(list)
    for row in session.scalars(select(StrategyStatusChange).order_by(StrategyStatusChange.id)):
        out[row.strategy_version].append(
            st.Change(row.status, row.reason, row.set_by, row.created_at)
        )
    return out


def _account(session: Session, version: str) -> PaperAccount | None:
    """The version's live paper account: active first, else the newest retired one."""
    rows = session.scalars(
        select(PaperAccount)
        .where(PaperAccount.strategy_version == version, PaperAccount.status != "closed")
        .order_by(PaperAccount.id.desc())
    ).all()
    active = [a for a in rows if a.status == "active"]
    return active[0] if active else (rows[0] if rows else None)


def account_health(session: Session, account: PaperAccount) -> Health:
    trades = session.scalars(
        select(PaperTrade)
        .where(PaperTrade.account_id == account.id)
        .order_by(PaperTrade.exit_date, PaperTrade.seq)
    ).all()
    closed = [t for t in trades if t.status == "closed"]
    backtest_rs = [
        float(r)
        for r in session.scalars(
            select(BacktestTrade.r_multiple).where(
                BacktestTrade.run_id == account.backtest_run_id, BacktestTrade.segment == "oos"
            )
        )
    ]
    run = session.get(BacktestRun, account.backtest_run_id)
    oos = run.summary.get("out_of_sample", {}) if run else {}
    sessions = oos.get("curve", {}).get("sessions") or 0
    bt_trades = oos.get("trades", {}).get("trades") or 0
    paper_sessions = (
        session.scalar(select(func.count()).where(PaperDay.account_id == account.id)) or 0
    )
    sectors = dict(session.execute(select(Instrument.symbol, Instrument.sector)).all())
    return assess(
        [float(t.r_multiple) for t in closed],
        backtest_rs,
        paper_entries=len(trades),
        paper_sessions=int(paper_sessions),
        backtest_trades_per_session=bt_trades / sessions if sessions else None,
        paper_sectors=[sectors.get(t.ticker) for t in closed],
    )


def _revalidated(run: BacktestRun | None, retired_on: date | None) -> bool:
    return bool(
        run is not None
        and run.live_eligible
        and retired_on is not None
        and run.created_at.date() > retired_on
    )


def strategy_views(session: Session, as_of: date | None = None) -> list[StrategyView]:
    runs = _latest_runs(session)
    changes = _changes(session)
    rows: dict[int | None, StrategyCompare] = {r.account_id: r for r in compare(session, as_of)}
    out = []
    for strategy in STRATEGIES.values():
        run = runs.get(strategy.version)
        account = _account(session, strategy.version)
        failed = [g["key"] for g in run.summary.get("gates", []) if not g["passed"]] if run else []
        live = account.live_eligible if account is not None else bool(run and run.live_eligible)
        base = st.derived(
            has_run=run is not None,
            live_eligible=live,
            run_date=run.created_at.date() if run else None,
            failed_gates=failed,
            account_status=account.status if account else None,
            account_start=account.start_date if account else None,
            retired_on=account.retired_on if account else None,
            retired_reason=account.retired_reason if account else None,
        )
        history = changes.get(strategy.version, [])
        row = rows.get(account.id) if account else None
        evidence = (run.summary.get("confidence") or {}).get("evidence") if run else None
        out.append(
            StrategyView(
                key=strategy.key,
                version=strategy.version,
                name=strategy.name,
                tier=strategy.tier.value,
                status=st.current(base, history),
                run_id=run.id if run else None,
                run_date=run.created_at.date() if run else None,
                live_eligible=live,
                failed_gates=failed,
                evidence=evidence,
                account_id=account.id if account else None,
                stage=row.stage if row else None,
                paper_gate=row.paper_gate if row else None,
                real_gate=row.real_gate if row else None,
                health=account_health(session, account) if account else None,
                history=history,
            )
        )
    return out


def set_status(
    session: Session, version: str, target: str, reason: str, now: datetime | None = None
) -> st.StatusView:
    """Record my status change, or raise ValueError saying why it isn't allowed. Retiring
    also retires the version's active paper account, so it stops issuing signals."""
    view = next((v for v in strategy_views(session) if v.version == version), None)
    if view is None:
        known = ", ".join(s.version for s in STRATEGIES.values())
        raise ValueError(f"No strategy version {version!r}: one of {known}")
    target = target.replace("-", " ").replace("_", " ").lower()
    account = _account(session, version)
    run = _latest_runs(session).get(version)
    problem = st.refusal(
        target,
        view.status,
        reason,
        paper_gate=view.paper_gate.status if view.paper_gate else None,
        real_gate=view.real_gate.status if view.real_gate else None,
        evidence=view.evidence.get("rating") if view.evidence else None,
        revalidated=_revalidated(run, account.retired_on if account else None),
    )
    if problem:
        raise ValueError(problem)
    now = now or datetime.now().astimezone()
    if target == st.RETIRED and account is not None and account.status == "active":
        account.status = "retired"
        account.retired_reason = f"retired by me: {reason}"[:300]
        account.retired_on = now.date()
    session.add(
        StrategyStatusChange(
            strategy_version=version,
            status=target,
            reason=reason.strip()[:500],
            set_by="owner",
            evidence={
                "run_id": view.run_id,
                "live_eligible": view.live_eligible,
                "failed_gates": view.failed_gates,
                "evidence": view.evidence.get("rating") if view.evidence else None,
                "paper_gate": view.paper_gate.status if view.paper_gate else None,
                "real_gate": view.real_gate.status if view.real_gate else None,
                "health": view.health.verdict if view.health else None,
            },
            created_at=now,
        )
    )
    session.commit()
    return st.StatusView(target, now.date(), reason.strip(), "owner")


def record_retirement(session: Session, version: str, reason: str, day: date) -> None:
    """The weekly revalidation's retirement, kept in the status history."""
    session.add(
        StrategyStatusChange(
            strategy_version=version,
            status=st.RETIRED,
            reason=f"Weekly revalidation on {day}: {reason}"[:500],
            set_by="jeron",
            evidence={},
        )
    )


def may_resume(session: Session, version: str) -> bool:
    """A retired version may paper-trade again only after I recorded a revalidation
    (status back to paper, `strategy-status`) after the retirement."""
    account = _account(session, version)
    if account is None or account.status != "retired" or account.retired_on is None:
        return True
    retired_on = account.retired_on
    return any(
        c.set_by == "owner" and c.status == st.PAPER and c.at.date() >= retired_on
        for c in _changes(session).get(version, [])
    )


# --- The registry ---------------------------------------------------------------------


@dataclass
class RegistryRow:
    key: str | None  # None: a version no longer in the code (superseded or dropped)
    version: str
    name: str
    tier: str | None
    in_code: bool
    grid_points: int | None
    registered_on: date | None
    runs: int
    variants_logged: int
    latest_run_id: int | None
    latest_run_date: date | None
    live_eligible: bool | None
    evidence: str | None
    expectancy_r: float | None
    deflated_sharpe: float | None


@dataclass
class Registry:
    rows: list[RegistryRow]
    versions: int
    grid_points: int  # the trials behind any one result: every grid point of every version
    runs: int
    passed: int  # versions whose latest run passed the gates
    note: str


def registry(session: Session) -> Registry:
    """Every strategy version in the code or in a stored run, including the ones that
    failed or were dropped. The grid points summed over all of them are the trials a
    "best" result was picked from."""
    runs = _latest_runs(session)
    counts = dict(
        session.execute(
            select(BacktestRun.strategy_version, func.count()).group_by(
                BacktestRun.strategy_version
            )
        ).all()
    )
    variants = dict(
        session.execute(
            select(BacktestRun.strategy_version, func.count(BacktestVariant.id))
            .join(BacktestVariant, BacktestVariant.run_id == BacktestRun.id)
            .group_by(BacktestRun.strategy_version)
        ).all()
    )
    code: dict[str, Any] = {s.version: s for s in STRATEGIES.values()}
    code.update({c.version: c for c in COMBINED.values()})
    rows = []
    for version in sorted(set(code) | set(runs)):
        s = code.get(version)
        run = runs.get(version)
        grid = len(s.grid) if s is not None and hasattr(s, "grid") else None
        oos = run.summary.get("out_of_sample", {}) if run else {}
        evidence = ((run.summary.get("confidence") or {}).get("evidence") or {}) if run else {}
        rows.append(
            RegistryRow(
                key=s.key if s is not None else (run.strategy_key if run else None),
                version=version,
                name=s.name if s is not None else (run.strategy_name if run else version),
                tier=s.tier.value if s is not None else (run.tier if run else None),
                in_code=s is not None,
                grid_points=grid,
                registered_on=getattr(s, "registered_on", None),
                runs=int(counts.get(version, 0)),
                variants_logged=int(variants.get(version, 0)),
                latest_run_id=run.id if run else None,
                latest_run_date=run.created_at.date() if run else None,
                live_eligible=run.live_eligible if run else None,
                evidence=evidence.get("rating"),
                expectancy_r=oos.get("trades", {}).get("expectancy_r") if run else None,
                deflated_sharpe=oos.get("deflated_sharpe") if run else None,
            )
        )
    grid_total = int(np.sum([r.grid_points or 0 for r in rows]))
    passed = sum(1 for r in rows if r.live_eligible)
    return Registry(
        rows=rows,
        versions=len(rows),
        grid_points=grid_total,
        runs=int(sum(counts.values())),
        passed=passed,
        note=(
            f"{len(rows)} strategy versions and {grid_total} parameter sets have been tried. "
            f"With that many tries, some will pass the gates by luck alone: {passed} passed. "
            "The deflated Sharpe and the evidence rating account for it; a pass on its own "
            "does not."
        ),
    )
