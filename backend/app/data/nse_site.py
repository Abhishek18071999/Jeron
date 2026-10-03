"""NSE's main website (www.nseindia.com): corporate filings, board meetings and
announcements, served as JSON to the site's own pages.

Unlike the archive, the site wants the cookies it sets on its home page, so the client
visits the home page first and again whenever the API stops answering.
"""

from datetime import date

import httpx

from app.data.http import DEFAULT_USER_AGENT, Fetcher, FetchError

SITE = "https://www.nseindia.com"
BOARD_MEETINGS = "/api/corporate-board-meetings"
_DAY = "%d-%m-%Y"


class NseSite:
    def __init__(self, fetcher: Fetcher | None = None, *, min_interval: float = 1.0) -> None:
        self.fetcher = fetcher or Fetcher(
            httpx.Client(
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": f"{SITE}/",
                },
                timeout=30.0,
                follow_redirects=True,
            ),
            min_interval=min_interval,
            max_attempts=4,
        )
        self._warm = False

    def _home(self) -> None:
        self.fetcher.get(f"{SITE}/")
        self._warm = True

    def get(self, path: str, params: dict[str, str]) -> bytes:
        if not self._warm:
            self._home()
        try:
            return self.fetcher.get(f"{SITE}{path}", params)
        except FetchError:
            # The cookies may have expired: visit the home page and try once more.
            self._home()
            return self.fetcher.get(f"{SITE}{path}", params)

    def board_meetings(self, start: date, end: date) -> bytes:
        """Board meetings with a meeting date from `start` to `end`, as NSE's JSON."""
        return self.get(
            BOARD_MEETINGS,
            {"index": "equities", "from_date": f"{start:{_DAY}}", "to_date": f"{end:{_DAY}}"},
        )
