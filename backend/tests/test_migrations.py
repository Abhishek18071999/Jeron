"""Runs the real migrations against a throwaway Postgres database."""

from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from alembic import command
from app import models  # noqa: F401  (registers the tables)
from app.config import get_settings
from app.db import Base
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
        "source_files",
        "index_bars",
        "security_status",
        "surveillance_flags",
        "symbol_changes",
        "scan_runs",
        "scan_results",
    } <= tables
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")


@requires_db
def test_models_match_migrations(alembic_config):
    command.upgrade(alembic_config, "head")
    with create_engine(TEST_DATABASE_URL or "").connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
