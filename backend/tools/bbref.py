from __future__ import annotations

import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from tools.search import search

_TIMEOUT_SECONDS = 10.0


def _extract_labeled_value(meta: BeautifulSoup, label: str) -> str | None:
    strong = meta.find("strong", string=re.compile(rf"^{re.escape(label)}", re.IGNORECASE))
    if strong is None:
        return None
    parent = strong.parent
    if parent is None:
        return None
    text = parent.get_text(" ", strip=True)
    value = re.sub(rf"^{re.escape(label)}\s*", "", text, flags=re.IGNORECASE).strip()
    return value or None


def _to_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _extract_recent_per_game_stats(soup: BeautifulSoup) -> dict[str, Any]:
    table = soup.select_one("table#per_game")
    if table is None:
        return {
            "pts": None,
            "reb": None,
            "ast": None,
            "fg_pct": None,
            "three_pct": None,
            "ft_pct": None,
            "games": None,
            "minutes": None,
        }

    rows = table.select("tbody tr")
    candidate = None
    for row in rows:
        if "thead" in row.get("class", []):
            continue
        season = row.select_one("th[data-stat='season']")
        if season is None:
            continue
        season_text = season.get_text(strip=True).lower()
        if season_text in {"career", ""}:
            continue
        candidate = row

    if candidate is None:
        return {
            "pts": None,
            "reb": None,
            "ast": None,
            "fg_pct": None,
            "three_pct": None,
            "ft_pct": None,
            "games": None,
            "minutes": None,
        }

    def get_stat(data_stat: str) -> str | None:
        cell = candidate.select_one(f"td[data-stat='{data_stat}']")
        if cell is None:
            return None
        return cell.get_text(strip=True) or None

    return {
        "pts": _to_float(get_stat("pts_per_g")),
        "reb": _to_float(get_stat("trb_per_g")),
        "ast": _to_float(get_stat("ast_per_g")),
        "fg_pct": _to_float(get_stat("fg_pct")),
        "three_pct": _to_float(get_stat("fg3_pct")),
        "ft_pct": _to_float(get_stat("ft_pct")),
        "games": _to_int(get_stat("g")),
        "minutes": _to_float(get_stat("mp_per_g")),
    }


async def get_player_stats(player_name: str) -> dict[str, Any]:
    """Scrape Basketball Reference profile + most recent per-game stats."""
    if not player_name.strip():
        return {"confidence": 0.0}

    try:
        results = await search(f"site:basketball-reference.com {player_name} basketball reference", max_results=8)
        player_url = None
        for result in results:
            url = result.get("url", "")
            if re.search(r"basketball-reference\.com/players/[a-z]/.+\.html", url):
                player_url = url
                break

        if not player_url:
            return {"confidence": 0.0}

        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = await client.get(player_url)
            if response.status_code != 200 or not response.text:
                return {"confidence": 0.0}

        soup = BeautifulSoup(response.text, "html.parser")
        meta = soup.select_one("div#meta")
        if meta is None:
            return {"confidence": 0.0}

        name_node = meta.select_one("h1 span")
        full_name = name_node.get_text(" ", strip=True) if name_node else None

        pos = _extract_labeled_value(meta, "Position:")
        height = _extract_labeled_value(meta, "Shoots:")  # fallback parsing follows
        if height and ("Shoots:" in height or "shoots" in height.lower()):
            height = None

        # Height/weight often appear together in the vitals paragraph.
        vitals_text = meta.get_text(" ", strip=True)
        height_match = re.search(r"(\d-\d{1,2})\s*,?\s*(\d{2,3}lb)?", vitals_text)
        parsed_height = height_match.group(1) if height_match else None
        parsed_weight = None
        if height_match and height_match.group(2):
            parsed_weight = height_match.group(2)
        else:
            weight_match = re.search(r"(\d{2,3}lb)", vitals_text)
            parsed_weight = weight_match.group(1) if weight_match else None

        birth_node = meta.select_one("span#necro-birth")
        birth_date = birth_node.get("data-birth") if birth_node else None

        school = _extract_labeled_value(meta, "College:")
        team = _extract_labeled_value(meta, "Team:")
        school_or_team = school or team

        per_game = _extract_recent_per_game_stats(soup)

        data: dict[str, Any] = {
            "full_name": full_name,
            "position": pos,
            "height": parsed_height,
            "weight": parsed_weight,
            "birth_date": birth_date,
            "school_or_team": school_or_team,
            "per_game": per_game,
            "source_url": player_url,
        }

        fields_to_score = [
            full_name,
            pos,
            parsed_height,
            parsed_weight,
            birth_date,
            school_or_team,
            per_game.get("pts"),
            per_game.get("reb"),
            per_game.get("ast"),
            per_game.get("fg_pct"),
            per_game.get("three_pct"),
            per_game.get("ft_pct"),
            per_game.get("games"),
            per_game.get("minutes"),
        ]
        found_count = sum(value is not None for value in fields_to_score)
        data["confidence"] = round(found_count / len(fields_to_score), 3)

        return data
    except Exception:
        return {"confidence": 0.0}
