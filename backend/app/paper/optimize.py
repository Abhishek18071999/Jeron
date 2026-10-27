"""The paper review's database side (paper-review-v1): load an account's review,
record strategy proposals from its closed trades, and test them.

Proposals are never applied. A proposal is tested twice on data its evidence never saw:
- the backtest check runs the strategy with and without the filter, walk-forward with
  the 12-month holdout, on the history before the paper account opened (the evidence
  came from the paper period);
- the forward check splits the paper trades closed since the proposal by the filter
  (reporting only).
Passing makes it "ready for a new version": a person registers that version in
`strategies.py`, where it is backtested and paper-traded like any other.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.backtest.job import load_inputs, missing_inputs
from app.backtest.market import Market, build_market
from app.backtest.strategies import STRATEGIES, Strategy
from app.backtest.walkforward import Evaluation, evaluate, make_folds
from app.data import store
from app.models import (
    BacktestRun,
    PaperAccount,
    PaperEvent,
    PaperTrade,
    SignalRecord,
    StrategyProposal,
)
from app.paper.proposals import (
    REVIEW_VERSION,
    ClosedTrade,
    Result,
    candidates,
    forward_split,
    judge,
    skip_filter,
)
from app.paper.review import TradeRow, review
from app.signals.build import IST

Log = Callable[[str], None]
# The weekly job tests at most this many waiting proposals (each is two walk-forward
# backtests).
WEEKLY_VALIDATIONS = 2


def _quiet(_: str) -> None:
    pass


def _rows(session: Session, account_id: int) -> list[TradeRow]:
    return [
        TradeRow(
            seq=t.seq,
            ticker=t.ticker,
            status=t.status,
            signal_id=t.signal_id,
            signal_date=t.signal_date,
            entry_date=t.entry_date,
            entry_price=t.entry_price,
            initial_stop=t.initial_stop,
            target_t1=t.target_t1,
            shares=t.shares,
            current_stop=t.current_stop,
            last_close=t.last_close,
            shares_held=t.shares_held,
            exit_date=t.exit_date,
            exit_price=t.exit_price,
            exit_reason=t.exit_reason,
            charges=t.charges,
            net_pnl=t.net_pnl,
            r_multiple=t.r_multiple,
            sessions=t.sessions,
            context=t.context or {},
        )
        for t in session.scalars(
            select(PaperTrade).where(PaperTrade.account_id == account_id).order_by(PaperTrade.seq)
        )
    ]


def _closed(rows: list[TradeRow], after: date | None = None) -> list[ClosedTrade]:
    return [
        ClosedTrade(float(t.r_multiple), float(t.net_pnl), t.context)
        for t in rows
        if t.status == "closed" and (after is None or t.signal_date > after)
    ]


def proposal_view(p: StrategyProposal) -> dict[str, Any]:
    return {
        "id": p.id,
        "strategy_version": p.strategy_version,
        "account_id": p.account_id,
        "dimension": p.dimension,
        "group_value": p.group_value,
        "text": p.text,
        "evidence": p.evidence,
        "created_at": p.created_at.isoformat(),
        "status": p.status,
        "backtest": p.backtest,
        "validated_at": p.validated_at.isoformat() if p.validated_at else None,
        "forward": p.forward,
        "forward_at": p.forward_at.isoformat() if p.forward_at else None,
    }


def account_review(session: Session, account: PaperAccount) -> dict[str, Any]:
    """Everything the performance page shows for one paper account."""
    rows = _rows(session, account.id)
    signals = session.scalars(select(SignalRecord).where(SignalRecord.account_id == account.id))
    why: dict[Any, list[str]] = {}
    late = 0
    for r in signals:
        why[r.signal_id] = list(r.payload.get("why") or [])
        late += r.late
    run = session.get(BacktestRun, account.backtest_run_id)
    proposals = session.scalars(
        select(StrategyProposal)
        .where(StrategyProposal.strategy_version == account.strategy_version)
        .order_by(StrategyProposal.id.desc())
    ).all()
    events = session.scalar(
        select(func.count()).select_from(PaperEvent).where(PaperEvent.account_id == account.id)
    )
    tested = session.scalar(
        select(func.count())
        .select_from(StrategyProposal)
        .where(StrategyProposal.validated_at.is_not(None))
    )
    return {
        **review(rows, account.summary or {}, run.summary if run else None, late, why),
        "proposals": [proposal_view(p) for p in proposals],
        "proposals_tested_all": tested or 0,
        "audit_events": events or 0,
        "review_version": REVIEW_VERSION,
    }


def audit_trail(
    session: Session, account_id: int, limit: int = 200, kind: str | None = None
) -> list[dict[str, Any]]:
    query = select(PaperEvent).where(PaperEvent.account_id == account_id)
    if kind:
        query = query.where(PaperEvent.kind == kind)
    query = query.order_by(PaperEvent.event_date.desc(), PaperEvent.id.desc()).limit(limit)
    return [
        {
            "kind": e.kind,
            "event_date": str(e.event_date),
            "ticker": e.ticker,
            "ref": e.ref,
            "detail": e.detail,
            "recorded_at": e.recorded_at.isoformat(),
        }
        for e in session.scalars(query)
    ]


def record_proposals(
    session: Session, now: datetime | None = None, log: Log = _quiet
) -> list[StrategyProposal]:
    """Apply the proposal rule to every active paper account's closed trades and store
    the proposals not made before (one per strategy version and group, ever)."""
    now = now or datetime.now(IST)
    new: list[StrategyProposal] = []
    accounts = session.scalars(select(PaperAccount).where(PaperAccount.status == "active"))
    for account in accounts:
        for c in candidates(_closed(_rows(session, account.id))):
            g = c.group
            row = session.execute(
                pg_insert(StrategyProposal)
                .values(
                    strategy_version=account.strategy_version,
                    account_id=account.id,
                    dimension=g.dimension,
                    group_value=g.value,
                    text=c.text,
                    evidence=c.evidence(),
                    created_at=now,
                    status="proposed",
                )
                .on_conflict_do_nothing(
                    index_elements=["strategy_version", "dimension", "group_value"]
                )
                .returning(StrategyProposal.id)
            ).first()
            if row is not None:
                proposal = session.get_one(StrategyProposal, row[0])
                new.append(proposal)
                log(f"{account.strategy_key}: proposed: {c.text}")
    session.commit()
    return new


def refresh_forward(session: Session, now: datetime | None = None) -> int:
    """The forward check for every proposal: its account's paper trades signalled after
    the proposal was made, split by the filter."""
    now = now or datetime.now(IST)
    proposals = session.scalars(select(StrategyProposal)).all()
    for p in proposals:
        made = p.created_at.astimezone(IST).date()
        trades = _closed(_rows(session, p.account_id), after=made)
        p.forward = {"since": str(made), **forward_split(trades, p.dimension, p.group_value)}
        p.forward_at = now
    session.commit()
    return len(proposals)


def filtered_strategy(strategy: Strategy, p: StrategyProposal) -> Strategy:
    """The strategy with the proposal's filter: a trial, never registered."""
    return replace(
        strategy,
        key=f"{strategy.key}+proposal-{p.id}",
        version=f"{strategy.version}+proposal-{p.id}",
        name=f"{strategy.name}, {p.text.split(':')[0].lower()}",
        condition=skip_filter(strategy.condition, p.dimension, p.group_value),
    )


