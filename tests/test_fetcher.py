"""
Unit tests for ResilientFetcher, Adaptive Batch Fetching, and Rate-Limiting Backoff.
Covers all requirements from user specification:
1. Base HTTP status handling (404, 403, timeout, success).
2. HTTP 200 alone must NOT mean success (empty / SPA hydration shell).
3. All pages successful.
4. One page returns 403 while others succeed.
5. Multiple pages fail (404, 500, connection error).
6. Timeout alongside successful pages.
7. Enough usable sources reached (adaptive stopping early).
8. Not enough usable sources (candidate exhaustion handled).
9. Global concurrency limit is respected.
10. Domain-level concurrency limit is respected.
11. Specific Integration Scenario: 5 candidates (403, success, timeout, success, success) -> 3 usable.
12. 429 -> retry -> success.
13. 429 -> 429 -> 429 -> final failure (max retries exceeded).
14. Retry-After header is respected.
15. 403 -> no retry.
16. 404 -> no retry.
17. Timeout -> retry -> success.
18. 503 -> retry -> success.
19. Jitter does not produce negative or excessive delays.
"""

import asyncio
import pytest
import httpx
from unittest.mock import AsyncMock, patch

from app.tools.fetcher import (
    ResilientFetcher,
    FetchResult,
    AdaptiveFetchReport,
    calculate_backoff_delay,
    parse_retry_after,
)


def _create_mock_response(status_code: int, text: str = "", headers: dict = None) -> httpx.Response:
    resp_headers = headers or {}
    return httpx.Response(
        status_code=status_code,
        text=text,
        headers=resp_headers,
        request=httpx.Request("GET", "https://mock.test/page"),
    )


# 1. Base status tests
@pytest.mark.asyncio
async def test_fetcher_404_handling():
    fetcher = ResilientFetcher(timeout_seconds=2.0, max_retries=2)
    mock_resp = _create_mock_response(404)

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        result = await fetcher.fetch_page("https://mock.test/404")
        assert result.status == "NOT_FOUND_404"
        assert result.status_code == 404
        assert result.is_usable is False
        assert result.total_retries == 0  # 404 must NEVER retry
        assert "not found" in result.rejection_reason.lower()


@pytest.mark.asyncio
async def test_fetcher_403_handling():
    fetcher = ResilientFetcher(timeout_seconds=2.0, max_retries=2)
    mock_resp = _create_mock_response(403)

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        result = await fetcher.fetch_page("https://mock.test/403")
        assert result.status == "BLOCKED_403"
        assert result.status_code == 403
        assert result.is_usable is False
        assert result.total_retries == 0  # 403 must NEVER retry
        assert "blocked" in result.rejection_reason.lower()


@pytest.mark.asyncio
async def test_fetcher_timeout_handling():
    fetcher = ResilientFetcher(timeout_seconds=1.0, max_retries=0)

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.TimeoutException("Timed out")
        result = await fetcher.fetch_page("https://mock.test/timeout")
        assert result.status == "TIMEOUT"
        assert result.is_usable is False
        assert "timed out" in result.rejection_reason.lower()


@pytest.mark.asyncio
async def test_fetcher_success_extraction():
    fetcher = ResilientFetcher(timeout_seconds=2.0)
    html_sample = "<html><body><article><p>" + ("Zepto operates quick-commerce dark stores across Indian metro cities. " * 10) + "</p></article></body></html>"
    mock_resp = _create_mock_response(200, text=html_sample)

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        result = await fetcher.fetch_page("https://mock.test/article")
        assert result.status == "SUCCESS"
        assert result.status_code == 200
        assert result.is_usable is True
        assert "Zepto" in result.extracted_text


# 2. HTTP 200 alone must NOT mean success (empty / SPA hydration shell)
@pytest.mark.asyncio
async def test_200_response_with_empty_content():
    fetcher = ResilientFetcher(timeout_seconds=2.0)
    # 200 response with only empty SPA root div
    spa_html = "<html><body><div id='root'></div><script src='bundle.js'></script></body></html>"
    mock_resp = _create_mock_response(200, text=spa_html)

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        result = await fetcher.fetch_page("https://mock.test/spa")
        assert result.status_code == 200
        # Must NOT be marked usable!
        assert result.is_usable is False
        assert result.status == "EMPTY_CONTENT"
        assert "empty" in result.rejection_reason.lower() or "brief" in result.rejection_reason.lower()


