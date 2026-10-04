"""Database side of the backtester: load market data, run strategies, store results.

`python -m app.cli backtest` runs every strategy (or `--strategy KEY`) over all
stored history and saves one run per strategy with its trades and the log of every
grid point tried. Runs are never overwritten, so the history of what was tried stays
visible.
"""

import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import numpy as np
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.backtest.engine import Trade
from app.backtest.market import (
    Market,
    MarketInputs,
    SecurityStatusDay,
    StockData,
    build_market,
)
from app.backtest.strategies import STRATEGIES, Strategy
from app.backtest.walkforward import Evaluation, evaluate
from app.config import get_settings
from app.data import store
from app.data.adjust import adjust_bars, build_adjustments
from app.data.nse_lists import INDIA_VIX, NIFTY_50, NIFTY_500
from app.data.pipeline import BOARD_MEETINGS_SOURCE
from app.data.provider import Bar, CorporateActionRecord
from app.enums import CorporateActionType, QualityStatus
from app.models import (
    BacktestRun,
    BacktestTrade,
    BacktestVariant,
    CorporateAction,
    DailyBar,
    DataQualityReport,
    Instrument,
    SecurityStatus,
    SurveillanceFlag,
)
from app.news import job as news_job
from app.scan.job import ASM
from app.scan.universe import UniverseRules

Log = Callable[[str], None]
_CHUNK = 300


def _quiet(_: str) -> None:
    pass


@dataclass(frozen=True)
class _Group:
    symbol: str
    members: tuple[tuple[int, date], ...]  # (instrument id, first date it no longer counts)


def _groups(session: Session, keep: set[int]) -> list[_Group]:
    """One group per company: its current instrument plus the instruments of its
    earlier symbols, each counting only before its rename."""
    symbols = dict(session.execute(select(Instrument.id, Instrument.symbol)).all())
    ids = {s: i for i, s in symbols.items()}
    lineage = store.symbol_lineage(session, ids)
    absorbed: set[int] = set()
    groups = []
    for symbol, chain in lineage.items():
        members = [(ids[symbol], date.max)]
        for old, changed in chain:
            if old in ids:
                members.append((ids[old], changed))
                absorbed.add(ids[old])
        groups.append(_Group(symbol, tuple(members)))
    grouped = {g.symbol for g in groups}
    for id_, symbol in symbols.items():
        if symbol not in grouped and id_ not in absorbed:
            groups.append(_Group(symbol, ((id_, date.max),)))
    return sorted(
        (g for g in groups if any(i in keep for i, _ in g.members)), key=lambda g: g.symbol
    )


def _stock(
    symbol: str,
    rows: Sequence[
        tuple[date, str | None, Decimal, Decimal, Decimal, Decimal, int, Decimal | None]
    ],
    actions: list[CorporateActionRecord],
    sector: str | None,
) -> StockData | None:
    if not rows:
        return None
    bars = [Bar(symbol, d, o, h, lo, c, v, series=s or "") for d, s, o, h, lo, c, v, _ in rows]
    adjustments = build_adjustments(bars, actions)
    adjusted = adjust_bars(bars, adjustments)
    dividends: dict[date, float] = defaultdict(float)
    for a in {
        (a.ex_date, a.amount) for a in actions if a.action_type == CorporateActionType.DIVIDEND
    }:
        if a[1]:
            dividends[a[0]] += float(a[1])
    return StockData(
        symbol=symbol,
        dates=[b.trade_date for b in bars],
        open=np.array([float(a.open) for a in adjusted]),
        high=np.array([float(a.high) for a in adjusted]),
        low=np.array([float(a.low) for a in adjusted]),
        close=np.array([float(a.close) for a in adjusted]),
        volume=np.array([float(a.volume) for a in adjusted]),
        factor=np.array([float(a.factor) for a in adjusted]),
        turnover=np.array([np.nan if r[7] is None else float(r[7]) for r in rows]),
        eq_series=np.array([r[1] == "EQ" for r in rows]),
        dividends=dict(dividends),
        sector=sector,
    )


