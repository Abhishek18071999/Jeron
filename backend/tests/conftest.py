import os

import pytest

TEST_DATABASE_URL = os.environ.get("JERON_TEST_DATABASE_URL")

requires_db = pytest.mark.skipif(
    TEST_DATABASE_URL is None, reason="set JERON_TEST_DATABASE_URL to run database tests"
)
