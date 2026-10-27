"""The kill switch (docs/runbook.md): `python -m app.cli stop-all --reason "..."` stops
everything that leads to a new buy in one command, and says why; `resume` undoes it.

While stopped:
- no signal or watchlist alerts are sent; the daily summary and the pre-open check
  still go out, headed "JERON IS STOPPED" with the reason, because open positions
  still need their exits (stopping those in a crisis would be the wrong reflex);
- new signals are recorded as research only (paper trading itself carries on, so the
  paper record has no gap);
- the trade plan refuses to save a buy (a hard check, `app.plan.calc`).

The state is a `setting_changes` row (key "halt"): rows are only added, so the history
says when Jeron was stopped and why. Nothing else in the database changes.
"""

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SettingChange

HALT_KEY = "halt"
REASON_CHARS = 150  # the row holds 200 characters of JSON


@dataclass(frozen=True)
class Halt:
    reason: str
    since: datetime

    def headline(self) -> str:
        return (
            f"JERON IS STOPPED (since {self.since:%a %-d %b %H:%M}): {self.reason}. No new "
            "buys; exits still apply. To restart: python -m app.cli resume"
        )


def halt_state(session: Session) -> Halt | None:
    """The kill switch, if it is on."""
    row = session.scalar(
        select(SettingChange)
        .where(SettingChange.key == HALT_KEY)
        .order_by(SettingChange.id.desc())
        .limit(1)
    )
    if row is None or row.value is None:
        return None
    try:
        reason = str(json.loads(row.value))
    except ValueError:
        reason = row.value
    return Halt(reason, row.changed_at)


def stop_all(session: Session, reason: str) -> Halt:
    """Turn the kill switch on (again, with a new reason, if it already is). Commits."""
    reason = " ".join(reason.split())[:REASON_CHARS] or "no reason given"
    session.add(SettingChange(key=HALT_KEY, value=json.dumps(reason)))
    session.commit()
    halt = halt_state(session)
    assert halt is not None
    return halt


def resume(session: Session) -> Halt | None:
    """Turn the kill switch off; the stop it ends, or None if it wasn't on. Commits."""
    before = halt_state(session)
    if before is not None:
        session.add(SettingChange(key=HALT_KEY, value=None))
        session.commit()
    return before