# 3. All pages successful
@pytest.mark.asyncio
async def test_all_pages_successful():
    fetcher = ResilientFetcher(timeout_seconds=2.0)
    urls = ["https://mock.test/p1", "https://mock.test/p2", "https://mock.test/p3"]
    good_html = "<html><body><p>" + ("Titan opened over 90 new retail stores across India during FY24. " * 10) + "</p></body></html>"
    mock_resp = _create_mock_response(200, text=good_html)

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        report = await fetcher.fetch_with_adaptive_stopping(urls, min_usable=3, max_concurrency=3)
        assert report.candidates_evaluated == 3
        assert report.successful_usable_count == 3
        assert report.blocked_count == 0
        assert report.failed_count == 0
        assert report.threshold_reached is True
        assert len(report.usable_results) == 3


# 4. One page returns 403 while others succeed
@pytest.mark.asyncio
async def test_one_page_403_while_others_succeed():
    fetcher = ResilientFetcher(timeout_seconds=2.0)
    urls = ["https://mock.test/blocked", "https://mock.test/good1", "https://mock.test/good2"]
    good_html = "<html><body><p>" + ("Kalyan Jewellers added 71 showrooms across non-south markets. " * 10) + "</p></body></html>"

    async def mock_router(url):
        if "blocked" in str(url):
            return _create_mock_response(403)
        return _create_mock_response(200, text=good_html)

    with patch.object(httpx.AsyncClient, "get", side_effect=mock_router):
        report = await fetcher.fetch_with_adaptive_stopping(urls, min_usable=2, max_concurrency=3)
        assert report.successful_usable_count == 2
        assert report.blocked_count == 1
        assert report.threshold_reached is True
        # Verify 403 failure reason was preserved
        blocked_item = next(r for r in report.all_results if "blocked" in r.url)
        assert blocked_item.status == "BLOCKED_403"
        assert blocked_item.is_usable is False
        assert "blocked by host" in blocked_item.rejection_reason.lower()


# 5. Multiple pages fail
@pytest.mark.asyncio
async def test_multiple_pages_fail():
    fetcher = ResilientFetcher(timeout_seconds=2.0, max_retries=0)
    urls = ["https://mock.test/404", "https://mock.test/500", "https://mock.test/err"]

    async def mock_router(url):
        u = str(url)
        if "404" in u:
            return _create_mock_response(404)
        elif "500" in u:
            return _create_mock_response(500)
        else:
            raise httpx.ConnectError("Failed to resolve host")

    with patch.object(httpx.AsyncClient, "get", side_effect=mock_router):
        report = await fetcher.fetch_with_adaptive_stopping(urls, min_usable=2, max_concurrency=3)
        assert report.successful_usable_count == 0
        assert report.failed_count == 3
        assert report.threshold_reached is False
        for res in report.all_results:
            assert res.is_usable is False
            assert res.rejection_reason is not None


# 6. Timeout alongside successful pages
@pytest.mark.asyncio
async def test_timeout_alongside_successful_pages():
    fetcher = ResilientFetcher(timeout_seconds=2.0, max_retries=0)
    urls = ["https://mock.test/timeout", "https://mock.test/good"]
    good_html = "<html><body><p>" + ("Blinkit reported strong revenue growth in the previous quarter of operations. " * 10) + "</p></body></html>"

    async def mock_router(url):
        if "timeout" in str(url):
            raise httpx.TimeoutException("Read timed out")
        return _create_mock_response(200, text=good_html)

    with patch.object(httpx.AsyncClient, "get", side_effect=mock_router):
        report = await fetcher.fetch_with_adaptive_stopping(urls, min_usable=1, max_concurrency=2)
        assert report.successful_usable_count == 1
        assert report.failed_count == 1
        assert report.threshold_reached is True
        timed_out = next(r for r in report.all_results if "timeout" in r.url)
        assert timed_out.status == "TIMEOUT"


