"""Who may call the API (docs/plans/platform-audit-v1.md, slice 1).

The API listens on 127.0.0.1 only and the web app is its one client (the browser never
calls it). Two checks keep everything else out:

- Host: a request whose Host header is not in `JERON_ALLOWED_HOSTS` is refused. This
  stops DNS rebinding, where a hostile web page's own domain is made to resolve to
  127.0.0.1 so the browser sends it requests for this API.
- Token: with `JERON_API_TOKEN` set, every request but `/health` must carry
  `Authorization: Bearer <token>`. The web app sends it from the same `.env`. Without a
  token the API is open to local processes (as before), and the Setup page says so.
"""

import hmac

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings

# Reachable without the token: Docker's health check and the CI smoke test.
OPEN_PATHS = frozenset({"/health"})


def token_ok(header: str | None, token: str) -> bool:
    """True when no token is set, or `header` is exactly "Bearer <token>". Compared in
    constant time."""
    if not token:
        return True
    if not header:
        return False
    return hmac.compare_digest(header.encode(), f"Bearer {token}".encode())


def host_ok(header: str | None, allowed: list[str]) -> bool:
    """The Host header without its port, against the allowed names; "*" allows any."""
    if "*" in allowed:
        return True
    if not header:
        return False
    host = header.strip().lower()
    if host.startswith("["):  # IPv6 literal, "[::1]:8000"
        host = host[: host.find("]") + 1] if "]" in host else host
    else:
        host = host.split(":", 1)[0]
    return host in allowed


class ApiGuard(BaseHTTPMiddleware):
    """Refuses requests from an unknown Host (400) or without the token (401). Reads
    the settings per request, so a test can change them."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        if not host_ok(request.headers.get("host"), settings.allowed_host_list):
            return JSONResponse({"detail": "Unknown host"}, status_code=400)
        if request.url.path not in OPEN_PATHS and not token_ok(
            request.headers.get("authorization"), settings.api_token
        ):
            return JSONResponse(
                {"detail": "Missing or wrong API token (JERON_API_TOKEN)"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)
