"""The daily scan job: universe, indicators and technical score for one trading day.

The scan refuses to run (and records why) when:
- there are no NSE prices for the day,
- the day's data-quality report is missing or FAILed (spec: "If it fails, the scan
  doesn't run and I'm told why"),
- the Nifty 500 close for the day is missing (relative strength needs it),
- there is no NSE security list from the last week (GSM can't be checked).

Re-running a day replaces that day's results for the same score version.
"""

import statistics
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.data import store
from app.data.adjust import adjust_bars, build_adjustments
from app.data.nse_lists import NIFTY_500
from app.data.provider import Bar, CorporateActionRecord
from app.enums import QualityStatus
from app.models import (
    CorporateAction,
    DailyBar,
    DataQualityReport,
    Instrument,
    ScanResult,
    ScanRun,
    SourceFile,
)
from app.scan.score import (
    SCORE_VERSION,
    PriceHistory,
    Snapshot,
    percentile_ranks,
    score,
    snapshot,
    total,
)
from app.scan.universe import (
    EXCLUSION_LABELS,
    Candidate,
    Exclusion,
    UniverseRules,
    exclusion,
)

Log = Callable[[str], None]
# Sessions of history loaded per stock: a year of 52-week highs plus the 200-day
# EMA's warm-up, so every indicator has settled.
LOOKBACK_SESSIONS = 450
ASM = "ASM"


def _quiet(_: str) -> None:
    pass


@dataclass
class ScanOutcome:
    run_id: int
    trade_date: date
    status: str
    reasons: list[str] = field(default_factory=list)
    universe_size: int = 0
    duration_seconds: float = 0.0


def _session_dates(session: Session, end: date, sessions: int) -> list[date]:
    """The last `sessions` NSE trading days up to `end`, oldest first."""
    rows = session.scalars(
        select(SourceFile.trade_date)
        .where(
            SourceFile.source == store.NSE_BARS,
            SourceFile.status == "ok",
            SourceFile.trade_date <= end,
        )
        .order_by(SourceFile.trade_date.desc())
        .limit(sessions)
    )
    return sorted(rows)


def latest_scannable_date(session: Session) -> date | None:
    days = _session_dates(session, date.max, 1)
    return days[-1] if days else None


def blocking_reasons(session: Session, day: date) -> list[str]:
    reasons = []
    if day not in _session_dates(session, day, 1):
        return [f"No NSE prices are stored for {day}."]
    report = session.scalar(select(DataQualityReport).where(DataQualityReport.trade_date == day))
    if report is None:
        reasons.append(f"No data-quality report for {day}; run the quality check first.")
    elif report.status == QualityStatus.FAIL:
        failed = "; ".join(report.details.get("reasons", [])) or "see the report"
        reasons.append(f"Data quality FAILED for {day}: {failed}")
    if not store.index_closes(session, NIFTY_500, day, day):
        reasons.append(f"No Nifty 500 close for {day}, so relative strength can't be measured.")
    if store.gsm_symbols(session, day) is None:
        reasons.append(f"No NSE security list in the week up to {day}, so GSM can't be checked.")
    return reasons


def _candidates(session: Session, days: Sequence[date]) -> dict[str, tuple[int, Candidate]]:
    """Every stock that traded in the turnover window, with its stats on the last day."""
    day = days[-1]
    rows = session.execute(
        select(
            Instrument.id,
            Instrument.symbol,
            DailyBar.trade_date,
            DailyBar.series,
            DailyBar.close,
            DailyBar.turnover,
        )
        .join(DailyBar, DailyBar.instrument_id == Instrument.id)
        .where(DailyBar.source == store.NSE_BARS, DailyBar.trade_date.in_(list(days)))
    )
    turnovers: dict[int, list[Decimal]] = defaultdict(list)
    today: dict[int, tuple[str | None, Decimal | None]] = {}
    symbols: dict[int, str] = {}
    for id_, symbol, trade_date, series, close, turnover in rows:
        symbols[id_] = symbol
        if turnover is not None:
            turnovers[id_].append(turnover)
        if trade_date == day:
            today[id_] = (series, close)
    out = {}
    for id_, symbol in symbols.items():
        day_series, day_close = today.get(id_, (None, None))
        values = turnovers.get(id_)
        out[symbol] = (
            id_,
            Candidate(
                symbol=symbol,
                traded=id_ in today,
                series=day_series,
                close=day_close,
                median_turnover=statistics.median(values) if values else None,
            ),
        )
    return out


@dataclass
class _Loaded:
    bars: dict[str, list[Bar]]
    actions: dict[str, list[CorporateActionRecord]]


