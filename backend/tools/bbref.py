from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup


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
        "confidence": 0.0,
    }


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


def _extract_stats_and_team(soup: BeautifulSoup) -> tuple[dict, str | None]:
    table = soup.find("table", {"id": "per_game_stats"}) or soup.find("table", {"id": "per_game"})
    empty_stats = {
        "pts": None,
        "reb": None,
        "ast": None,
        "fg_pct": None,
        "three_pct": None,
        "ft_pct": None,
        "games": None,
        "minutes": None,
    }
    if table is None:
        return empty_stats, None

    candidate = None
    tbody = table.find("tbody")
    if tbody is None:
        return empty_stats, None

    for row in tbody.find_all("tr"):
        classes = row.get("class", [])
        if "thead" in classes:
            continue
        row_text = row.get_text(" ", strip=True).lower()
        if "did not play" in row_text:
            continue
        season_cell = (
            row.find("th", {"data-stat": "year_id"})
            or row.find("th", {"data-stat": "season"})
            or row.find(["th", "td"], {"data-stat": "year_id"})
        )
        if season_cell is None:
            continue
        candidate = row

    if candidate is None:
        return empty_stats, None

    def get_stat(stat_name: str) -> str | None:
        cell = candidate.find("td", {"data-stat": stat_name})
        if cell is None:
            return None
        text = cell.get_text(strip=True)
        return text if text else None

    team = get_stat("team_name_abbr") or get_stat("team_id")
    stats = {
        "pts": _to_float(get_stat("pts_per_g")),
        "reb": _to_float(get_stat("trb_per_g")),
        "ast": _to_float(get_stat("ast_per_g")),
        "fg_pct": _to_float(get_stat("fg_pct")),
        "three_pct": _to_float(get_stat("fg3_pct")),
        "ft_pct": _to_float(get_stat("ft_pct")),
        "games": _to_int(get_stat("games") or get_stat("g")),
        "minutes": _to_float(get_stat("mp_per_g")),
    }
    return stats, team


async def get_player_stats(player_name: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    result = _empty_result()
    if not player_name.strip():
        return result

    player_page_pattern = re.compile(r"/players/[a-z]/[a-z0-9'\-]+\.html")

    try:
        search_url = (
            "https://www.basketball-reference.com/search/search.fcgi?search="
            f"{player_name.replace(' ', '+')}"
        )
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            response = await client.get(search_url, headers=headers)
            if response.status_code != 200:
                return result

            final_url = str(response.url)
            player_url = final_url
            player_html = response.text

            if not player_page_pattern.search(final_url):
                soup_search = BeautifulSoup(response.text, "html.parser")
                found_link = None
                for a_tag in soup_search.find_all("a", href=True):
                    href = a_tag["href"]
                    if player_page_pattern.search(href):
                        found_link = urljoin("https://www.basketball-reference.com", href)
                        break
                if not found_link:
                    return result
                player_response = await client.get(found_link, headers=headers)
                if player_response.status_code != 200:
                    return result
                player_url = str(player_response.url)
                player_html = player_response.text

        soup = BeautifulSoup(player_html, "html.parser")
        name_tag = soup.find("h1", {"itemprop": "name"})
        name = name_tag.get_text(" ", strip=True) if name_tag else player_name

        meta = soup.find("div", {"id": "meta"})
        position = None
        height = None
        weight = None
        team = None

        if meta is not None:
            for p_tag in meta.find_all("p"):
                text = p_tag.get_text(" ", strip=True)
                if position is None and "Position" in text:
                    match = re.search(r"Position\s*:\s*([A-Za-z\-\s/]+)", text)
                    if match:
                        position = match.group(1).strip()
                if height is None:
                    h_match = re.search(r"(\d-\d{1,2})", text)
                    if h_match:
                        height = h_match.group(1)
                if weight is None:
                    w_match = re.search(r"(\d{2,3}lb)", text)
                    if w_match:
                        weight = w_match.group(1)
                if team is None and re.search(r"\bTeam\s*:", text):
                    t_match = re.search(r"\bTeam\s*:\s*([A-Za-z0-9\.\-\s'&]+)", text)
                    if t_match:
                        team = t_match.group(1).strip()
                if team is None and re.search(r"\bCollege\s*:", text):
                    c_match = re.search(r"\bCollege\s*:\s*([A-Za-z0-9\.\-\s'&]+)", text)
                    if c_match:
                        team = c_match.group(1).strip()

        stats, stats_team = _extract_stats_and_team(soup)
        if team is None and stats_team is not None:
            team = stats_team

        result = {
            "player_name": name,
            "position": position,
            "height": height,
            "weight": weight,
            "team": team,
            "pts": stats["pts"],
            "reb": stats["reb"],
            "ast": stats["ast"],
            "fg_pct": stats["fg_pct"],
            "three_pct": stats["three_pct"],
            "ft_pct": stats["ft_pct"],
            "games": stats["games"],
            "minutes": stats["minutes"],
            "source_url": player_url,
            "confidence": 0.0,
        }

        score_fields = [
            result["player_name"],
            result["position"],
            result["height"],
            result["weight"],
            result["team"],
            result["pts"],
            result["reb"],
            result["ast"],
            result["fg_pct"],
            result["three_pct"],
            result["ft_pct"],
            result["games"],
            result["minutes"],
        ]
        non_null_count = sum(v is not None for v in score_fields)
        result["confidence"] = round(non_null_count / 13, 3)
        return result
    except Exception:
        return _empty_result()
