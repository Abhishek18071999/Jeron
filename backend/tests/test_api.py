from collections.abc import Iterator
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db import get_session
from app.main import app


def test_health_reports_unreachable_database():
    session = MagicMock()
    session.execute.side_effect = OperationalError("SELECT 1", {}, Exception("down"))

    def broken_session() -> Iterator[MagicMock]:
        yield session

    app.dependency_overrides[get_session] = broken_session
    try:
        response = TestClient(app).get("/health")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"status": "degraded", "database": "unreachable"}