def _load_history(session: Session, wanted: dict[str, int], start: date, end: date) -> _Loaded:
    """Raw bars from `start` to `end` and NSE corporate actions for `wanted`
    (symbol -> instrument id), joining each renamed stock's earlier symbols."""
    lineage = store.symbol_lineage(session, wanted)
    old_symbols = {old for chain in lineage.values() for old, _ in chain}
    old_ids = store.existing_ids(session, old_symbols)
    # instrument id -> (scanned symbol, last date that instrument's bars count for)
    owners: dict[int, list[tuple[str, date]]] = defaultdict(list)
    for symbol, id_ in wanted.items():
        owners[id_].append((symbol, end))
        for old, changed in lineage.get(symbol, []):
            if old in old_ids:
                owners[old_ids[old]].append((symbol, changed))
    ids = list(owners)

    bars: dict[str, list[Bar]] = defaultdict(list)
    for chunk in range(0, len(ids), 500):
        rows = session.execute(
            select(
                DailyBar.instrument_id,
                DailyBar.trade_date,
                DailyBar.open,
                DailyBar.high,
                DailyBar.low,
                DailyBar.close,
                DailyBar.volume,
            ).where(
                DailyBar.source == store.NSE_BARS,
                DailyBar.instrument_id.in_(ids[chunk : chunk + 500]),
                DailyBar.trade_date.between(start, end),
            )
        )
        for id_, trade_date, o, h, lo, c, v in rows:
            for symbol, until in owners[id_]:
                # Old symbols count only before the rename; the current one from then.
                if id_ != wanted[symbol] and trade_date >= until:
                    continue
                bars[symbol].append(Bar(symbol, trade_date, o, h, lo, c, v))
    for symbol_bars in bars.values():
        symbol_bars.sort(key=lambda b: b.trade_date)
        # If old and new symbols both have a bar on a date, keep one.
        deduped = {b.trade_date: b for b in symbol_bars}
        symbol_bars[:] = [deduped[d] for d in sorted(deduped)]

    actions: dict[str, list[CorporateActionRecord]] = defaultdict(list)
    for chunk in range(0, len(ids), 500):
        for row in session.scalars(
            select(CorporateAction).where(
                CorporateAction.source == store.NSE_ACTIONS,
                CorporateAction.instrument_id.in_(ids[chunk : chunk + 500]),
                CorporateAction.ex_date <= end,
            )
        ):
            for symbol, _ in owners[row.instrument_id]:
                actions[symbol].append(
                    CorporateActionRecord(
                        symbol=symbol,
                        ex_date=row.ex_date,
                        action_type=row.action_type,
                        ratio_new=row.ratio_new,
                        ratio_old=row.ratio_old,
                        amount=row.amount,
                        raw_text=row.raw_text,
                    )
                )
    return _Loaded(bars, actions)


def _price_history(bars: list[Bar], actions: list[CorporateActionRecord]) -> PriceHistory:
    adjustments = build_adjustments(bars, actions)
    if adjustments:
        adjusted = adjust_bars(bars, adjustments)
        return PriceHistory(
            dates=[a.raw.trade_date for a in adjusted],
            highs=[float(a.high) for a in adjusted],
            lows=[float(a.low) for a in adjusted],
            closes=[float(a.close) for a in adjusted],
            volumes=[float(a.volume) for a in adjusted],
        )
    return PriceHistory(
        dates=[b.trade_date for b in bars],
        highs=[float(b.high) for b in bars],
        lows=[float(b.low) for b in bars],
        closes=[float(b.close) for b in bars],
        volumes=[float(b.volume) for b in bars],
    )


def _save_run(
    session: Session,
    day: date,
    status: str,
    universe_size: int,
    duration: float,
    details: dict[str, Any],
) -> ScanRun:
    session.execute(
        delete(ScanRun).where(ScanRun.trade_date == day, ScanRun.score_version == SCORE_VERSION)
    )
    run = ScanRun(
        trade_date=day,
        score_version=SCORE_VERSION,
        status=status,
        universe_size=universe_size,
        duration_seconds=Decimal(f"{duration:.3f}"),
        details=details,
    )
    session.add(run)
    session.flush()
    return run


