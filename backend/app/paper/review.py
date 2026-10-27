"""The paper review (paper-review-v1): one paper account's journal, performance, plan
evaluation and root causes, from its stored trades and its latest update's summary.
Pure: the caller loads the rows (`app/paper/optimize.py`).

Everything here is simulated: paper trades from end-of-day data, filled at the open
of the session after the signal with modelled slippage and charges. Nothing is a real
return; the Portfolio and Journal pages hold those.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.journal.calc import mean_interval, sample_note
from app.paper.proposals import ClosedTrade, groups

# A closed trade stopped out this soon at this loss is a false signal: the setup failed
# at once.
FALSE_SIGNAL_SESSIONS = 3
FALSE_SIGNAL_R = -0.5
# A loss worse than this went through the stop (a gap or a lower circuit).
GAP_THROUGH_R = -1.2

LIMITATIONS = [
    "Simulated: paper trades on end-of-day data, not real money. Your real trades are on "
    "the Portfolio and Journal pages.",
    "Fills are the open of the session after the signal (or skipped if it opens above the "
    "entry zone), with modelled slippage and Zerodha's charges. Real fills can differ, "
    "and there are no partial fills or queue effects.",
    "Times are session dates: Jeron has no intraday prices, so a stop or target that "
    "would have hit intraday is acted on at the next open after the close crosses it.",
    "Every update replays the account from its first day on the stored data. If data is "
    "corrected, past paper trades can change; signals and the audit trail keep what was "
    "first recorded.",
    "Sectors are NSE's industries today, not at the time of each trade.",
    "Small samples mislead: the 95% ranges assume independent trades, which trades open "
    "at the same time are not quite.",
]


@dataclass(frozen=True)
class TradeRow:
    """A stored paper trade, as the review reads it (`PaperTrade`'s columns)."""

    seq: int
    ticker: str
    status: str
    signal_id: UUID | None
    signal_date: date
    entry_date: date
    entry_price: Decimal
    initial_stop: Decimal
    target_t1: Decimal
    shares: int
    current_stop: Decimal | None
    last_close: Decimal | None
    shares_held: int
    exit_date: date | None
    exit_price: Decimal | None
    exit_reason: str | None
    charges: Decimal
    net_pnl: Decimal
    r_multiple: Decimal
    sessions: int
    context: Mapping[str, Any] = field(default_factory=dict)


def _r(x: float | None, places: int = 4) -> float | None:
    return None if x is None else round(x, places)


def _exit_kind(reason: str | None) -> str:
    return (reason or "").split(" (")[0] or "unknown"


def _row(t: TradeRow, why: Mapping[UUID, list[str]]) -> dict[str, Any]:
    return {
        "seq": t.seq,
        "ticker": t.ticker,
        "signal_date": str(t.signal_date),
        "entry_date": str(t.entry_date),
        "entry_price": str(t.entry_price),
        "initial_stop": str(t.initial_stop),
        "target_t1": str(t.target_t1),
        "shares": t.shares,
        "exit_date": str(t.exit_date) if t.exit_date else None,
        "exit_price": str(t.exit_price) if t.exit_price is not None else None,
        "exit_reason": t.exit_reason,
        "charges": str(t.charges),
        "net_pnl": str(t.net_pnl),
        "r": float(t.r_multiple),
        "sessions": t.sessions,
        "sector": t.context.get("sector"),
        "score": t.context.get("score"),
        "why": list(why.get(t.signal_id, [])) if t.signal_id else [],
    }


def journal(
    trades: Sequence[TradeRow], equity: float, why: Mapping[UUID, list[str]]
) -> dict[str, Any]:
    """Open positions with their share of equity, closed trades newest first, and where
    the money is (positions by sector, cash)."""
    open_rows = []
    sectors: dict[str, float] = {}
    invested = 0.0
    for t in trades:
        if t.status != "open":
            continue
        value = float(t.last_close or 0) * t.shares_held
        invested += value
        sector = t.context.get("sector") or "no sector"
        sectors[sector] = sectors.get(sector, 0.0) + value
        open_rows.append(
            {
                **_row(t, why),
                "current_stop": str(t.current_stop) if t.current_stop is not None else None,
                "last_close": str(t.last_close) if t.last_close is not None else None,
                "shares_held": t.shares_held,
                "value": round(value, 2),
                "pct_of_equity": round(value / equity * 100, 2) if equity > 0 else None,
            }
        )
    closed = [_row(t, why) for t in trades if t.status == "closed"]
    closed.sort(key=lambda r: (r["exit_date"] or "", r["seq"]), reverse=True)
    cash = equity - invested
    return {
        "open": open_rows,
        "closed": closed,
        "allocation": {
            "equity": round(equity, 2),
            "invested": round(invested, 2),
            "cash": round(cash, 2),
            "cash_pct": round(cash / equity * 100, 2) if equity > 0 else None,
            "sectors": [
                {
                    "sector": k,
                    "value": round(v, 2),
                    "pct_of_equity": round(v / equity * 100, 2) if equity > 0 else None,
                }
                for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])
            ],
        },
    }