# 7. Enough usable sources reached (Adaptive early stopping)
@pytest.mark.asyncio
async def test_enough_usable_sources_reached_early_stopping():
    fetcher = ResilientFetcher(timeout_seconds=2.0)
    urls = [f"https://mock.test/page_{i}" for i in range(1, 7)]
    good_html = "<html><body><p>" + ("Titan and Kalyan Jewellers opened physical stores across India in 2024. " * 10) + "</p></body></html>"

    fetch_call_count = 0

    async def mock_router(url):
        nonlocal fetch_call_count
        fetch_call_count += 1
        return _create_mock_response(200, text=good_html)

    with patch.object(httpx.AsyncClient, "get", side_effect=mock_router):
        report = await fetcher.fetch_with_adaptive_stopping(urls, min_usable=2, max_concurrency=2)
        assert report.threshold_reached is True
        assert report.successful_usable_count == 2
        # Evaluated only 2 candidates instead of all 6
        assert report.candidates_evaluated == 2
        assert fetch_call_count == 2


# 8. Not enough usable sources (candidate exhaustion handled)
@pytest.mark.asyncio
async def test_not_enough_usable_sources_exhaustion():
    fetcher = ResilientFetcher(timeout_seconds=2.0, max_retries=0)
    urls = ["https://mock.test/p1_good", "https://mock.test/p2_403", "https://mock.test/p3_404"]
    good_html = "<html><body><p>" + ("Swiggy Instamart operates 600+ dark stores in major metros. " * 10) + "</p></body></html>"

    async def mock_router(url):
        u = str(url)
        if "p2_403" in u:
            return _create_mock_response(403)
        if "p3_404" in u:
            return _create_mock_response(404)
        return _create_mock_response(200, text=good_html)

    with patch.object(httpx.AsyncClient, "get", side_effect=mock_router):
        report = await fetcher.fetch_with_adaptive_stopping(urls, min_usable=3, max_concurrency=3)
        assert report.threshold_reached is False
        assert report.successful_usable_count == 1
        assert report.blocked_count == 1
        assert report.failed_count == 1
        assert report.candidates_evaluated == 3


# 9. Concurrency limit is respected
@pytest.mark.asyncio
async def test_concurrency_limit_respected():
    fetcher = ResilientFetcher(timeout_seconds=2.0)
    urls = [f"https://mock{i}.test/page_{i}" for i in range(10)]
    max_concurrency = 3
    active_requests = 0
    peak_concurrency = 0

    async def mock_counted_router(url):
        nonlocal active_requests, peak_concurrency
        active_requests += 1
        if active_requests > peak_concurrency:
            peak_concurrency = active_requests
        await asyncio.sleep(0.02)
        active_requests -= 1
        return _create_mock_response(200, text="<html><body><p>" + ("Substantive text content. " * 20) + "</p></body></html>")

    with patch.object(httpx.AsyncClient, "get", side_effect=mock_counted_router):
        report = await fetcher.fetch_with_adaptive_stopping(urls, min_usable=5, max_concurrency=max_concurrency)
        assert peak_concurrency <= max_concurrency
        assert report.successful_usable_count == 5


# 10. Domain concurrency limit is respected
@pytest.mark.asyncio
async def test_domain_concurrency_limit_respected():
    fetcher = ResilientFetcher(timeout_seconds=2.0, max_concurrency=5, max_per_domain_concurrency=2)
    urls = [f"https://same-domain.test/article_{i}" for i in range(6)]
    active_domain_requests = 0
    peak_domain_concurrency = 0

    async def mock_domain_router(url):
        nonlocal active_domain_requests, peak_domain_concurrency
        active_domain_requests += 1
        if active_domain_requests > peak_domain_concurrency:
            peak_domain_concurrency = active_domain_requests
        await asyncio.sleep(0.02)
        active_domain_requests -= 1
        return _create_mock_response(200, text="<html><body><p>" + ("Domain rate limited evidence text. " * 20) + "</p></body></html>")

    with patch.object(httpx.AsyncClient, "get", side_effect=mock_domain_router):
        report = await fetcher.fetch_with_adaptive_stopping(urls, min_usable=4, max_concurrency=5)
        # Even with max_concurrency=5, max_per_domain_concurrency=2 caps parallel hits to the same domain!
        assert peak_domain_concurrency <= 2
        assert report.threshold_reached is True
        assert report.successful_usable_count >= 4


