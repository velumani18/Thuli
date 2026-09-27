"""
Resilient Web Page Fetcher, Adaptive Content Extractor, and Rate-Limit Handler.

Features:
- Handles web failure modes independently (403 bot blocks, 404 dead links, timeouts, empty SPAs)
- Robust exponential backoff with jitter for temporary errors (429, 408, 502, 503, 504, timeouts)
- Respects HTTP Retry-After header when present
- Never retries permanent failures (401, 403, 404, 410)
- Global and domain-level concurrency limiting via asyncio Semaphores
- Comprehensive telemetry on every candidate URL and retry attempt
- Adaptive early stopping once MIN_USABLE_SOURCES is satisfied
"""

import asyncio
import email.utils
import random
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Optional, Literal
from pydantic import BaseModel, Field
import httpx
import trafilatura
from bs4 import BeautifulSoup
import json

from app.core.config import settings

# Retryable vs Non-retryable definitions
RETRYABLE_STATUS_CODES = {408, 429, 502, 503, 504}
NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404, 405, 410, 422}


class RetryAttemptLog(BaseModel):
    url: str
    domain: str
    attempt_number: int  # 1-indexed (1st retry, 2nd retry, etc.)
    status_code: Optional[int] = None
    error_type: Optional[str] = None
    calculated_delay: float
    retry_after_header: Optional[str] = None
    actual_wait_time: float
    final_result: str  # "RETRYING", "MAX_RETRIES_EXCEEDED"


class FetchResult(BaseModel):
    url: str
    domain: str = ""
    status: Literal["SUCCESS", "BLOCKED_403", "NOT_FOUND_404", "RATE_LIMITED_429", "TIMEOUT", "EMPTY_CONTENT", "SERVER_ERROR", "ERROR"]
    status_code: Optional[int] = None
    title: Optional[str] = None
    extracted_text: str = ""
    character_count: int = 0
    duration_ms: float = 0.0
    start_time_iso: Optional[str] = None
    end_time_iso: Optional[str] = None
    is_usable: bool = False
    rejection_reason: Optional[str] = None
    error_message: Optional[str] = None
    total_retries: int = 0
    retry_attempts: list[RetryAttemptLog] = Field(default_factory=list)


class AdaptiveFetchReport(BaseModel):
    candidates_evaluated: int = 0
    successful_usable_count: int = 0
    blocked_count: int = 0
    failed_count: int = 0
    total_fetch_time_ms: float = 0.0
    threshold_reached: bool = False
    total_retries_performed: int = 0
    retry_logs: list[RetryAttemptLog] = Field(default_factory=list)
    usable_results: list[FetchResult] = Field(default_factory=list)
    all_results: list[FetchResult] = Field(default_factory=list)


def parse_retry_after(header_value: Optional[str]) -> Optional[float]:
    """
    Parses an HTTP Retry-After header value.
    Supports integer/float seconds and RFC 7231 / RFC 2822 HTTP-date formats.
    Returns wait seconds as a float if valid and > 0, otherwise None.
    """
    if not header_value:
        return None
    val = header_value.strip()
    
    # 1. Try numeric seconds
    try:
        sec = float(val)
        return max(0.0, sec)
    except ValueError:
        pass

    # 2. Try HTTP date string (e.g., "Wed, 21 Oct 2026 07:28:00 GMT")
    try:
        dt = email.utils.parsedate_to_datetime(val)
        if dt is not None:
            now = datetime.now(timezone.utc)
            delta = (dt - now).total_seconds()
            return max(0.0, delta)
    except Exception:
        pass

    return None


def calculate_backoff_delay(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 8.0,
    retry_after_header: Optional[str] = None,
    jitter: bool = True,
    jitter_max: float = 0.5,
) -> tuple[float, float, Optional[str]]:
    """
    Calculates exponential backoff with jitter and respects Retry-After headers.

    Formula:
        delay = min(max_delay, base_delay * (2 ** attempt))

    If Retry-After is present and valid, it is respected subject to max_delay.
    Jitter adds a small positive offset bounded by jitter_max.
    Never returns negative or excessive delays.

    Returns:
        (calculated_delay, actual_wait_time, retry_after_header_value)
    """
    # 1. Check Retry-After header first
    parsed_retry = parse_retry_after(retry_after_header)
    if parsed_retry is not None:
        wait_time = min(max_delay, parsed_retry)
        return round(wait_time, 3), round(wait_time, 3), retry_after_header

    # 2. Exponential delay calculation
    calc_delay = min(max_delay, base_delay * (2 ** attempt))

    # 3. Add small random jitter (ensures non-negative and non-excessive delay)
    if jitter:
        upper_bound = min(jitter_max, max(0.1, calc_delay * 0.25))
        jitter_offset = random.uniform(0.05, upper_bound)
        actual_wait = min(max_delay + jitter_max, calc_delay + jitter_offset)
    else:
        actual_wait = calc_delay

    return round(calc_delay, 3), round(actual_wait, 3), None


