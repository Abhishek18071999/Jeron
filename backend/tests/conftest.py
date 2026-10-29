import os

import pytest
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from alembic import command

TEST_DATABASE_URL = os.environ.get("JERON_TEST_DATABASE_URL")

requires_db = pytest.mark.skipif(
    TEST_DATABASE_URL is None, reason="set JERON_TEST_DATABASE_URL to run database tests"
)


def reset_database(config: Config) -> None:
    """A migrated database with no data. Runs the migrations when the schema isn't at
    head; otherwise empties every table, which is much faster than running every
    migration down and up for each test (test_migrations.py still does that)."""
    engine = create_engine(TEST_DATABASE_URL or "")
    try:
        head = ScriptDirectory.from_config(config).get_current_head()
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
        if current != head:
            command.downgrade(config, "base")
            command.upgrade(config, "head")
            return
        tables = [t for t in inspect(engine).get_table_names() if t != "alembic_version"]
        if tables:
            names = ", ".join(f'"{t}"' for t in tables)
            with engine.begin() as conn:
                conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    finally:
        engine.dispose()
