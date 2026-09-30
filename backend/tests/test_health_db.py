from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import get_engine
from app.main import app
from tests.conftest import TEST_DATABASE_URL, requires_db


@requires_db
def test_health_with_real_database(monkeypatch):
    monkeypatch.setenv("JERON_DATABASE_URL", TEST_DATABASE_URL or "")
    get_settings.cache_clear()
    get_engine.cache_clear()
    try:
        response = TestClient(app).get("/health")
    finally:
        get_settings.cache_clear()
        get_engine.cache_clear()
    assert response.json() == {"status": "ok", "database": "ok"}
