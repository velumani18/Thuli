"""
Web Search Tool supporting Tavily, Bing Web Search with base64 decoding,
DuckDuckGo Lite, Wikipedia API, and DDGS fallback.
"""

import asyncio
import base64
import re
import urllib.parse
from typing import Optional
from pydantic import BaseModel
import httpx
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

from app.core.config import settings


class SearchResultItem(BaseModel):
    title: str
    url: str
    snippet: str
    raw_content: Optional[str] = None


class SearchResult(BaseModel):
    query: str
    engine: str
    items: list[SearchResultItem]
    duration_ms: float = 0.0
    error: Optional[str] = None


class SearchEngine:
    def __init__(self, tavily_api_key: Optional[str] = None):
        self.tavily_api_key = tavily_api_key or settings.tavily_api_key
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    @staticmethod
    def _decode_bing_url(u: str) -> str:
        """Decodes base64 destination URL embedded in Bing tracking links."""
        if "bing.com/ck/a" in u:
            try:
                parsed = urllib.parse.urlparse(u)
                q = urllib.parse.parse_qs(parsed.query)
                u_param = q.get("u", [""])[0]
                if u_param.startswith("a1"):
                    b64_str = u_param[2:]
                    padded = b64_str + "=" * (-len(b64_str) % 4)
                    decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
                    if decoded.startswith("http"):
                        return decoded
            except Exception:
                pass
        return u

    @staticmethod
    def _clean_url(raw_url: str) -> str:
        """Removes tracking wrappers and query parameters."""
        u = raw_url.strip()
        if "duckduckgo.com/l/?uddg=" in u:
            match = re.search(r"uddg=([^&]+)", u)
            if match:
                u = urllib.parse.unquote(match.group(1))
        try:
            parsed = urllib.parse.urlparse(u)
            q_params = urllib.parse.parse_qsl(parsed.query)
            clean_params = [(k, v) for k, v in q_params if not k.startswith("utm_") and k not in ("ref", "fbclid")]
            new_query = urllib.parse.urlencode(clean_params)
            return urllib.parse.urlunparse(parsed._replace(query=new_query))
        except Exception:
            return u

    async def _search_ddg_html(self, query: str, max_results: int) -> list[SearchResultItem]:
        """Scrapes DuckDuckGo HTML search results directly (fast, no JS, reliable)."""
        async with httpx.AsyncClient(headers=self.headers, timeout=12.0, follow_redirects=True) as client:
            resp = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                items = []
                for result in soup.find_all("div", class_="result"):
                    h2 = result.find("h2", class_="result__title")
                    title_a = h2.find("a") if h2 else None
                    snippet_elem = result.find("a", class_="result__snippet")

                    raw_url = ""
                    if title_a and title_a.get("href"):
                        raw_url = title_a["href"]
                    elif snippet_elem and snippet_elem.get("href"):
                        raw_url = snippet_elem["href"]

                    clean_url = self._clean_url(raw_url)
                    if clean_url.startswith("http") and "duckduckgo.com" not in clean_url:
                        title = title_a.get_text(strip=True) if title_a else ""
                        snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""
                        items.append(SearchResultItem(title=title or clean_url, url=clean_url, snippet=snippet or title))
                        if len(items) >= max_results:
                            break
                return items
        return []

    async def _search_bing(self, query: str, max_results: int) -> list[SearchResultItem]:
        """Scrapes Bing search results and decodes target URLs."""
        async with httpx.AsyncClient(headers=self.headers, timeout=12.0, follow_redirects=True) as client:
            resp = await client.get("https://www.bing.com/search", params={"q": query})
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                items = []
                for li in soup.find_all("li", class_="b_algo"):
                    h2 = li.find("h2")
                    if not h2:
                        continue
                    a = h2.find("a")
                    if not a or not a.get("href"):
                        continue
                    raw_url = a["href"]
                    clean_url = self._clean_url(self._decode_bing_url(raw_url))
                    if not clean_url.startswith("http") or "bing.com" in clean_url:
                        continue
                    p = li.find("p")
                    snippet = p.get_text(strip=True) if p else ""
                    title = a.get_text(strip=True)
                    items.append(SearchResultItem(title=title, url=clean_url, snippet=snippet or title))
                    if len(items) >= max_results:
                        break
                return items
        return []

    async def _search_ddg_lite(self, query: str, max_results: int) -> list[SearchResultItem]:
        """Scrapes DuckDuckGo Lite search results."""
        async with httpx.AsyncClient(headers=self.headers, timeout=10.0, follow_redirects=True) as client:
            resp = await client.post("https://lite.duckduckgo.com/lite/", data={"q": query, "b": ""})
            if resp.status_code == 200 and "result-link" in resp.text:
                soup = BeautifulSoup(resp.text, "html.parser")
                items = []
                for a in soup.find_all("a", class_="result-link"):
                    href = a.get("href", "").strip()
                    title = a.get_text(strip=True)
                    clean_url = self._clean_url(href)
                    if clean_url.startswith("http") and "duckduckgo.com" not in clean_url:
                        snippet = ""
                        parent_tr = a.find_parent("tr")
                        if parent_tr:
                            next_tr = parent_tr.find_next_sibling("tr")
                            if next_tr:
                                snippet_td = next_tr.find("td", class_="result-snippet")
                                if snippet_td:
                                    snippet = snippet_td.get_text(strip=True)
                        items.append(SearchResultItem(title=title, url=clean_url, snippet=snippet or title))
                        if len(items) >= max_results:
                            break
                return items
        return []

    async def _search_wikipedia(self, query: str, max_results: int) -> list[SearchResultItem]:
        """Uses Wikipedia OpenSearch API for background entity discovery."""
        clean_q = re.sub(r"^(what is|who is|who was|how many|when was|tell me about)\s+", "", query, flags=re.I).strip()
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={"action": "opensearch", "search": clean_q, "limit": max_results, "format": "json"},
                    headers={"User-Agent": "facTrack-Agent/1.0"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    titles = data[1] if len(data) > 1 else []
                    snippets = data[2] if len(data) > 2 else []
                    urls = data[3] if len(data) > 3 else []
                    items = []
                    for t, s, u in zip(titles, snippets, urls):
                        if u and u.startswith("http"):
                            items.append(SearchResultItem(title=t, url=u, snippet=s or t))
                    return items
        except Exception:
            pass
        return []

    async def search(self, query: str, max_results: int = settings.max_search_results) -> SearchResult:
        start_time = asyncio.get_event_loop().time()

        # 1. Tavily API if key provided
        if self.tavily_api_key:
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.post(
                        "https://api.tavily.com/search",
                        json={
                            "api_key": self.tavily_api_key,
                            "query": query,
                            "search_depth": "basic",
                            "include_raw_content": True,
                            "max_results": max_results,
                        },
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        items = [
                            SearchResultItem(
                                title=r.get("title", ""),
                                url=self._clean_url(r.get("url", "")),
                                snippet=r.get("content", ""),
                                raw_content=r.get("raw_content"),
                            )
                            for r in data.get("results", [])
                        ]
                        if items:
                            duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                            return SearchResult(query=query, engine="tavily", items=items, duration_ms=duration_ms)
            except Exception:
                pass

        # 2. DuckDuckGo HTML (Fast, reliable, direct unredirected links)
        try:
            items = await self._search_ddg_html(query, max_results)
            if items:
                duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                return SearchResult(query=query, engine="duckduckgo_html", items=items, duration_ms=duration_ms)
        except Exception:
            pass

        # 3. Bing Web Search (Fast, robust, direct primary sources)
        try:
            items = await self._search_bing(query, max_results)
            if items:
                duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                return SearchResult(query=query, engine="bing", items=items, duration_ms=duration_ms)
        except Exception:
            pass

        # 4. DuckDuckGo Lite
        try:
            items = await self._search_ddg_lite(query, max_results)
            if items:
                duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                return SearchResult(query=query, engine="duckduckgo_lite", items=items, duration_ms=duration_ms)
        except Exception:
            pass

        # 5. Wikipedia OpenSearch API fallback
        try:
            wiki_items = await self._search_wikipedia(query, max_results)
            if wiki_items:
                duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                return SearchResult(query=query, engine="wikipedia", items=wiki_items, duration_ms=duration_ms)
        except Exception:
            pass

        # 6. DDGS fallback
        try:
            loop = asyncio.get_event_loop()
            def _sync():
                with DDGS(timeout=5) as ddgs:
                    return list(ddgs.text(query, max_results=max_results))
            raw = await loop.run_in_executor(None, _sync)
            items = [
                SearchResultItem(title=r.get("title", ""), url=self._clean_url(r.get("href", "")), snippet=r.get("body", ""))
                for r in raw if r.get("href")
            ]
            if items:
                duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                return SearchResult(query=query, engine="duckduckgo_ddgs", items=items, duration_ms=duration_ms)
        except Exception:
            pass

        duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
        return SearchResult(query=query, engine="none", items=[], duration_ms=duration_ms, error="All search providers exhausted.")