def trade_numbers(closed: Sequence[TradeRow]) -> dict[str, Any]:
    """Closed trades' win rate, sizes of wins and losses, expectancy with its 95% range,
    profit factor and what charges took."""
    rs = [t.r_multiple for t in closed]
    n = len(rs)
    wins = [float(r) for r in rs if r > 0]
    losses = [float(r) for r in rs if r <= 0]
    pnl = [float(t.net_pnl) for t in closed]
    gains = sum(p for p in pnl if p > 0)
    lost = -sum(p for p in pnl if p < 0)
    charges = sum(float(t.charges) for t in closed)
    band = mean_interval(rs)
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses) / len(losses) if losses else None
    return {
        "trades": n,
        "wins": len(wins),
        "win_rate": _r(len(wins) / n) if n else None,
        "avg_win_r": _r(avg_win),
        "avg_loss_r": _r(avg_loss),
        # The realised reward:risk: the average win over the average loss.
        "payoff_ratio": _r(avg_win / -avg_loss) if avg_win and avg_loss and avg_loss < 0 else None,
        "expectancy_r": _r(sum(float(r) for r in rs) / n) if n else None,
        "expectancy_interval": [float(band[0]), float(band[1])] if band else None,
        "sample_note": sample_note(n, band),
        "profit_factor": _r(gains / lost) if lost > 0 else None,
        "net_pnl": round(sum(pnl), 2),
        "charges": round(charges, 2),
        "charges_pct_of_gains": _r(charges / gains * 100, 2) if gains > 0 else None,
        "avg_sessions": _r(sum(t.sessions for t in closed) / n, 2) if n else None,
    }


def performance(
    closed: Sequence[TradeRow], summary: Mapping[str, Any], backtest: Mapping[str, Any] | None
) -> dict[str, Any]:
    perf = summary.get("performance") or {}
    curve = perf.get("curve") or {}
    bench = perf.get("benchmark") or {}
    oos = (backtest or {}).get("out_of_sample") or {}
    excess = None
    if curve and bench:
        excess = _r(float(curve["total_return"]) - float(bench["total_return"]))
    return {
        "trades": trade_numbers(closed),
        "curve": curve or None,
        "profile": perf.get("profile"),
        "benchmark": bench or None,
        "excess_return": excess,
        "cash_rate_pct": perf.get("cash_rate_pct"),
        "backtest": {
            "trades": oos.get("trades"),
            "max_drawdown_pct": (oos.get("curve") or {}).get("max_drawdown_pct"),
            "sharpe": (oos.get("curve") or {}).get("sharpe"),
            "holdout": ((backtest or {}).get("holdout") or {}).get("trades"),
        }
        if oos
        else None,
    }


def plan_evaluation(
    closed: Sequence[TradeRow],
    summary: Mapping[str, Any],
    late_signals: int,
    why: Mapping[UUID, list[str]],
) -> dict[str, Any]:
    """What worked and failed by exit, the quick failures, stops gapped through, signals
    the rules skipped, and where the record parted from the plan."""
    by_exit: dict[str, list[TradeRow]] = {}
    for t in closed:
        by_exit.setdefault(_exit_kind(t.exit_reason), []).append(t)
    exits = [
        {
            "exit": k,
            "trades": len(ts),
            "avg_r": _r(sum(float(t.r_multiple) for t in ts) / len(ts)),
            "net_pnl": round(sum(float(t.net_pnl) for t in ts), 2),
        }
        for k, ts in sorted(by_exit.items(), key=lambda kv: -len(kv[1]))
    ]
    ranked = sorted(closed, key=lambda t: (t.r_multiple, t.seq))
    false_signals = [
        t
        for t in closed
        if t.sessions <= FALSE_SIGNAL_SESSIONS and float(t.r_multiple) <= FALSE_SIGNAL_R
    ]
    gaps = [t for t in closed if float(t.r_multiple) < GAP_THROUGH_R]
    notes = summary.get("notes") or []
    return {
        "exits": exits,
        "best": [_row(t, why) for t in reversed(ranked[-3:]) if t.r_multiple > 0],
        "worst": [_row(t, why) for t in ranked[:3] if t.r_multiple < 0],
        "false_signals": {
            "trades": len(false_signals),
            "share": _r(len(false_signals) / len(closed)) if closed else None,
            "rule": f"stopped out within {FALSE_SIGNAL_SESSIONS} sessions at {FALSE_SIGNAL_R:g}R "
            "or worse",
            "tickers": [t.ticker for t in false_signals[-10:]],
        },
        "gap_through": {
            "trades": len(gaps),
            "rule": f"closed worse than {GAP_THROUGH_R:g}R (the stop gapped or hit a circuit)",
            "rows": [_row(t, why) for t in gaps[-10:]],
        },
        "missed": summary.get("missed"),
        "deviations": {
            "late_signals": late_signals,
            "replay_changes": [n for n in notes if "no longer gives" in n],
            "rejected_signals": [n for n in notes if n.startswith("Rejected signal")],
            "note": "Paper trades follow the plan by construction (the backtest engine runs "
            "them), so these are the places the record parted from it.",
        },
    }