class UniversalContentExtractor:
    """
    Universal, multi-tier web page content extractor.
    Handles articles, news, tables, SPAs, structured schemas, e-commerce, and wikis.
    """

    @staticmethod
    def extract_tables_as_markdown(soup: BeautifulSoup, max_tables: int = 6) -> list[str]:
        """Converts HTML <table> tags into clean, structured Markdown tables."""
        tables = []
        for table in soup.find_all("table")[:max_tables]:
            rows = table.find_all("tr")
            if not rows or len(rows) < 2:
                continue
            table_lines = []
            max_cols = 0
            for r_idx, row in enumerate(rows[:35]):
                cells = row.find_all(["th", "td"])
                if not cells:
                    continue
                cols = [re.sub(r"\s+", " ", c.get_text(strip=True)).replace("|", "/") for c in cells]
                if cols:
                    max_cols = max(max_cols, len(cols))
                    table_lines.append("| " + " | ".join(cols) + " |")
                    if r_idx == 0:
                        table_lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
            if table_lines and max_cols > 1:
                tables.append("\n".join(table_lines))
        return tables

    @staticmethod
    def extract_structured_json_ld(soup: BeautifulSoup) -> list[str]:
        """Extracts Schema.org JSON-LD structured data (NewsArticle, Product, Organization, etc.)."""
        facts = []
        for tag in soup.find_all("script", type="application/ld+json"):
            if not tag.string:
                continue
            try:
                data = json.loads(tag.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    schema_type = item.get("@type", "Schema")
                    headline = item.get("headline") or item.get("name")
                    desc = item.get("description")
                    date = item.get("datePublished") or item.get("uploadDate") or item.get("dateModified")
                    author = item.get("author")
                    if isinstance(author, dict):
                        author = author.get("name")
                    elif isinstance(author, list) and author:
                        author = author[0].get("name") if isinstance(author[0], dict) else str(author[0])

                    parts = []
                    if headline:
                        parts.append(f"Title/Name: {headline}")
                    if date:
                        parts.append(f"Date: {date}")
                    if author:
                        parts.append(f"Author: {author}")
                    if desc:
                        parts.append(f"Description: {str(desc)[:200]}")
                    if parts:
                        facts.append(f"[{schema_type}] " + " | ".join(parts))
            except Exception:
                pass
        return facts[:5]

    @classmethod
    def extract_content(
        cls, html_content: str, url: str = "", max_characters: int = 15000
    ) -> tuple[str, str, Optional[str]]:
        if not html_content or len(html_content.strip()) < 50:
            return "", "", "Empty HTML response."

        soup = BeautifulSoup(html_content, "html.parser")

        # 1. Page Title
        title = ""
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            title = title_tag.get_text(strip=True)

        # 2. Meta description & OpenGraph
        meta_desc = ""
        desc_tag = (
            soup.find("meta", attrs={"name": "description"})
            or soup.find("meta", attrs={"property": "og:description"})
            or soup.find("meta", attrs={"name": "twitter:description"})
        )
        if desc_tag and desc_tag.get("content"):
            meta_desc = desc_tag.get("content").strip()

        # 3. Structured Data
        json_ld_facts = cls.extract_structured_json_ld(soup)

        # 4. Formatted Markdown Tables
        markdown_tables = cls.extract_tables_as_markdown(soup)

        # 5. Core Editorial Body (Trafilatura preferred)
        body_text = ""
        try:
            traf = trafilatura.extract(
                html_content,
                include_tables=True,
                include_links=False,
                include_images=False,
                output_format="txt",
            )
            if traf and len(traf.strip()) >= 80:
                body_text = traf.strip()
        except Exception:
            pass

        # 6. Fallback: BeautifulSoup Clean Parser if Trafilatura missed content
        if not body_text or len(body_text) < 80:
            for el in soup(["script", "style", "noscript", "svg", "header", "footer", "nav", "aside", "form"]):
                el.decompose()

            main_el = (
                soup.find("main")
                or soup.find("article")
                or soup.find("div", id=re.compile(r"content|main|article|body", re.I))
                or soup.body
            )
            if main_el:
                lines = []
                for p in main_el.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
                    text = p.get_text(strip=True)
                    if text and len(text) > 10:
                        if p.name.startswith("h"):
                            lines.append(f"\n### {text}\n")
                        elif p.name == "li":
                            lines.append(f"- {text}")
                        else:
                            lines.append(text)
                body_text = "\n\n".join(lines).strip()

        # 7. Assemble Complete Universal Representation
        sections = []
        if title:
            sections.append(f"# {title}\n")
        if meta_desc:
            sections.append(f"**Summary / Abstract:** {meta_desc}\n")
        if json_ld_facts:
            sections.append("### Structured Metadata & Schema Facts:\n" + "\n".join(f"- {f}" for f in json_ld_facts) + "\n")
        if markdown_tables:
            sections.append("### Structured Data Tables:\n" + "\n\n".join(markdown_tables) + "\n")
        if body_text:
            sections.append("### Page Content:\n" + body_text)

        full_content = "\n\n".join(sections).strip()
        if len(full_content) < 50:
            return title, "", "Content too brief or page rendered empty."

        return title, full_content[:max_characters], None


class ResilientFetcher:
    def __init__(
        self,
        timeout_seconds: float = settings.fetch_timeout_seconds,
        max_retries: int = settings.max_retries,
        base_delay: float = settings.retry_base_delay,
        max_delay: float = settings.retry_max_delay,
        max_concurrency: int = settings.max_concurrent_fetches,
        max_per_domain_concurrency: int = settings.max_per_domain_concurrency,
    ):
        self.timeout = timeout_seconds
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_concurrency = max_concurrency
        self.max_per_domain_concurrency = max_per_domain_concurrency
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
        self._domain_semaphores: dict[str, asyncio.Semaphore] = {}

    def _get_domain_semaphore(self, domain: str) -> asyncio.Semaphore:
        """Limits concurrent requests to the same domain to prevent anti-bot tripping."""
        if domain not in self._domain_semaphores:
            self._domain_semaphores[domain] = asyncio.Semaphore(self.max_per_domain_concurrency)
        return self._domain_semaphores[domain]

    def _is_meaningful_content(self, text: str) -> tuple[bool, Optional[str]]:
        """
        Validates whether extracted text is substantive evidence rather than
        a disguised error page, captcha, cookie banner, or empty hydration shell.
        HTTP 200 alone must NOT mean success.
        """
        cleaned = text.strip()
        if len(cleaned) < settings.min_extracted_characters:
            return False, f"Content too brief ({len(cleaned)} chars < {settings.min_extracted_characters} min threshold)."

        lower = cleaned.lower()
        bot_phrases = [
            "please enable javascript",
            "verify you are a human",
            "access denied",
            "cloudflare ray id",
            "incident id",
            "403 forbidden",
            "404 not found",
            "page not found",
            "enable cookies",
            "checking your browser",
        ]
        if len(cleaned) < 500:
            for phrase in bot_phrases:
                if phrase in lower:
                    return False, f"Content contains disguised block or error banner: '{phrase}'."

        return True, None

    async def fetch_page(self, url: str) -> FetchResult:
        """
        Fetches a single URL with exponential backoff and jitter for temporary errors.
        Never retries 401, 403, 404, 410.
        Limits per-domain concurrency.
        """
        parsed_url = urllib.parse.urlparse(url)
        domain = parsed_url.netloc.lower() or "unknown_domain"
        domain_semaphore = self._get_domain_semaphore(domain)
        retry_logs: list[RetryAttemptLog] = []

        async with domain_semaphore:
            start_time = asyncio.get_event_loop().time()
            start_iso = datetime.now().isoformat()

            for attempt in range(self.max_retries + 1):
                try:
                    async with httpx.AsyncClient(
                        headers=self.headers,
                        timeout=httpx.Timeout(self.timeout, connect=self.timeout),
                        follow_redirects=True,
                        verify=False,
                    ) as client:
                        response = await client.get(url)
                        duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                        end_iso = datetime.now().isoformat()
                        status_code = response.status_code

                        # Non-retryable: 401, 403 (Authorization / Bot blocking)
                        if status_code in (401, 403):
                            msg = f"Access blocked by host with status {status_code} (Anti-bot / Cloudflare challenge)."
                            return FetchResult(
                                url=url,
                                domain=domain,
                                status="BLOCKED_403",
                                status_code=status_code,
                                duration_ms=duration_ms,
                                start_time_iso=start_iso,
                                end_time_iso=end_iso,
                                is_usable=False,
                                rejection_reason=msg,
                                error_message=msg,
                                total_retries=len(retry_logs),
                                retry_attempts=retry_logs,
                            )

                        # Non-retryable: 404, 410 (Missing resources)
                        if status_code in (404, 410):
                            msg = f"Resource not found on server (status {status_code})."
                            return FetchResult(
                                url=url,
                                domain=domain,
                                status="NOT_FOUND_404",
                                status_code=status_code,
                                duration_ms=duration_ms,
                                start_time_iso=start_iso,
                                end_time_iso=end_iso,
                                is_usable=False,
                                rejection_reason=msg,
                                error_message=msg,
                                total_retries=len(retry_logs),
                                retry_attempts=retry_logs,
                            )

                        # Retryable status codes: 429, 408, 502, 503, 504
                        if status_code in RETRYABLE_STATUS_CODES:
                            retry_hdr = response.headers.get("retry-after")
                            calc_delay, wait_time, parsed_hdr = calculate_backoff_delay(
                                attempt=attempt,
                                base_delay=self.base_delay,
                                max_delay=self.max_delay,
                                retry_after_header=retry_hdr,
                            )

                            if attempt < self.max_retries:
                                retry_logs.append(
                                    RetryAttemptLog(
                                        url=url,
                                        domain=domain,
                                        attempt_number=attempt + 1,
                                        status_code=status_code,
                                        error_type=f"HTTP_{status_code}",
                                        calculated_delay=calc_delay,
                                        retry_after_header=retry_hdr,
                                        actual_wait_time=wait_time,
                                        final_result="RETRYING",
                                    )
                                )
                                await asyncio.sleep(wait_time)
                                continue
                            else:
                                # Max retries exhausted
                                retry_logs.append(
                                    RetryAttemptLog(
                                        url=url,
                                        domain=domain,
                                        attempt_number=attempt + 1,
                                        status_code=status_code,
                                        error_type=f"HTTP_{status_code}",
                                        calculated_delay=calc_delay,
                                        retry_after_header=retry_hdr,
                                        actual_wait_time=0.0,
                                        final_result="MAX_RETRIES_EXCEEDED",
                                    )
                                )
                                status_label = "RATE_LIMITED_429" if status_code == 429 else "SERVER_ERROR"
                                msg = f"Host returned HTTP {status_code} and exceeded max retries ({self.max_retries})."
                                return FetchResult(
                                    url=url,
                                    domain=domain,
                                    status=status_label,
                                    status_code=status_code,
                                    duration_ms=duration_ms,
                                    start_time_iso=start_iso,
                                    end_time_iso=end_iso,
                                    is_usable=False,
                                    rejection_reason=msg,
                                    error_message=msg,
                                    total_retries=len(retry_logs),
                                    retry_attempts=retry_logs,
                                )

                        # Non-retryable 5xx (e.g. 500) if not in retryable codes
                        if status_code >= 500:
                            msg = f"Upstream server error (status {status_code})."
                            return FetchResult(
                                url=url,
                                domain=domain,
                                status="SERVER_ERROR",
                                status_code=status_code,
                                duration_ms=duration_ms,
                                start_time_iso=start_iso,
                                end_time_iso=end_iso,
                                is_usable=False,
                                rejection_reason=msg,
                                error_message=msg,
                                total_retries=len(retry_logs),
                                retry_attempts=retry_logs,
                            )

                        # Other unexpected non-200 client statuses
                        if status_code != 200:
                            msg = f"Unexpected HTTP status {status_code}."
                            return FetchResult(
                                url=url,
                                domain=domain,
                                status="ERROR",
                                status_code=status_code,
                                duration_ms=duration_ms,
                                start_time_iso=start_iso,
                                end_time_iso=end_iso,
                                is_usable=False,
                                rejection_reason=msg,
                                error_message=msg,
                                total_retries=len(retry_logs),
                                retry_attempts=retry_logs,
                            )

                        # HTTP 200 universal content extraction
                        html_content = response.text
                        title, extracted_text, extract_err = UniversalContentExtractor.extract_content(
                            html_content=html_content,
                            url=url,
                            max_characters=settings.max_extracted_characters_per_page,
                        )

                        if not extracted_text or len(extracted_text.strip()) < 50:
                            msg = extract_err or "Page rendered empty or requires JavaScript hydration (SPA)."
                            return FetchResult(
                                url=url,
                                domain=domain,
                                status="EMPTY_CONTENT",
                                status_code=status_code,
                                duration_ms=duration_ms,
                                start_time_iso=start_iso,
                                end_time_iso=end_iso,
                                is_usable=False,
                                rejection_reason=msg,
                                error_message=msg,
                                total_retries=len(retry_logs),
                                retry_attempts=retry_logs,
                            )

                        cleaned_text = extracted_text.strip()[: settings.max_extracted_characters_per_page]
                        is_meaningful, reject_reason = self._is_meaningful_content(cleaned_text)

                        if not is_meaningful:
                            return FetchResult(
                                url=url,
                                domain=domain,
                                status="EMPTY_CONTENT",
                                status_code=status_code,
                                title=title,
                                extracted_text=cleaned_text,
                                character_count=len(cleaned_text),
                                duration_ms=duration_ms,
                                start_time_iso=start_iso,
                                end_time_iso=end_iso,
                                is_usable=False,
                                rejection_reason=reject_reason,
                                error_message=reject_reason,
                                total_retries=len(retry_logs),
                                retry_attempts=retry_logs,
                            )

                        # Valid, usable source evidence
                        return FetchResult(
                            url=url,
                            domain=domain,
                            status="SUCCESS",
                            status_code=status_code,
                            title=title,
                            extracted_text=cleaned_text,
                            character_count=len(cleaned_text),
                            duration_ms=duration_ms,
                            start_time_iso=start_iso,
                            end_time_iso=end_iso,
                            is_usable=True,
                            total_retries=len(retry_logs),
                            retry_attempts=retry_logs,
                        )

                except httpx.TimeoutException:
                    duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                    calc_delay, wait_time, _ = calculate_backoff_delay(
                        attempt=attempt,
                        base_delay=self.base_delay,
                        max_delay=self.max_delay,
                    )
                    if attempt < self.max_retries:
                        retry_logs.append(
                            RetryAttemptLog(
                                url=url,
                                domain=domain,
                                attempt_number=attempt + 1,
                                status_code=None,
                                error_type="TIMEOUT",
                                calculated_delay=calc_delay,
                                retry_after_header=None,
                                actual_wait_time=wait_time,
                                final_result="RETRYING",
                            )
                        )
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        retry_logs.append(
                            RetryAttemptLog(
                                url=url,
                                domain=domain,
                                attempt_number=attempt + 1,
                                status_code=None,
                                error_type="TIMEOUT",
                                calculated_delay=calc_delay,
                                retry_after_header=None,
                                actual_wait_time=0.0,
                                final_result="MAX_RETRIES_EXCEEDED",
                            )
                        )
                        end_iso = datetime.now().isoformat()
                        msg = f"Connection timed out after {self.timeout}s (max retries exhausted)."
                        return FetchResult(
                            url=url,
                            domain=domain,
                            status="TIMEOUT",
                            duration_ms=duration_ms,
                            start_time_iso=start_iso,
                            end_time_iso=end_iso,
                            is_usable=False,
                            rejection_reason=msg,
                            error_message=msg,
                            total_retries=len(retry_logs),
                            retry_attempts=retry_logs,
                        )

                except Exception as e:
                    duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                    calc_delay, wait_time, _ = calculate_backoff_delay(
                        attempt=attempt,
                        base_delay=self.base_delay,
                        max_delay=self.max_delay,
                    )
                    if attempt < self.max_retries:
                        retry_logs.append(
                            RetryAttemptLog(
                                url=url,
                                domain=domain,
                                attempt_number=attempt + 1,
                                status_code=None,
                                error_type=type(e).__name__,
                                calculated_delay=calc_delay,
                                retry_after_header=None,
                                actual_wait_time=wait_time,
                                final_result="RETRYING",
                            )
                        )
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        retry_logs.append(
                            RetryAttemptLog(
                                url=url,
                                domain=domain,
                                attempt_number=attempt + 1,
                                status_code=None,
                                error_type=type(e).__name__,
                                calculated_delay=calc_delay,
                                retry_after_header=None,
                                actual_wait_time=0.0,
                                final_result="MAX_RETRIES_EXCEEDED",
                            )
                        )
                        end_iso = datetime.now().isoformat()
                        msg = f"Fetch failed with network error: {str(e)} (max retries exhausted)."
                        return FetchResult(
                            url=url,
                            domain=domain,
                            status="ERROR",
                            duration_ms=duration_ms,
                            start_time_iso=start_iso,
                            end_time_iso=end_iso,
                            is_usable=False,
                            rejection_reason=msg,
                            error_message=msg,
                            total_retries=len(retry_logs),
                            retry_attempts=retry_logs,
                        )

    async def fetch_multiple(self, urls: list[str], max_concurrency: Optional[int] = None) -> list[FetchResult]:
        """Fetches multiple URLs concurrently with a concurrency semaphore."""
        concurrency = max_concurrency or self.max_concurrency
        semaphore = asyncio.Semaphore(concurrency)

        async def _bounded_fetch(u: str) -> FetchResult:
            async with semaphore:
                return await self.fetch_page(u)

        return await asyncio.gather(*[_bounded_fetch(u) for u in urls])

    async def fetch_with_adaptive_stopping(
        self,
        candidate_urls: list[str],
        min_usable: Optional[int] = None,
        max_concurrency: Optional[int] = None,
    ) -> AdaptiveFetchReport:
        """
        Adaptive Batch Fetching Pipeline:
        1. Takes multiple candidate URLs (up to MAX_CANDIDATES).
        2. Dispatches fetches concurrently in bounded batches.
        3. Evaluates evidence usability.
        4. If MIN_USABLE_SOURCES is reached, STOPS early to save time and tokens.
        5. If not reached, fetches additional candidates until threshold or list exhausted.
        6. A failed URL (403, 404, timeout, 429) NEVER stops the research.
        7. Records full retry telemetry for backoff visibility.
        """
        target_usable = min_usable or settings.min_usable_sources
        concurrency = max_concurrency or self.max_concurrency

        all_results: list[FetchResult] = []
        usable_results: list[FetchResult] = []
        all_retry_logs: list[RetryAttemptLog] = []
        total_retries = 0
        blocked_count = 0
        failed_count = 0

        start_overall = asyncio.get_event_loop().time()
        pending_urls = list(candidate_urls)
        semaphore = asyncio.Semaphore(concurrency)

        async def _bounded_fetch(u: str) -> FetchResult:
            async with semaphore:
                return await self.fetch_page(u)

        while pending_urls and len(usable_results) < target_usable:
            needed = target_usable - len(usable_results)
            batch_size = min(len(pending_urls), max(needed, concurrency))
            current_batch = pending_urls[:batch_size]
            pending_urls = pending_urls[batch_size:]

            batch_results = await asyncio.gather(*[_bounded_fetch(u) for u in current_batch])

            for res in batch_results:
                all_results.append(res)
                total_retries += res.total_retries
                all_retry_logs.extend(res.retry_attempts)

                if res.is_usable:
                    usable_results.append(res)
                elif res.status == "BLOCKED_403":
                    blocked_count += 1
                else:
                    failed_count += 1

            # Adaptive stopping check: if threshold met, break early
            if len(usable_results) >= target_usable:
                break

        total_time_ms = (asyncio.get_event_loop().time() - start_overall) * 1000

        return AdaptiveFetchReport(
            candidates_evaluated=len(all_results),
            successful_usable_count=len(usable_results),
            blocked_count=blocked_count,
            failed_count=failed_count,
            total_fetch_time_ms=round(total_time_ms, 2),
            threshold_reached=len(usable_results) >= target_usable,
            total_retries_performed=total_retries,
            retry_logs=all_retry_logs,
            usable_results=usable_results,
            all_results=all_results,
        )