# 11. Specific Integration Scenario: 5 candidates (403, success, timeout, success, success) -> 3 usable
@pytest.mark.asyncio
async def test_five_candidates_integration_scenario():
    fetcher = ResilientFetcher(timeout_seconds=2.0, max_retries=0)
    candidate_urls = [
        "https://mock.test/url1_403",
        "https://mock.test/url2_success",
        "https://mock.test/url3_timeout",
        "https://mock.test/url4_success",
        "https://mock.test/url5_success",
    ]

    valid_html = "<html><body><article><p>" + ("Verified factual evidence regarding quick commerce funding and expansion in India. " * 10) + "</p></article></body></html>"

    async def scenario_router(url):
        u = str(url)
        if "url1_403" in u:
            return _create_mock_response(403)
        elif "url2_success" in u:
            return _create_mock_response(200, text=valid_html)
        elif "url3_timeout" in u:
            raise httpx.TimeoutException("Server took too long to respond")
        elif "url4_success" in u:
            return _create_mock_response(200, text=valid_html)
        elif "url5_success" in u:
            return _create_mock_response(200, text=valid_html)
        return _create_mock_response(404)

    with patch.object(httpx.AsyncClient, "get", side_effect=scenario_router):
        report = await fetcher.fetch_with_adaptive_stopping(
            candidate_urls=candidate_urls,
            min_usable=3,
            max_concurrency=3,
        )

        assert report.candidates_evaluated == 5
        assert report.successful_usable_count == 3
        assert report.threshold_reached is True
        usable_urls = [r.url for r in report.usable_results]
        assert "https://mock.test/url2_success" in usable_urls
        assert "https://mock.test/url4_success" in usable_urls
        assert "https://mock.test/url5_success" in usable_urls

        assert report.blocked_count == 1
        assert report.failed_count == 1

        url1_rec = next(r for r in report.all_results if "url1_403" in r.url)
        assert url1_rec.status == "BLOCKED_403"
        assert url1_rec.is_usable is False

        url3_rec = next(r for r in report.all_results if "url3_timeout" in r.url)
        assert url3_rec.status == "TIMEOUT"
        assert url3_rec.is_usable is False


# 12. 429 -> retry -> success
@pytest.mark.asyncio
async def test_429_retry_success():
    fetcher = ResilientFetcher(timeout_seconds=2.0, max_retries=3, base_delay=1.0)
    valid_html = "<html><body><p>" + ("Zomato Hyperpure revenue surged this financial year. " * 10) + "</p></body></html>"
    calls = 0

    async def mock_router(url):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _create_mock_response(429)
        return _create_mock_response(200, text=valid_html)

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with patch.object(httpx.AsyncClient, "get", side_effect=mock_router):
            result = await fetcher.fetch_page("https://mock.test/429_then_good")
            assert result.status == "SUCCESS"
            assert result.is_usable is True
            assert calls == 2
            assert result.total_retries == 1
            assert len(result.retry_attempts) == 1
            assert result.retry_attempts[0].status_code == 429
            assert result.retry_attempts[0].final_result == "RETRYING"
            mock_sleep.assert_called_once()


# 13. 429 -> 429 -> 429 -> final failure (max retries exceeded)
@pytest.mark.asyncio
async def test_429_max_retries_exceeded():
    fetcher = ResilientFetcher(timeout_seconds=2.0, max_retries=3, base_delay=1.0)
    calls = 0

    async def mock_router(url):
        nonlocal calls
        calls += 1
        return _create_mock_response(429)

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with patch.object(httpx.AsyncClient, "get", side_effect=mock_router):
            result = await fetcher.fetch_page("https://mock.test/429_always")
            assert result.status == "RATE_LIMITED_429"
            assert result.is_usable is False
            # 1 initial call + 3 retries = 4 calls total
            assert calls == 4
            assert result.total_retries == 4
            assert result.retry_attempts[-1].final_result == "MAX_RETRIES_EXCEEDED"
            assert "exceeded max retries" in result.rejection_reason.lower()
            assert mock_sleep.call_count == 3


# 14. Retry-After header is respected
@pytest.mark.asyncio
async def test_retry_after_is_respected():
    fetcher = ResilientFetcher(timeout_seconds=2.0, max_retries=3, base_delay=1.0, max_delay=8.0)
    valid_html = "<html><body><p>" + ("Content delivered after rate limit cool-down period. " * 10) + "</p></body></html>"
    calls = 0

    async def mock_router(url):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _create_mock_response(429, headers={"Retry-After": "3.5"})
        return _create_mock_response(200, text=valid_html)

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with patch.object(httpx.AsyncClient, "get", side_effect=mock_router):
            result = await fetcher.fetch_page("https://mock.test/retry_after_url")
            assert result.status == "SUCCESS"
            assert result.is_usable is True
            assert result.retry_attempts[0].retry_after_header == "3.5"
            assert result.retry_attempts[0].actual_wait_time == 3.5
            mock_sleep.assert_called_once_with(3.5)


