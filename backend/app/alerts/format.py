"""Alert texts: one message per signal and a daily summary. Plain text (no markup), so
Telegram and email show the same thing. Pure functions."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

# Telegram's limit for one message.
TELEGRAM_LIMIT = 4096


def inr(value: Decimal | float | int, decimals: int = 2) -> str:
    """Rupees with Indian digit grouping: 1234567.5 -> ₹12,34,567.50."""
    amount = Decimal(str(value))
    sign = "-" if amount < 0 else ""
    text = f"{abs(amount):.{decimals}f}"
    whole, _, fraction = text.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    return f"{sign}₹{whole}" + (f".{fraction}" if fraction else "")


def _day(d: date | str) -> str:
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return d.strftime("%a %-d %b %Y")


def _num(value: Any, places: int = 2) -> str:
    return f"{Decimal(str(value)):.{places}f}"


def journal_link(web_url: str, signal_id: str) -> str:
    return f"{web_url.rstrip('/')}/journal?signal={signal_id}"


def signal_message(payload: Mapping[str, Any], research_only: bool, web_url: str) -> str:
    """One signal (spec section 4 payload) as an alert."""
    p = payload
    zone, stop, targets, bt = p["entry_zone"], p["stop"], p["targets"], p["backtest_stats"]
    head = (
        f"RESEARCH ONLY, not a trade: {p['ticker']}"
        if research_only
        else f"NEW SIGNAL: {p['ticker']}"
    )
    pf = bt["profit_factor"]
    lines = [
        f"{head} ({p['tier']}, conviction {p['conviction']}/5)",
        f"{p['setup_name']} · {p['strategy_version']}",
        "",
        f"Buy between {inr(zone['low'])} and {inr(zone['high'])}, "
        f"valid until {_day(zone['valid_until'])}",
        f"Stop {inr(stop['price'])} ({stop['reason']})",
        f"T1 {inr(targets['t1'])} · T2 {inr(targets['t2'])} ({targets['basis']}); "
        f"reward:risk {_num(p['risk_reward_t1'], 1)} / {_num(p['risk_reward_t2'], 1)} "
        "after costs",
        f"Size {int(p['shares']):,} shares, {inr(p['capital_at_risk'], 0)} at risk",
        f"Hold {p['expected_holding']['min_days']}-{p['expected_holding']['max_days']} "
        f"sessions; time stop {p['time_stop_days']} sessions",
        "",
        "Why:",
        *[f"• {reason}" for reason in p["why"]],
        "",
        f"Exit plan: {p['exit_plan']}",
        f"Cancel if: {p['invalidation']}",
        f"Event risk: {p['event_risk']}",
        f"Backtest (out of sample, after costs): {bt['trades']} trades, expectancy "
        f"{_num(bt['expectancy_R'])}R, profit factor {'n/a' if pf is None else _num(pf)}, "
        f"max drawdown {_num(bt['max_drawdown_pct'], 1)}% ({bt['period']})",
    ]
    if research_only:
        lines.append(
            "This strategy has not passed the backtest bar (spec section 6); "
            "it is paper-traded for evidence only."
        )
    lines += [f"Note: {n}" for n in p.get("notes", [])]
    lines += ["", f"Journal: {journal_link(web_url, str(p['signal_id']))}"]
    return "\n".join(lines)


@dataclass(frozen=True)
class DigestSignal:
    strategy_key: str
    ticker: str
    research_only: bool
    conviction: int
    entry_low: Decimal
    stop: Decimal


@dataclass(frozen=True)
class DigestAccount:
    strategy_key: str
    stage: str  # "paper" / "research only"
    equity: Decimal
    return_pct: Decimal
    open_positions: int
    heat_pct: Decimal
    drawdown_pct: Decimal


@dataclass(frozen=True)
class DigestPosition:
    ticker: str
    shares: int
    r_multiple: Decimal | None


@dataclass
class Digest:
    day: date
    quality: str | None  # "pass" / "warn" / "fail"; None: no report
    quality_reasons: list[str] = field(default_factory=list)
    scan_status: str | None = None
    scan_reasons: list[str] = field(default_factory=list)
    universe: int = 0
    top: list[tuple[str, Decimal]] = field(default_factory=list)
    regime: str | None = None
    risk_off: bool | None = None
    signals: list[DigestSignal] = field(default_factory=list)
    accounts: list[DigestAccount] = field(default_factory=list)
    positions: list[DigestPosition] = field(default_factory=list)
    pending: int = 0
    web_url: str = ""


def _signal_line(s: DigestSignal) -> str:
    return (
        f"• {s.ticker} ({s.strategy_key}, conviction {s.conviction}/5): "
        f"buy from {inr(s.entry_low)}, stop {inr(s.stop)}"
    )


def digest_message(d: Digest) -> str:
    lines = [f"Jeron daily summary · {_day(d.day)}", ""]
    if d.quality is None:
        lines.append("Data quality: no report for the day")
    else:
        lines.append(f"Data quality: {d.quality.upper()}")
        lines += [f"  - {r}" for r in d.quality_reasons[:3]]
        if len(d.quality_reasons) > 3:
            lines.append(f"  - and {len(d.quality_reasons) - 3} more")
    if d.regime is not None:
        filt = "regime filter ON: risk per trade halved" if d.risk_off else "regime filter off"
        lines.append(f"Market: {d.regime} regime; {filt}")
    if d.scan_status is None:
        lines.append("Scan: not run")
    elif d.scan_status != "ok":
        lines.append("Scan: BLOCKED")
        lines += [f"  - {r}" for r in d.scan_reasons]
    else:
        top = ", ".join(f"{s} {_num(v, 0)}" for s, v in d.top[:5])
        lines.append(f"Scan: {d.universe:,} stocks scored" + (f"; top {top}" if top else ""))

    live = [s for s in d.signals if not s.research_only]
    research = [s for s in d.signals if s.research_only]
    lines.append("")
    if live:
        lines.append(f"New signals ({len(live)}):")
        lines += [_signal_line(s) for s in live]
    else:
        lines.append(
            "New signals: none"
            if any(a.stage == "paper" for a in d.accounts)
            else "New signals: none (no strategy has passed the backtest bar yet)"
        )
    if research:
        by_key: dict[str, list[str]] = {}
        for s in research:
            by_key.setdefault(s.strategy_key, []).append(s.ticker)
        lines.append(f"Research only, not trades ({len(research)}):")
        lines += [f"• {key}: {', '.join(tickers)}" for key, tickers in by_key.items()]

    if d.accounts:
        lines += ["", "Paper accounts:"]
        lines += [
            f"• {a.strategy_key} ({a.stage}): {inr(a.equity, 0)} "
            f"({'+' if a.return_pct >= 0 else ''}{_num(a.return_pct)}%), "
            f"{a.open_positions} open, heat {_num(a.heat_pct, 1)}%, "
            f"drawdown {_num(a.drawdown_pct, 1)}%"
            for a in d.accounts
        ]
    lines += ["", "Journal:"]
    if d.positions:
        held = ", ".join(
            f"{p.ticker} {'' if p.r_multiple is None else _signed_r(p.r_multiple)}".strip()
            for p in d.positions
        )
        lines.append(f"• {len(d.positions)} open: {held}")
    else:
        lines.append("• no open positions")
    if d.pending:
        lines.append(f"• {d.pending} live signals waiting for a decision")
    if d.web_url:
        lines += ["", d.web_url]
    return "\n".join(lines)


def _signed_r(r: Decimal) -> str:
    return f"{'+' if r >= 0 else ''}{_num(r)}R"


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split on line breaks so each part fits the limit (a too-long line is cut)."""
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current or not parts:
        parts.append(current)
    return parts


def digest_signals(rows: Sequence[tuple[str, bool, Mapping[str, Any]]]) -> list[DigestSignal]:
    """(strategy key, research only, payload) -> digest lines."""
    return [
        DigestSignal(
            key,
            p["ticker"],
            research,
            int(p["conviction"]),
            Decimal(str(p["entry_zone"]["low"])),
            Decimal(str(p["stop"]["price"])),
        )
        for key, research, p in rows
    ]
