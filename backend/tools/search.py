from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote_plus

from ddgs import DDGS
import httpx
from bs4 import BeautifulSoup


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _run_ddgs_search(query: str, max_results: int) -> list[dict[str, Any]]:
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))


async def _html_fallback_search(query: str, max_results: int) -> list[dict[str, Any]]:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            response = await client.get(url, headers=_HEADERS)
            if response.status_code != 200 or not response.text:
                return []
        soup = BeautifulSoup(response.text, "html.parser")
        parsed: list[dict[str, Any]] = []
        for node in soup.select(".result"):
            if len(parsed) >= max_results:
                break
            link = node.select_one(".result__a")
            if link is None:
                continue
            title = link.get_text(" ", strip=True)
            href = link.get("href")
            snippet_node = node.select_one(".result__snippet")
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            if not title or not href:
                continue
            parsed.append({"title": title, "url": href, "snippet": snippet})
        return parsed
    except Exception:
        return []


async def search(query: str, max_results: int = 8) -> list[dict[str, Any]]:
    if not query or max_results <= 0:
        return []

    try:
        loop = asyncio.get_running_loop()
        raw_results = await loop.run_in_executor(
            None,
            lambda: _run_ddgs_search(query, max_results),
        )
        if not raw_results:
            await asyncio.sleep(2)
            raw_results = await loop.run_in_executor(
                None,
                lambda: _run_ddgs_search(query, max_results),
            )

        parsed: list[dict[str, Any]] = []
        for item in raw_results:
            title = item.get("title")
            url = item.get("href")
            snippet = item.get("body", "")
            if not title or not url:
                continue
            parsed.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                }
            )
        if not parsed:
            parsed = await _html_fallback_search(query, max_results)
        if not parsed:
            print(f"Warning: web_search returned empty results after retry for query: {query}")
        return parsed
    except Exception:
        return []