def run_scan(
    session: Session,
    day: date | None = None,
    *,
    rules: UniverseRules | None = None,
    log: Log = _quiet,
    clock: Callable[[], float] = time.perf_counter,
) -> ScanOutcome:
    """Scan one trading day (default: the newest with prices) and store the results."""
    rules = rules or UniverseRules()
    started = clock()
    day = day or latest_scannable_date(session)
    if day is None:
        raise ValueError("No NSE prices stored yet; run backfill first.")

    reasons = blocking_reasons(session, day)
    if reasons:
        run = _save_run(session, day, "blocked", 0, clock() - started, {"reasons": reasons})
        session.commit()
        for reason in reasons:
            log(f"Scan blocked: {reason}")
        return ScanOutcome(run.id, day, "blocked", reasons, 0, float(run.duration_seconds or 0))

    timings: dict[str, float] = {}
    mark = clock()
    turnover_days = _session_dates(session, day, rules.turnover_sessions)
    candidates = _candidates(session, turnover_days)
    gsm_list = store.gsm_symbols(session, day)
    gsm_date, gsm = gsm_list if gsm_list else (None, set())
    asm = store.surveillance_symbols(session, ASM, day)
    asm_loaded = store.ok_dates(session, store.ASM_IMPORT, end=day)

    excluded: dict[Exclusion, list[str]] = defaultdict(list)
    passed: dict[str, int] = {}
    for symbol, (id_, candidate) in sorted(candidates.items()):
        rule = exclusion(candidate, rules, gsm, asm)
        if rule is None:
            passed[symbol] = id_
        else:
            excluded[rule].append(symbol)
    timings["universe"] = clock() - mark

    mark = clock()
    window = _session_dates(session, day, LOOKBACK_SESSIONS)
    loaded = _load_history(session, passed, window[0], day)
    nifty = {d: float(c) for d, c in store.index_closes(session, NIFTY_500, window[0], day).items()}
    timings["load"] = clock() - mark

    mark = clock()
    snapshots: dict[str, Snapshot] = {}
    for symbol in passed:
        bars = loaded.bars.get(symbol, [])
        if len(bars) < rules.min_history or bars[-1].trade_date != day:
            excluded[Exclusion.SHORT_HISTORY].append(symbol)
            continue
        snapshots[symbol] = snapshot(_price_history(bars, loaded.actions.get(symbol, [])), nifty)
    rs3 = percentile_ranks({s: v.rs_3m for s, v in snapshots.items()})
    rs6 = percentile_ranks({s: v.rs_6m for s, v in snapshots.items()})
    scored = []
    for symbol, snap in snapshots.items():
        components = score(snap, rs3.get(symbol), rs6.get(symbol))
        scored.append((total(components), symbol, snap, components))
    scored.sort(key=lambda r: (-r[0], r[1]))
    timings["score"] = clock() - mark

    nifty500 = store.index_members(session, NIFTY_500, day)
    sectors = dict(
        session.execute(
            select(Instrument.symbol, Instrument.sector).where(
                Instrument.id.in_(list(passed.values()))
            )
        ).all()
    )
    notes = []
    if not asm_loaded:
        notes.append(
            "No ASM list has been imported, so ASM stocks are not excluded "
            "(python -m app.cli asm-import)."
        )
    elif (day - asm_loaded[-1]).days > 7:
        notes.append(f"The ASM list was last imported on {asm_loaded[-1]}.")
    if not nifty500:
        notes.append("Nifty 500 membership is not loaded for this date.")
    details: dict[str, Any] = {
        "turnover_window": [str(turnover_days[0]), str(turnover_days[-1])],
        "security_list_date": str(gsm_date) if gsm_date else None,
        "asm_list_date": str(asm_loaded[-1]) if asm_loaded else None,
        "candidates": len(candidates),
        "exclusions": [
            {
                "rule": rule.value,
                "label": EXCLUSION_LABELS[rule],
                "count": len(excluded[rule]),
                "symbols": sorted(excluded[rule])[:200]
                if rule in (Exclusion.GSM, Exclusion.ASM, Exclusion.SHORT_HISTORY)
                else [],
            }
            for rule in Exclusion
        ],
        "notes": notes,
        "timings": {k: round(v, 3) for k, v in timings.items()},
    }
    run = _save_run(session, day, "ok", len(scored), clock() - started, details)
    rows = [
        {
            "run_id": run.id,
            "instrument_id": passed[symbol],
            "symbol": symbol,
            "rank": rank,
            "score": Decimal(f"{points:.1f}"),
            "close": loaded.bars[symbol][-1].close,
            "in_nifty500": symbol in nifty500,
            "sector": sectors.get(symbol),
            "components": [c.to_dict() for c in components],
            "indicators": snap.to_dict(),
        }
        for rank, (points, symbol, snap, components) in enumerate(scored, 1)
    ]
    for chunk in range(0, len(rows), 1000):
        session.execute(insert(ScanResult), rows[chunk : chunk + 1000])
    run.duration_seconds = Decimal(f"{clock() - started:.3f}")
    run.details = details | {"timings": details["timings"] | {"total": float(run.duration_seconds)}}
    session.commit()
    log(
        f"{day}: scanned {len(candidates)} stocks, {len(scored)} in the universe, "
        f"in {run.duration_seconds} s"
    )
    return ScanOutcome(run.id, day, "ok", [], len(scored), float(run.duration_seconds))