def load_inputs(
    session: Session,
    start: date | None = None,
    end: date | None = None,
    rules: UniverseRules | None = None,
    log: Log = _quiet,
) -> MarketInputs:
    rules = rules or UniverseRules()
    days = store.ok_dates(session, store.NSE_BARS, start=start, end=end)
    if not days:
        raise ValueError("No NSE prices stored; run backfill first.")
    first, last = days[0], days[-1]
    day_set = set(days)
    # Only stocks that could ever pass the price and turnover rules.
    keep = set(
        session.scalars(
            select(DailyBar.instrument_id)
            .where(DailyBar.source == store.NSE_BARS, DailyBar.trade_date.between(first, last))
            .group_by(DailyBar.instrument_id)
            .having(
                (func.max(DailyBar.turnover) >= rules.min_median_turnover)
                & (func.max(DailyBar.close) >= rules.min_price)
            )
        )
    )
    groups = _groups(session, keep)
    sectors = dict(session.execute(select(Instrument.symbol, Instrument.sector)).all())
    log(f"Loading {len(groups)} stocks, {first} to {last} ({len(days)} sessions)")

    stocks: list[StockData] = []
    statuses: dict[str, dict[date, SecurityStatusDay]] = {}
    for chunk_start in range(0, len(groups), _CHUNK):
        chunk = groups[chunk_start : chunk_start + _CHUNK]
        owners: dict[int, list[tuple[str, date]]] = defaultdict(list)
        for g in chunk:
            for id_, until in g.members:
                owners[id_].append((g.symbol, until))
        ids = list(owners)
        rows_by: dict[str, dict[date, tuple[Any, ...]]] = defaultdict(dict)
        own_id = {g.symbol: g.members[0][0] for g in chunk}
        for id_, d, s, o, h, lo, c, v, t in session.execute(
            select(
                DailyBar.instrument_id,
                DailyBar.trade_date,
                DailyBar.series,
                DailyBar.open,
                DailyBar.high,
                DailyBar.low,
                DailyBar.close,
                DailyBar.volume,
                DailyBar.turnover,
            ).where(
                DailyBar.source == store.NSE_BARS,
                DailyBar.instrument_id.in_(ids),
                DailyBar.trade_date.between(first, last),
            )
        ):
            if d not in day_set:
                continue
            for symbol, until in owners[id_]:
                if id_ != own_id[symbol] and d >= until:
                    continue
                # The current symbol's bar wins if both exist on a date.
                if d in rows_by[symbol] and id_ != own_id[symbol]:
                    continue
                rows_by[symbol][d] = (d, s, o, h, lo, c, v, t)
        actions: dict[str, list[CorporateActionRecord]] = defaultdict(list)
        for row in session.scalars(
            select(CorporateAction).where(
                CorporateAction.source == store.NSE_ACTIONS,
                CorporateAction.instrument_id.in_(ids),
                CorporateAction.ex_date <= last,
            )
        ):
            for symbol, _ in owners[row.instrument_id]:
                actions[symbol].append(
                    CorporateActionRecord(
                        symbol,
                        row.ex_date,
                        row.action_type,
                        row.ratio_new,
                        row.ratio_old,
                        row.amount,
                        row.raw_text,
                    )
                )
        for id_, d, band, gsm in session.execute(
            select(
                SecurityStatus.instrument_id,
                SecurityStatus.trade_date,
                SecurityStatus.price_band,
                SecurityStatus.gsm_stage,
            ).where(
                SecurityStatus.instrument_id.in_(ids),
                SecurityStatus.trade_date.between(first, last),
            )
        ):
            for symbol, until in owners[id_]:
                if id_ != own_id[symbol] and d >= until:
                    continue
                statuses.setdefault(symbol, {})[d] = SecurityStatusDay(
                    None if band is None else float(band), gsm is not None
                )
        for g in chunk:
            rows = [rows_by[g.symbol][d] for d in sorted(rows_by[g.symbol])]
            stock = _stock(g.symbol, rows, actions.get(g.symbol, []), sectors.get(g.symbol))
            if stock is not None:
                stocks.append(stock)
        log(f"  loaded {min(chunk_start + _CHUNK, len(groups))} of {len(groups)}")

    asm: dict[str, list[tuple[date, date | None]]] = defaultdict(list)
    for symbol, start_date, end_date in session.execute(
        select(Instrument.symbol, SurveillanceFlag.start_date, SurveillanceFlag.end_date)
        .join(SurveillanceFlag, SurveillanceFlag.instrument_id == Instrument.id)
        .where(SurveillanceFlag.measure == ASM)
    ):
        asm[symbol].append((start_date, end_date))
    fails = frozenset(
        session.scalars(
            select(DataQualityReport.trade_date).where(
                DataQualityReport.status == QualityStatus.FAIL,
                DataQualityReport.trade_date.between(first, last),
            )
        )
    )

    labeller = news_job.labeller_name(get_settings())

    def closes(name: str) -> dict[date, float]:
        return {d: float(c) for d, c in store.index_closes(session, name, first, last).items()}

    return MarketInputs(
        days=days,
        stocks=stocks,
        nifty500=closes(NIFTY_500),
        nifty50=closes(NIFTY_50),
        vix=closes(INDIA_VIX),
        security_list_days=store.ok_dates(session, store.NSE_SEC_LIST, start=first, end=last),
        security_status=statuses,
        asm=asm,
        quality_fail_days=fails,
        results=(
            store.results_dates(session, [s.symbol for s in stocks])
            if store.board_meetings_loaded(session)
            else None
        ),
        results_updated=store.board_meetings_updated(session, BOARD_MEETINGS_SOURCE),
        news=(
            news_job.dated_labels(session, [s.symbol for s in stocks], labeller, end=last)
            if news_job.labels_exist(session, labeller)
            else None
        ),
        news_labeller=labeller if news_job.labels_exist(session, labeller) else None,
    )


