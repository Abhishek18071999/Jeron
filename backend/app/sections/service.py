"""The four sections from the database: each strategy's backtest and paper state, the
latest scan day's signals and the open paper positions, sorted into sections."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.strategies import STRATEGIES, Strategy
from app.models import PaperAccount, PaperTrade
from app.paper.job import (
    active_account,
    day_signals,
    latest_backtest,
    latest_scan_date,
    retired_account,
)
from app.sections.calc import (
    BY_KEY,
    INTRADAY_NEEDS,
    SECTIONS,
    SectionDef,
    SectionKey,
    SectionStatus,
    SignalCard,
    StrategyState,
    card,
    section_for_tier,
    status,
)
from app.settings_store import effective_settings


@dataclass(frozen=True)
class Position:
    account_id: int
    strategy_key: str
    research_only: bool
    ticker: str
    entry_date: date
    entry_price: Decimal
    current_stop: Decimal | None
    last_close: Decimal | None
    shares_held: int
    r_multiple: Decimal


@dataclass
class SectionView:
    section: SectionDef
    status: SectionStatus
    max_positions: int | None
    as_of: date | None
    strategies: list[StrategyState] = field(default_factory=list)
    signals: list[SignalCard] = field(default_factory=list)
    positions: list[Position] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)

    @property
    def live_signals(self) -> list[SignalCard]:
        return [s for s in self.signals if not s.research_only]

    @property
    def research_signals(self) -> list[SignalCard]:
        return [s for s in self.signals if s.research_only]


def strategy_state(session: Session, strategy: Strategy) -> StrategyState:
    run = latest_backtest(session, strategy)
    account = active_account(session, strategy) or retired_account(session, strategy)
    gates: list[dict[str, Any]] = [] if run is None else run.summary.get("gates", [])
    oos = {} if run is None else run.summary.get("out_of_sample", {}).get("trades", {})
    paper = {} if account is None else account.summary or {}
    closed = paper.get("closed_trades", {}) or {}
    return StrategyState(
        key=strategy.key,
        version=strategy.version,
        name=strategy.name,
        summary=strategy.summary,
        tier=strategy.tier,
        backtested=run is not None,
        passed=bool(run is not None and run.live_eligible),
        gates_passed=sum(1 for g in gates if g.get("passed")),
        gates_total=len(gates),
        failed_gates=tuple(str(g.get("label", "")) for g in gates if not g.get("passed")),
        oos_trades=oos.get("trades"),
        oos_expectancy_r=None if oos.get("expectancy_r") is None else float(oos["expectancy_r"]),
        run_id=None if run is None else run.id,
        account_id=None if account is None else account.id,
        account_status=None if account is None else account.status,
        retired_reason=None if account is None else account.retired_reason,
        paper_closed_trades=int(closed.get("trades", 0) or 0),
        paper_return_pct=paper.get("return_pct"),
        paper_open_positions=int(paper.get("open_positions", 0) or 0),
    )


def _max_positions(session: Session, key: SectionKey) -> int | None:
    settings = effective_settings(session)
    return {
        SectionKey.SWING: settings.max_positions_swing,
        SectionKey.POSITIONAL: settings.max_positions_positional,
        SectionKey.INVEST: settings.max_positions_invest,
    }.get(key)


def sections(
    session: Session, only: SectionKey | None = None, day: date | None = None
) -> list[SectionView]:
    """Every section (or one), with the signals of `day` (default: the newest scanned
    day)."""
    day = day or latest_scan_date(session)
    capital = Decimal(str(effective_settings(session).capital))
    wanted = [BY_KEY[only]] if only else list(SECTIONS)
    states: dict[SectionKey, list[StrategyState]] = {s.key: [] for s in wanted}
    for strategy in STRATEGIES.values():
        key = section_for_tier(strategy.tier.value)
        if key in states:
            states[key].append(strategy_state(session, strategy))

    cards: dict[SectionKey, list[SignalCard]] = {s.key: [] for s in wanted}
    if day is not None:
        for record, strategy_key in day_signals(session, day):
            key = section_for_tier(record.payload["tier"])
            if key in cards:
                cards[key].append(
                    card(
                        record.signal_id,
                        record.signal_date,
                        strategy_key,
                        record.research_only,
                        record.payload,
                        capital,
                    )
                )

    accounts = {
        a.id: a
        for a in session.scalars(select(PaperAccount).where(PaperAccount.status == "active"))
    }
    positions: dict[SectionKey, list[Position]] = {s.key: [] for s in wanted}
    if accounts:
        for t in session.scalars(
            select(PaperTrade)
            .where(PaperTrade.status == "open", PaperTrade.account_id.in_(list(accounts)))
            .order_by(PaperTrade.entry_date, PaperTrade.ticker)
        ):
            account = accounts[t.account_id]
            held_by = STRATEGIES.get(account.strategy_key)
            if held_by is None:
                continue
            key = section_for_tier(held_by.tier.value)
            if key in positions:
                positions[key].append(
                    Position(
                        account_id=t.account_id,
                        strategy_key=account.strategy_key,
                        research_only=not account.live_eligible,
                        ticker=t.ticker,
                        entry_date=t.entry_date,
                        entry_price=t.entry_price,
                        current_stop=t.current_stop,
                        last_close=t.last_close,
                        shares_held=t.shares_held,
                        r_multiple=t.r_multiple,
                    )
                )

    out = []
    for section in wanted:
        strategies = sorted(states[section.key], key=lambda s: (not s.passed, s.key))
        out.append(
            SectionView(
                section=section,
                status=status(section, strategies),
                max_positions=_max_positions(session, section.key),
                as_of=day,
                strategies=strategies,
                signals=sorted(
                    cards[section.key], key=lambda c: (c.research_only, -c.conviction, c.ticker)
                ),
                positions=positions[section.key],
                needs=INTRADAY_NEEDS if section.key == SectionKey.INTRADAY else [],
            )
        )
    return out
