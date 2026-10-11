"""Settings changed on the Settings page win over `.env`, are checked, and are kept as
history; the risk code reads them."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import get_settings
from app.main import app
from app.models import SettingChange
from app.settings_store import SettingsError, effective_settings, save_settings, validate
from tests.conftest import requires_db
from tests.test_alerts_db import empty_session as empty_session  # noqa: F401 - the fixture

pytestmark = requires_db


def test_validate_uses_the_settings_rules():
    assert validate("risk_pct", "1.5") == 1.5
    assert validate("alert_research_signals", True) is True
    with pytest.raises(SettingsError, match="Risk per trade"):
        validate("risk_pct", 5)
    with pytest.raises(SettingsError, match="can't be changed"):
        validate("telegram_bot_token", "x")


def test_changes_override_env_and_keep_history(empty_session):
    s = empty_session
    env = get_settings()
    assert effective_settings(s).risk_pct == env.risk_pct
    save_settings(s, {"risk_pct": 0.5, "capital": 500000})
    now = effective_settings(s)
    assert (now.risk_pct, now.capital) == (0.5, 500000)
    save_settings(s, {"risk_pct": 0.5})  # unchanged: nothing stored
    save_settings(s, {"risk_pct": 0.75})
    assert effective_settings(s).risk_pct == 0.75
    assert s.scalar(select(func.count()).select_from(SettingChange)) == 3
    save_settings(s, {"risk_pct": None})  # back to .env
    assert effective_settings(s).risk_pct == env.risk_pct
    assert effective_settings(s).capital == 500000


def test_a_bad_value_stores_nothing(empty_session):
    s = empty_session
    with pytest.raises(SettingsError):
        save_settings(s, {"capital": 100, "sector_cap_pct": 150})
    s.rollback()
    assert s.scalar(select(func.count()).select_from(SettingChange)) == 0


def test_api(empty_session):
    client = TestClient(app)
    view = client.get("/settings").json()
    keys = [r["key"] for r in view["settings"]]
    assert "risk_pct" in keys and "news_monthly_budget_usd" in keys
    assert "telegram_bot_token" not in keys
    assert view["news_spend"]["spent_usd"] == "0"
    # The page sends every field, as text, and booleans.
    every = {row["key"]: str(row["value"]) for row in view["settings"]}
    every["alert_research_signals"] = False
    every["max_positions_swing"] = "3"
    r = client.put("/settings", json={"changes": every})
    assert r.status_code == 200
    row = next(x for x in r.json()["settings"] if x["key"] == "max_positions_swing")
    assert row["value"] == 3 and row["changed_at"] is not None
    bad = client.put("/settings", json={"changes": {"risk_pct": 9}})
    assert bad.status_code == 422 and "Risk per trade" in bad.json()["detail"]
