from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from tools.search import search


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


def _empty_result() -> dict:
    return {
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
        "level": "fiba",
        "confidence": 0.0,
    }


async def get_fiba_profile(player_name: str) -> dict:
    result = _empty_result()
    if not player_name.strip():
        return result

    try:
        results = await search(f"{player_name} FIBA basketball profile stats", max_results=8)
        profile_url = None
        for item in results:
            url = str(item.get("url", ""))
            if "fiba" in url.lower():
                profile_url = url
                break
        if not profile_url:
            return result

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            response = await client.get(profile_url, headers=headers)
            if response.status_code != 200 or not response.text:
                return result

        soup = BeautifulSoup(response.text, "html.parser")
        page_text = soup.get_text(" ", strip=True)
        name_node = soup.find("h1") or soup.find("title")
        name = name_node.get_text(" ", strip=True) if name_node else player_name

        pos_match = re.search(r"\bPosition\b[:\s\-]*([A-Za-z\-\s/]+)", page_text)
        height_match = re.search(r"(\d-\d{1,2})", page_text)
        weight_match = re.search(r"(\d{2,3}\s?(?:kg|lb|lbs))", page_text, flags=re.IGNORECASE)
        team_match = re.search(r"\bTeam\b[:\s\-]*([A-Za-z0-9\.\-\s'&]+)", page_text)
        pts_match = re.search(r"\bPTS\b\s*([0-9]+(?:\.[0-9]+)?)", page_text)
        reb_match = re.search(r"\bREB\b\s*([0-9]+(?:\.[0-9]+)?)", page_text)
        ast_match = re.search(r"\bAST\b\s*([0-9]+(?:\.[0-9]+)?)", page_text)
        games_match = re.search(r"\bGP\b\s*([0-9]+)", page_text) or re.search(r"\bGames\b\s*([0-9]+)", page_text)

        result.update(
            {
                "player_name": name,
                "position": pos_match.group(1).strip() if pos_match else None,
                "height": height_match.group(1) if height_match else None,
                "weight": weight_match.group(1) if weight_match else None,
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
            result["position"],
            result["height"],
            result["weight"],
            result["team"],
            result["pts"],
            result["reb"],
            result["ast"],
            result["games"],
        ]
        result["confidence"] = round(sum(v is not None for v in score_fields) / 13, 3)
        return result
    except Exception:
        return result