def root_causes(closed: Sequence[TradeRow]) -> dict[str, Any]:
    """Closed trades grouped by what was known at each signal, worst first, with how
    much of all the R lost came from each dimension's worst group."""
    trades = [ClosedTrade(float(t.r_multiple), float(t.net_pnl), t.context) for t in closed]
    total_loss = -sum(t.r for t in trades if t.r < 0)
    out = []
    for dimension, gs in groups(trades).items():
        if not gs:
            continue
        worst_loss = max(gs, key=lambda g: g.loss_r)
        out.append(
            {
                "dimension": dimension,
                "groups": [g.to_dict() for g in gs],
                "loss_concentration": {
                    "value": worst_loss.value,
                    "share": _r(worst_loss.loss_r / total_loss) if total_loss > 0 else None,
                },
            }
        )
    losses = sorted((t for t in closed if float(t.r_multiple) <= -0.9), key=lambda t: t.r_multiple)
    return {
        "dimensions": out,
        "big_losses": [
            {
                "ticker": t.ticker,
                "entry_date": str(t.entry_date),
                "r": float(t.r_multiple),
                "exit_reason": t.exit_reason,
                "context": dict(t.context),
            }
            for t in losses[:15]
        ],
        "no_context": sum(1 for t in closed if not t.context),
    }


def observations(perf: Mapping[str, Any], plan: Mapping[str, Any]) -> list[str]:
    """Changes to exits, sizing or risk controls the numbers point at. These change the
    engine's rules, so they are never proposals: each would be a new strategy version
    written by hand and backtested."""
    out: list[str] = []
    t = perf["trades"]
    if t["trades"] < 30:
        return out
    if t["avg_win_r"] is not None and t["avg_win_r"] < 1.0:
        out.append(
            f"Winners average {t['avg_win_r']:.2f}R: the exits may be taking profits too soon "
            "(a wider trail or a later breakeven move would be a new version to test)."
        )
    share = plan["false_signals"]["share"]
    if share is not None and share >= 0.3:
        out.append(
            f"{share:.0%} of closed trades were stopped out within "
            f"{FALSE_SIGNAL_SESSIONS} sessions: entries may be stretched, or the stop too "
            "close for the stock's swings."
        )
    gaps = plan["gap_through"]["trades"]
    if gaps and gaps / t["trades"] >= 0.05:
        out.append(
            f"{gaps} trades lost more than {-GAP_THROUGH_R:g}R through gaps: position size is "
            "set by the stop, so a gap risk filter or smaller size would be a new version."
        )
    profile = perf.get("profile") or {}
    exposure = profile.get("exposure_pct")
    if exposure is not None and exposure < 30:
        out.append(
            f"On average {exposure:.0f}% of the account was in stocks: most of the result is "
            "the cash rate, not the trades."
        )
    charges = t["charges_pct_of_gains"]
    if charges is not None and charges >= 20:
        out.append(
            f"Charges took {charges:.0f}% of the winning trades' profit: small positions or "
            "short holds are expensive."
        )
    return out


def review(
    trades: Sequence[TradeRow],
    summary: Mapping[str, Any],
    backtest: Mapping[str, Any] | None,
    late_signals: int,
    why: Mapping[UUID, list[str]],
) -> dict[str, Any]:
    closed = [t for t in trades if t.status == "closed"]
    equity = float(summary.get("equity") or 0.0)
    perf = performance(closed, summary, backtest)
    plan = plan_evaluation(closed, summary, late_signals, why)
    return {
        "journal": journal(trades, equity, why),
        "performance": perf,
        "plan": plan,
        "root_causes": root_causes(closed),
        "observations": observations(perf, plan),
        "limitations": LIMITATIONS,
    }