# 15. 403 -> no retry
@pytest.mark.asyncio
async def test_403_no_retry():
    fetcher = ResilientFetcher(timeout_seconds=2.0, max_retries=3)
    calls = 0

    async def mock_router(url):
        nonlocal calls
        calls += 1
        return _create_mock_response(403)

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with patch.object(httpx.AsyncClient, "get", side_effect=mock_router):
            result = await fetcher.fetch_page("https://mock.test/forbidden")
            assert result.status == "BLOCKED_403"
            assert result.is_usable is False
            assert calls == 1  # Exactly 1 call, zero retries
            assert result.total_retries == 0
            mock_sleep.assert_not_called()


# 16. 404 -> no retry
@pytest.mark.asyncio
async def test_404_no_retry():
    fetcher = ResilientFetcher(timeout_seconds=2.0, max_retries=3)
    calls = 0

    async def mock_router(url):
        nonlocal calls
        calls += 1
        return _create_mock_response(404)

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with patch.object(httpx.AsyncClient, "get", side_effect=mock_router):
            result = await fetcher.fetch_page("https://mock.test/not_found")
            assert result.status == "NOT_FOUND_404"
            assert result.is_usable is False
            assert calls == 1  # Exactly 1 call, zero retries
            assert result.total_retries == 0
            mock_sleep.assert_not_called()


# 17. Timeout -> retry -> success
@pytest.mark.asyncio
async def test_timeout_retry_success():
    fetcher = ResilientFetcher(timeout_seconds=2.0, max_retries=3, base_delay=1.0)
    valid_html = "<html><body><p>" + ("Tata Consumer Products expanded distribution networks successfully. " * 10) + "</p></body></html>"
    calls = 0

    async def mock_router(url):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.TimeoutException("Read timed out on initial connection")
        return _create_mock_response(200, text=valid_html)

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with patch.object(httpx.AsyncClient, "get", side_effect=mock_router):
            result = await fetcher.fetch_page("https://mock.test/timeout_then_good")
            assert result.status == "SUCCESS"
            assert result.is_usable is True
            assert calls == 2
            assert result.total_retries == 1
            assert result.retry_attempts[0].error_type == "TIMEOUT"
            mock_sleep.assert_called_once()


# 18. 503 -> retry -> success
@pytest.mark.asyncio
async def test_503_retry_success():
    fetcher = ResilientFetcher(timeout_seconds=2.0, max_retries=3, base_delay=1.0)
    valid_html = "<html><body><p>" + ("Tata Neu app active user metrics published in annual report. " * 10) + "</p></body></html>"
    calls = 0

    async def mock_router(url):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _create_mock_response(503)
        return _create_mock_response(200, text=valid_html)

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with patch.object(httpx.AsyncClient, "get", side_effect=mock_router):
            result = await fetcher.fetch_page("https://mock.test/503_then_good")
            assert result.status == "SUCCESS"
            assert result.is_usable is True
            assert calls == 2
            assert result.total_retries == 1
            assert result.retry_attempts[0].status_code == 503
            mock_sleep.assert_called_once()


# 19. Jitter does not produce negative or excessive delays
def test_jitter_does_not_produce_negative_or_excessive_delays():
    base_delay = 1.0
    max_delay = 8.0
    jitter_max = 0.5

    for attempt in range(5):
        delays = []
        for _ in range(50):
            calc_delay, actual_wait, _ = calculate_backoff_delay(
                attempt=attempt,
                base_delay=base_delay,
                max_delay=max_delay,
                jitter=True,
                jitter_max=jitter_max,
            )
            # Never negative
            assert actual_wait >= 0.0, f"Delay {actual_wait} was negative!"
            # Never excessive (capped at max_delay + jitter_max)
            assert actual_wait <= (max_delay + jitter_max + 0.01), f"Delay {actual_wait} exceeded ceiling!"
            # Must be at least calculated exponential delay
            assert actual_wait >= calc_delay, f"Actual wait {actual_wait} was lower than calc delay {calc_delay}!"
            delays.append(actual_wait)

        # Check jitter non-determinism: not all 50 samples should be identical
        assert len(set(delays)) > 1, f"Jitter did not randomize delays for attempt {attempt}!"
