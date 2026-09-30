import httpx
import pytest

from app.data.http import Fetcher, FetchError, NotPublishedError


def fetcher_for(responses, **kwargs):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        status = responses.pop(0)
        return httpx.Response(status, content=b"data" if status == 200 else b"no")

    sleeps = []
    fetcher = Fetcher(
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
        clock=lambda: 0.0,
        **kwargs,
    )
    return fetcher, calls, sleeps


def test_retries_access_denied_then_succeeds():
    fetcher, calls, sleeps = fetcher_for([403, 429, 200], backoff=5)
    assert fetcher.get("https://example.test/f.zip") == b"data"
    assert len(calls) == 3
    assert sleeps.count(5) == 1 and sleeps.count(10) == 1


def test_404_means_not_published_and_is_not_retried():
    fetcher, calls, _ = fetcher_for([404])
    with pytest.raises(NotPublishedError):
        fetcher.get("https://example.test/f.zip")
    assert len(calls) == 1


def test_gives_up_after_max_attempts():
    fetcher, calls, _ = fetcher_for([403] * 3, max_attempts=3)
    with pytest.raises(FetchError, match="gave up after 3 attempts"):
        fetcher.get("https://example.test/f.zip")
    assert len(calls) == 3


def test_other_errors_fail_immediately():
    fetcher, calls, _ = fetcher_for([401])
    with pytest.raises(FetchError, match="HTTP 401"):
        fetcher.get("https://example.test/f.zip")
    assert len(calls) == 1


def test_waits_between_requests():
    fetcher, _, sleeps = fetcher_for([200, 200], min_interval=1.5)
    fetcher.get("https://example.test/a")
    fetcher.get("https://example.test/b")
    assert sleeps == [1.5]