def _years(years: Sequence[int]) -> str:
    return f"{years[0]}-{years[-1]}" if years else "none"


def _money(value: float) -> Decimal:
    return Decimal(f"{value:.2f}")


def _price(value: float) -> Decimal:
    return Decimal(f"{value:.4f}")


def _trade_row(run_id: int, seq: int, segment: str, t: Trade, days: list[date]) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "seq": seq,
        "segment": segment,
        "symbol": t.symbol,
        "variant": t.variant,
        "signal_date": days[t.signal_day],
        "entry_date": days[t.entry_day],
        "exit_date": days[t.exit_day],
        "entry_price": _price(t.entry),
        "stop_price": _price(t.stop0),
        "target_price": _price(t.t1),
        "exit_price": _price(t.exit_price),
        "shares": t.raw_shares,
        "exit_reason": t.exit_reason,
        "gross_pnl": _money(t.gross_pnl),
        "charges": _money(t.charges),
        "dividends": _money(t.dividends),
        "net_pnl": _money(t.net_pnl),
        "r_multiple": Decimal(f"{t.r_multiple:.4f}"),
        "regime": t.regime.value,
        "score": Decimal(f"{t.score:.1f}"),
        "sessions": max(t.exit_day - t.entry_day, 0),
        "open_at_end": t.open_at_end,
    }


def save_evaluation(session: Session, ev: Evaluation, duration: float) -> BacktestRun:
    days = ev.days
    run = BacktestRun(
        strategy_key=ev.strategy.key,
        strategy_version=ev.strategy.version,
        strategy_name=ev.strategy.name,
        tier=ev.strategy.tier.value,
        data_start=days[0],
        data_end=days[-1],
        oos_start=days[ev.folds.test_starts[0]],
        holdout_start=days[ev.folds.holdout_start],
        live_eligible=ev.live_eligible,
        fingerprint=ev.fingerprint,
        duration_seconds=Decimal(f"{duration:.3f}"),
        summary=ev.summary,
        equity=ev.equity,
    )
    session.add(run)
    session.flush()
    rows = [_trade_row(run.id, i, "oos", t, days) for i, t in enumerate(ev.oos_trades, 1)]
    offset = len(rows)
    rows += [
        _trade_row(run.id, offset + i, "holdout", t, days)
        for i, t in enumerate(ev.holdout_trades, 1)
    ]
    for chunk in range(0, len(rows), 1000):
        session.execute(insert(BacktestTrade), rows[chunk : chunk + 1000])
    variant_rows = [
        {
            "run_id": run.id,
            "window": v.window,
            "label": v.label,
            "params": v.params,
            "train_start": v.train_start,
            "train_end": v.train_end,
            "trades": v.trades,
            "expectancy_r": Decimal(f"{v.expectancy_r:.4f}"),
            "sharpe": Decimal(f"{v.sharpe:.4f}"),
            "chosen": v.chosen,
        }
        for v in ev.variant_logs
    ]
    if variant_rows:
        session.execute(insert(BacktestVariant), variant_rows)
    session.commit()
    return run


def run_backtests(
    session: Session,
    keys: Sequence[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    log: Log = _quiet,
    market: Market | None = None,
) -> list[BacktestRun]:
    strategies: list[Strategy] = [STRATEGIES[k] for k in (keys or STRATEGIES)]
    started = time.perf_counter()
    if market is None:
        market = build_market(load_inputs(session, start, end, log=log))
        log(f"Market ready: {len(market.symbols)} stocks in {time.perf_counter() - started:.1f} s")
    runs = []
    for strategy in strategies:
        mark = time.perf_counter()
        ev = evaluate(market, strategy)
        run = save_evaluation(session, ev, time.perf_counter() - mark)
        oos = ev.summary["out_of_sample"]["trades"]
        log(
            f"{strategy.key}: {oos['trades']} out-of-sample trades, expectancy "
            f"{oos['expectancy_r']}R, profit factor {oos['profit_factor']}; "
            f"{'LIVE-ELIGIBLE' if ev.live_eligible else 'not eligible'} (run {run.id}, "
            f"data {ev.fingerprint})"
        )
        brains = ev.summary["brains"]
        if brains["results_blackout"] or brains["min_news_score"] is not None:
            log(
                f"  results calendar: {_years(brains['results_calendar_years'])}; news from "
                f"{brains['news_labeller'] or 'no labeller'}: {_years(brains['news_years'])}"
            )
        for gate in ev.summary["gates"]:
            log(f"  [{'pass' if gate['passed'] else 'FAIL'}] {gate['label']}: {gate['value']}")
        runs.append(run)
    return runs
