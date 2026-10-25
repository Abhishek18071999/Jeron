"""The API's Host check and token (app/api/security.py)."""

import re

import pytest
from fastapi.testclient import TestClient

from app.api.security import OPEN_PATHS, host_ok, token_ok
from app.config import get_settings
from app.main import app

TOKEN = "s3cret-token-for-tests"


@pytest.fixture
def settings_env(monkeypatch: pytest.MonkeyPatch):
    def set_env(**values: str) -> None:
        for key, value in values.items():
            monkeypatch.setenv(f"JERON_{key.upper()}", value)
        get_settings.cache_clear()

    yield set_env
    get_settings.cache_clear()


def test_token_ok() -> None:
    assert token_ok(None, "")  # no token set: open, as before
    assert token_ok("anything", "")
    assert token_ok(f"Bearer {TOKEN}", TOKEN)
    assert not token_ok(None, TOKEN)
    assert not token_ok("", TOKEN)
    assert not token_ok(TOKEN, TOKEN)  # the scheme is required
    assert not token_ok(f"bearer {TOKEN}", TOKEN)
    assert not token_ok(f"Bearer {TOKEN}x", TOKEN)
    assert not token_ok(f"Bearer {TOKEN[:-1]}", TOKEN)


def test_host_ok() -> None:
    allowed = ["localhost", "127.0.0.1", "backend"]
    assert host_ok("localhost:8000", allowed)
    assert host_ok("BACKEND:8000", allowed)
    assert host_ok("127.0.0.1", allowed)
    assert not host_ok("evil.example", allowed)
    assert not host_ok("evil.example:8000", allowed)
    assert not host_ok("localhost.evil.example", allowed)
    assert not host_ok(None, allowed)
    assert not host_ok("", allowed)
    assert host_ok("[::1]:8000", ["[::1]"])
    assert host_ok("evil.example", ["*"])


def test_open_without_a_token(settings_env) -> None:
    settings_env(api_token="")
    assert TestClient(app).get("/openapi.json").status_code == 200


def test_token_required_when_set(settings_env) -> None:
    settings_env(api_token=TOKEN)
    client = TestClient(app)
    assert client.get("/openapi.json").status_code == 401
    wrong = client.get("/openapi.json", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    assert wrong.headers["www-authenticate"] == "Bearer"
    ok = client.get("/openapi.json", headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200


def test_health_needs_no_token(settings_env) -> None:
    settings_env(api_token=TOKEN)
    # The database may be unreachable here; the point is that it isn't a 401.
    assert TestClient(app).get("/health").status_code == 200


def test_unknown_host_refused(settings_env) -> None:
    settings_env(api_token=TOKEN)
    auth = {"Authorization": f"Bearer {TOKEN}"}
    rebound = TestClient(app, base_url="http://evil.example:8000")
    assert rebound.get("/health").status_code == 400
    assert rebound.get("/openapi.json", headers=auth).status_code == 400
    compose = TestClient(app, base_url="http://backend:8000")
    assert compose.get("/openapi.json", headers=auth).status_code == 200


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def test_every_route_is_guarded(settings_env) -> None:
    """Server-side: every route but /health refuses a request without the token, for
    every method it serves, before any handler or database work runs."""
    settings_env(api_token=TOKEN)
    client = TestClient(app)
    checked = 0
    for path, methods in app.openapi()["paths"].items():
        if path in OPEN_PATHS:
            continue
        for method in methods:
            res = client.request(method.upper(), _concrete(path))
            assert res.status_code == 401, f"{method} {path} answered {res.status_code}"
            checked += 1
    assert checked > 40  # the API's routes were really walked
