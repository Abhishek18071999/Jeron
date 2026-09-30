"""Runs the real migrations against a throwaway Postgres database."""

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from app.config import get_settings
from tests.conftest import TEST_DATABASE_URL, requires_db

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def alembic_config(monkeypatch):
    monkeypatch.setenv("JERON_DATABASE_URL", TEST_DATABASE_URL or "")
    get_settings.cache_clear()
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    yield config
    get_settings.cache_clear()


@requires_db
def test_upgrade_and_downgrade(alembic_config):
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    tables = set(inspect(create_engine(TEST_DATABASE_URL)).get_table_names())
    assert {
        "instruments",
        "daily_bars",
        "corporate_actions",
        "index_memberships",
        "data_quality_reports",
        "users",
    } <= tables
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
