"""A strategy version's status, shown everywhere it appears (decision 0018). Pure.

| Status | Means | Set by |
|---|---|---|
| Research | failed the section 6 gates, or not backtested yet: signals are research only | Jeron |
| Paper | passed the gates: paper trading, signals are live but unproven | Jeron |
| Small capital | I trade it with a small, limited allocation | me, past the checks below |
| Approved | full capital | me, past the checks below |
| Retired | failed the weekly revalidation, or I retired it | Jeron or me |

Jeron derives Research, Paper and Retired from the backtest runs and the paper
account. Small capital and Approved are only ever set by me (`strategy-status`), and
`refusal` says when the evidence doesn't allow it yet:

- Small capital: the paper gate passed (3 months, 30 trades, inside the backtest's
  range) and the latest run's evidence rating is moderate or strong;
- Approved: Small capital first, and my real trades match paper (the real gate);
- Paper again after a retirement: a backtest run made after the retirement passes the
  gates, and the reason says what was revalidated. Without that, a retired version
  stays retired: a few winning trades don't bring a broken strategy back.

A status never changes what the engine or the signals do. It is the label that says
how far the evidence has got.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

RESEARCH = "research"
PAPER = "paper"
SMALL = "small capital"
APPROVED = "approved"
RETIRED = "retired"
STATUSES = (RESEARCH, PAPER, SMALL, APPROVED, RETIRED)
CREDIBLE = ("moderate", "strong")
MIN_REASON = 10


@dataclass(frozen=True)
class StatusView:
    status: str
    since: date | None
    reason: str
    set_by: str  # "jeron" or "owner"


@dataclass(frozen=True)
class Change:
    status: str
    reason: str
    set_by: str
    at: datetime


def derived(
    *,
    has_run: bool,
    live_eligible: bool,
    run_date: date | None,
    failed_gates: Sequence[str],
    account_status: str | None,
    account_start: date | None,
    retired_on: date | None,
    retired_reason: str | None,
) -> StatusView:
    """The status Jeron gives from the runs and the paper account alone."""
    if account_status == "retired":
        return StatusView(RETIRED, retired_on, retired_reason or "retired", "jeron")
    if not has_run:
        return StatusView(RESEARCH, None, "Not backtested yet.", "jeron")
    if not live_eligible:
        failed = ", ".join(failed_gates) or "the section 6 gates"
        return StatusView(RESEARCH, run_date, f"Failed {failed}: research only.", "jeron")
    if account_status == "active":
        return StatusView(
            PAPER,
            account_start,
            "Passed the section 6 gates: paper trading. Not yet proven with real money.",
            "jeron",
        )
    return StatusView(
        PAPER, run_date, "Passed the section 6 gates: waiting for its paper account.", "jeron"
    )


def current(base: StatusView, changes: Sequence[Change]) -> StatusView:
    """The newest of my changes, unless Jeron retired the strategy after it."""
    mine = [c for c in changes if c.set_by == "owner"]
    if not mine:
        return base
    last = max(mine, key=lambda c: c.at)
    if base.status == RETIRED and base.since is not None and base.since > last.at.date():
        return base
    return StatusView(last.status, last.at.date(), last.reason, "owner")


def refusal(
    target: str,
    now: StatusView,
    reason: str,
    *,
    paper_gate: str | None,
    real_gate: str | None,
    evidence: str | None,
    revalidated: bool,
) -> str | None:
    """Why I can't set `target` yet, or None. `paper_gate` and `real_gate` are the
    comparison's gate statuses ("passed", "failed", "not yet"); `evidence` the latest
    run's rating; `revalidated`: a run made after the retirement passed the gates."""
    if target not in STATUSES:
        return f"Unknown status {target!r}: one of {', '.join(STATUSES)}."
    if len(reason.strip()) < MIN_REASON:
        return "Give a reason (at least a sentence): it is kept with the status."
    if target == now.status:
        return f"Already {target}."
    if target == SMALL:
        if paper_gate != "passed":
            return f"The paper gate has not passed ({paper_gate or 'no paper record'})."
        if evidence not in CREDIBLE:
            return (
                f"The backtest evidence is {evidence or 'not rated'}: moderate or strong is "
                "needed before real money (run the backtest again to rate it)."
            )
    if target == APPROVED:
        if now.status != SMALL:
            return "Small capital comes first."
        if real_gate != "passed":
            return f"My real trades don't match paper yet ({real_gate or 'no real trades'})."
    if now.status == RETIRED and target in (PAPER, SMALL, APPROVED):
        if not revalidated:
            return (
                "Retired: a backtest run made after the retirement must pass the gates "
                "before it can paper-trade again."
            )
        if target != PAPER:
            return "A retired strategy goes back to paper first."
    return None
