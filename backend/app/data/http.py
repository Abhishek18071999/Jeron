"""A polite HTTP client for public market-data files.

NSE's archive server sits behind a bot filter that answers bursts of requests with
403 "Access Denied" for a while, and Yahoo answers bursts with 429. Both are
temporary, so they are retried with a growing pause. A 404 means the file does not
exist (for NSE: no trading that day, or not published yet) and is never retried.
"""

import time
from collections.abc import Callable

import httpx

# NSE's filter rejects some full browser and tool user agents but accepts this one.
DEFAULT_USER_AGENT = "Mozilla/5.0"
RETRY_STATUSES = frozenset({403, 429, 500, 502, 503, 504})


class NotPublishedError(LookupError):
    """The server says the file does not exist (HTTP 404)."""


class FetchError(RuntimeError):
    """The file could not be downloaded after all retries."""


class Fetcher:
    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        min_interval: float = 1.0,
        max_attempts: int = 8,
        backoff: float = 5.0,
        max_backoff: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client or httpx.Client(
            headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "*/*"},
            timeout=30.0,
            follow_redirects=True,
        )
        self.min_interval = min_interval
        self.max_attempts = max_attempts
        self.backoff = backoff
        self.max_backoff = max_backoff
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None

    def _wait_turn(self) -> None:
        if self._last_request is not None:
            wait = self.min_interval - (self._clock() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._clock()

    def get(self, url: str, params: dict[str, str] | None = None) -> bytes:
        last_problem = ""
        for attempt in range(1, self.max_attempts + 1):
            self._wait_turn()
            try:
                response = self._client.get(url, params=params)
            except httpx.TransportError as exc:
                last_problem = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code == 200:
                    return response.content
                if response.status_code == 404:
                    raise NotPublishedError(url)
                if response.status_code not in RETRY_STATUSES:
                    raise FetchError(f"{url}: HTTP {response.status_code}")
                last_problem = f"HTTP {response.status_code}"
            if attempt < self.max_attempts:
                self._sleep(min(self.backoff * attempt, self.max_backoff))
        raise FetchError(f"{url}: gave up after {self.max_attempts} attempts ({last_problem})")