def _result(ev: Evaluation) -> Result:
    oos, hold = ev.summary["out_of_sample"], ev.summary["holdout"]
    return Result(
        oos_trades=int(oos["trades"]["trades"]),
        oos_expectancy_r=float(oos["trades"]["expectancy_r"]),
        holdout_trades=int(hold["trades"]["trades"]),
        holdout_expectancy_r=float(hold["trades"]["expectancy_r"]),
        max_drawdown_pct=float(oos["curve"]["max_drawdown_pct"]),
    )


def validation_market(session: Session, account: PaperAccount) -> Market:
    """The stored history before the paper account opened (its first day's signals
    are paper evidence, so that day is left out too)."""
    days = store.ok_dates(session, store.NSE_BARS, end=account.start_date)
    before = [d for d in days if d < account.start_date]
    if not before:
        raise ValueError(f"no stored prices before {account.start_date}")
    return build_market(load_inputs(session, None, before[-1]))


def validate(
    session: Session,
    proposal: StrategyProposal,
    market: Market | None = None,
    now: datetime | None = None,
    log: Log = _quiet,
) -> StrategyProposal:
    """The backtest check: base and filtered strategy on the history before the paper
    account opened. Stores the numbers, the verdict and when."""
    now = now or datetime.now(IST)
    account = session.get_one(PaperAccount, proposal.account_id)
    base = STRATEGIES.get(account.strategy_key)

    def cannot(reason: str) -> StrategyProposal:
        proposal.status = "could not test"
        proposal.backtest = {"reason": reason}
        proposal.validated_at = now
        session.commit()
        log(f"Proposal {proposal.id}: could not test: {reason}")
        return proposal

    if base is None or base.version != proposal.strategy_version:
        return cannot("the strategy version is no longer registered")
    m = market if market is not None else validation_market(session, account)
    try:
        folds = make_folds(m.days)
    except ValueError as exc:
        return cannot(f"{exc} before the paper account opened on {account.start_date}")
    missing = missing_inputs(m, base)
    if missing:
        return cannot(missing)
    filtered = filtered_strategy(base, proposal)
    base_ev, filtered_ev = evaluate(m, base), evaluate(m, filtered)
    before, after = _result(base_ev), _result(filtered_ev)
    passed, fails = judge(before, after)
    proposal.backtest = {
        "data": [str(m.days[0]), str(m.days[-1])],
        "out_of_sample_from": str(m.days[folds.test_starts[0]]),
        "holdout": [str(m.days[folds.holdout_start]), str(m.days[folds.end])],
        "base": before.to_dict(),
        "filtered": after.to_dict(),
        "fails": fails,
        "fingerprint": filtered_ev.fingerprint,
    }
    proposal.status = "passed backtest" if passed else "failed backtest"
    proposal.validated_at = now
    session.commit()
    log(f"Proposal {proposal.id}: {proposal.status}" + (f" ({'; '.join(fails)})" if fails else ""))
    return proposal


def validate_waiting(
    session: Session, limit: int | None = None, log: Log = _quiet, now: datetime | None = None
) -> list[StrategyProposal]:
    """Test proposals that haven't been, oldest first. Accounts that share a start day
    share the market built for them."""
    query = (
        select(StrategyProposal)
        .where(StrategyProposal.validated_at.is_(None))
        .order_by(StrategyProposal.id)
    )
    if limit is not None:
        query = query.limit(limit)
    markets: dict[date, Market] = {}
    done = []
    for p in session.scalars(query).all():
        account = session.get_one(PaperAccount, p.account_id)
        if account.start_date not in markets:
            try:
                markets[account.start_date] = validation_market(session, account)
            except ValueError as exc:
                log(f"Proposal {p.id}: {exc}")
                continue
        done.append(validate(session, p, markets[account.start_date], now=now, log=log))
    return done
