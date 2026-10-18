"""Settings changed on the Settings page.

The `JERON_` env values (app/config.py) are the defaults. A change made on the page is
stored as a new `setting_changes` row and wins over the env value from then on; rows
are never changed, so the history says what was in force when. Only the risk and alert
settings below can be changed this way: secrets and connections stay in `.env`.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import SettingChange


@dataclass(frozen=True)
class Editable:
    label: str
    help: str


EDITABLE: dict[str, Editable] = {
    "capital": Editable(
        "Capital (₹)", "What position sizes and portfolio heat are measured against."
    ),
    "risk_pct": Editable("Risk per trade (%)", "Share of capital at risk per trade, 0.5 to 2."),
    "max_positions_swing": Editable("Swing positions at most", "Open swing trades at once."),
    "max_positions_positional": Editable(
        "Positional positions at most", "Open positional trades at once."
    ),
    "max_positions_invest": Editable(
        "Long-term positions at most", "Open long-term investments at once."
    ),
    "sector_cap_pct": Editable("Sector cap (%)", "Most of capital in one sector."),
    "idle_cash_in_index": Editable(
        "Park idle cash in an index fund",
        "On: Jeron says to keep idle cash in a Nifty index fund instead of a liquid fund. "
        "More return when the market rises, and you share its falls (Nifty 500 fell 38% "
        "at worst from 2019 to 2025). The backtest's dotted line shows the effect.",
    ),
    "alert_research_signals": Editable(
        "Alert research-only signals",
        "Also send signals of strategies that failed section 6, clearly marked. "
        "Off: they are only in the daily summary.",
    ),
    "news_monthly_budget_usd": Editable(
        "News labels: monthly cap (US$)",
        "The labeller stops for the month at this estimated spend. 0 turns the cap off.",
    ),
}


class SettingsError(ValueError):
    pass


def _adapter(key: str) -> TypeAdapter[Any]:
    field = Settings.model_fields[key]
    if not field.metadata:
        return TypeAdapter(field.annotation)
    return TypeAdapter(Annotated[field.annotation, *field.metadata])


def validate(key: str, value: Any) -> Any:
    """The value in its proper type; SettingsError in plain words when it doesn't fit."""
    if key not in EDITABLE:
        raise SettingsError(f"{key} can't be changed here")
    try:
        return _adapter(key).validate_python(value)
    except ValidationError as exc:
        reason = exc.errors()[0]["msg"]
        raise SettingsError(f"{EDITABLE[key].label}: {reason[0].lower()}{reason[1:]}") from exc


@dataclass(frozen=True)
class Override:
    value: Any
    changed_at: datetime


def overrides(session: Session) -> dict[str, Override]:
    """The latest change per key, when it isn't "back to the env value"."""
    latest = (
        select(SettingChange.key, func.max(SettingChange.id).label("id"))
        .group_by(SettingChange.key)
        .subquery()
    )
    rows = session.execute(
        select(SettingChange.key, SettingChange.value, SettingChange.changed_at).join(
            latest, SettingChange.id == latest.c.id
        )
    )
    found = {}
    for key, value, changed_at in rows:
        if key not in EDITABLE or value is None:
            continue
        try:
            found[key] = Override(validate(key, json.loads(value)), changed_at)
        except (SettingsError, ValueError):
            continue  # a stored value the current rules reject: the env value applies
    return found


def effective_settings(session: Session, base: Settings | None = None) -> Settings:
    """The env settings with the Settings page's changes applied."""
    base = base or get_settings()
    changes = {k: o.value for k, o in overrides(session).items()}
    return base.model_copy(update=changes) if changes else base


def save_settings(session: Session, changes: dict[str, Any]) -> Settings:
    """Store each change that differs from what is in force (None: back to the env
    value). All are checked before any is stored. Commits."""
    current = effective_settings(session)
    stored = overrides(session)
    rows = []
    for key, raw in changes.items():
        if raw is None:
            if key not in EDITABLE:
                raise SettingsError(f"{key} can't be changed here")
            if key in stored:
                rows.append(SettingChange(key=key, value=None))
            continue
        value = validate(key, raw)
        if value != getattr(current, key):
            rows.append(SettingChange(key=key, value=json.dumps(value)))
    session.add_all(rows)
    session.commit()
    return effective_settings(session)
