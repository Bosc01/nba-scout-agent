"""Web search utility used by the scouting agent.

DuckDuckGo HTML search is used because it requires no API key, has broad
coverage across public basketball sources, and is free to use for lightweight
agent research tasks.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

_RATE_LIMIT_SECONDS = 1.0
_SEARCH_TIMEOUT_SECONDS = 10.0
_rate_limit_lock = asyncio.Lock()
_last_call_at = 0.0


async def _respect_rate_limit() -> None:
    global _last_call_at
    async with _rate_limit_lock:
        now = time.monotonic()
        elapsed = now - _last_call_at
        if elapsed < _RATE_LIMIT_SECONDS:
            await asyncio.sleep(_RATE_LIMIT_SECONDS - elapsed)
        _last_call_at = time.monotonic()


async def search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Run a DuckDuckGo HTML search and return normalized search results.

    Args:
        query: Search query.
        max_results: Maximum number of results to return.

    Returns:
        A list of dictionaries with keys: title, url, snippet.
        Returns an empty list on any error.
    """
    if not query or max_results <= 0:
        return []

    await _respect_rate_limit()

    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        )
    }

    try:
        async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            if response.status_code != 200 or not response.text:
                return []

        soup = BeautifulSoup(response.text, "html.parser")
        results: list[dict[str, Any]] = []

        for node in soup.select(".result"):
            if len(results) >= max_results:
                break

            link = node.select_one(".result__a")
            if link is None:
                continue

            title = link.get_text(" ", strip=True) or None
            raw_url = link.get("href")
            snippet_node = node.select_one(".result__snippet")
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""

            if not title or not raw_url:
                continue

            results.append(
                {
                    "title": title,
                    "url": raw_url,
                    "snippet": snippet,
                }
            )

        return results
    except (httpx.HTTPError, asyncio.TimeoutError, Exception):
        return []
