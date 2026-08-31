from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from tools.search import search
from tools.urlguard import UnsafeURLError, is_allowed_url, safe_get

_EUROLEAGUE_DOMAINS = {"euroleague.net", "euroleaguebasketball.net"}

_HEADERS = {
    "User-Agent": "NBAScoutBot/1.0 (+https://nbascout.app)",
    "Accept-Language": "en-US,en;q=0.9",
}


def _empty_result() -> dict:
    return {
        "status": None,
        "http_status": None,
        "error": None,
        "player_name": None,
        "position": None,
        "height": None,
        "weight": None,
        "team": None,
        "pts": None,
        "reb": None,
        "ast": None,
        "fg_pct": None,
        "three_pct": None,
        "ft_pct": None,
        "games": None,
        "minutes": None,
        "source_url": None,
        "level": "euroleague",
        "confidence": 0.0,
    }


def _failure(status: str, *, http_status: int | None = None, error: str | None = None) -> dict:
    result = _empty_result()
    result["status"] = status
    result["http_status"] = http_status
    result["error"] = error
    return result


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


async def get_euroleague_stats(player_name: str) -> dict:
    if not player_name.strip():
        return _failure("not_found", error="empty player name")

    try:
        results = await search(f"{player_name} euroleague stats", max_results=8)
        player_url = None
        for item in results:
            url = str(item.get("url", ""))
            # Hostname allowlist, not substring: "euroleague.net" in url passes
            # for any URL that merely mentions the domain in its query string.
            if is_allowed_url(url, _EUROLEAGUE_DOMAINS):
                player_url = url
                break
        if not player_url:
            return _failure("not_found", error="no euroleague.net page in search results")

        async with httpx.AsyncClient(timeout=15) as client:
            response = await safe_get(client, player_url, _EUROLEAGUE_DOMAINS, headers=_HEADERS)
            if response.status_code != 200 or not response.text:
                status = "blocked" if response.status_code in (403, 429) else "parse_failed"
                return _failure(status, http_status=response.status_code,
                                error=f"page returned HTTP {response.status_code}")

        soup = BeautifulSoup(response.text, "html.parser")
        page_text = soup.get_text(" ", strip=True)
        name = None
        name_tag = soup.find("h1") or soup.find("title")
        if name_tag:
            name = name_tag.get_text(" ", strip=True)

        team_match = re.search(r"Team\s*[:\-]\s*([A-Za-z0-9\.\-\s'&]+)", page_text)
        pts_match = re.search(r"\bPTS\b\s*([0-9]+(?:\.[0-9]+)?)", page_text)
        reb_match = re.search(r"\bREB\b\s*([0-9]+(?:\.[0-9]+)?)", page_text)
        ast_match = re.search(r"\bAST\b\s*([0-9]+(?:\.[0-9]+)?)", page_text)
        games_match = re.search(r"\bGP\b\s*([0-9]+)", page_text) or re.search(
            r"\bGames\b\s*([0-9]+)", page_text
        )

        result = _empty_result()
        result.update(
            {
                "status": "ok",
                "http_status": 200,
                "player_name": name or player_name,
                "team": team_match.group(1).strip() if team_match else None,
                "pts": _to_float(pts_match.group(1) if pts_match else None),
                "reb": _to_float(reb_match.group(1) if reb_match else None),
                "ast": _to_float(ast_match.group(1) if ast_match else None),
                "games": _to_int(games_match.group(1) if games_match else None),
                "source_url": str(response.url),
            }
        )

        score_fields = [
            result["player_name"],
            result["team"],
            result["pts"],
            result["reb"],
            result["ast"],
            result["games"],
        ]
        result["confidence"] = round(sum(v is not None for v in score_fields) / 13, 3)
        return result
    except UnsafeURLError as exc:
        return _failure("parse_failed", error=str(exc))
    except Exception as exc:
        return _failure("parse_failed", error=str(exc))
