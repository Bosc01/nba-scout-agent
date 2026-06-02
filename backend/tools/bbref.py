from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from tools.search import search


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
        "level": None,
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


def _normalize_name_tokens(name: str) -> list[str]:
    cleaned = re.sub(r"[^a-zA-Z\s]", " ", name).lower()
    return [t for t in cleaned.split() if t]


def _is_same_player(requested_name: str, found_name: str) -> bool:
    req_tokens = _normalize_name_tokens(requested_name)
    found_tokens = _normalize_name_tokens(found_name)
    if not req_tokens or not found_tokens:
        return False
    if req_tokens[-1] != found_tokens[-1]:
        return False
    return req_tokens[0][0] == found_tokens[0][0]


def _url_matches_requested_player(url: str, requested_name: str) -> bool:
    tokens = _normalize_name_tokens(requested_name)
    if not tokens:
        return False
    last_name = tokens[-1]
    first_name = tokens[0]
    slug = url.lower()
    if last_name in slug:
        return True
    # Basketball Reference slugs abbreviate surnames (e.g. risacza01).
    if len(last_name) >= 5 and last_name[:5] in slug:
        return True
    if len(last_name) >= 4 and last_name[:4] in slug and first_name[:1] in slug:
        return True
    return False
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _extract_stats_from_table(soup: BeautifulSoup, table_ids: list[str]) -> tuple[dict, str | None]:
    table = None
    for table_id in table_ids:
        table = soup.find("table", {"id": table_id})
        if table is not None:
            break
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

    tbody = table.find("tbody")
    if tbody is None:
        return empty_stats, None

    valid_rows = []
    for row in tbody.find_all("tr"):
        classes = row.get("class", [])
        if "thead" in classes or "partial_table" in classes:
            continue
        row_text = row.get_text(" ", strip=True).lower()
        if "did not play" in row_text:
            continue
        valid_rows.append(row)

    if not valid_rows:
        return empty_stats, None
    candidate = valid_rows[-1]

    def get_stat(stat_name: str) -> str | None:
        cell = candidate.find("td", {"data-stat": stat_name})
        if cell is None:
            return None
        text = cell.get_text(strip=True)
        if not text or text == "--":
            return None
        return text

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
        async with httpx.AsyncClient(follow_redirects=True, timeout=8) as client:
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
                if not _url_matches_requested_player(player_url, player_name):
                    return result
                player_html = player_response.text

        soup = BeautifulSoup(player_html, "html.parser")
        name_tag = soup.find("h1", {"itemprop": "name"})
        name = name_tag.get_text(" ", strip=True) if name_tag else None
        if name is None:
            title_tag = soup.find("title")
            name = title_tag.get_text(" ", strip=True).split(" Stats", 1)[0].strip() if title_tag else player_name
        if not _is_same_player(player_name, name):
            return result

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

        stats, stats_team = _extract_stats_from_table(soup, ["per_game_stats", "per_game"])
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
            "level": "pro",
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


async def get_college_stats(player_name: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    result = _empty_result()
    result["level"] = "college"
    if not player_name.strip():
        return result

    try:
        search_url = (
            "https://www.sports-reference.com/cbb/search/search.fcgi?search="
            f"{player_name.replace(' ', '+')}"
        )
        async with httpx.AsyncClient(follow_redirects=True, timeout=8) as client:
            response = await client.get(search_url, headers=headers)
            if response.status_code != 200:
                return result

            final_url = str(response.url)
            player_url = final_url
            player_html = response.text

            if "/cbb/players/" in final_url and not _url_matches_requested_player(final_url, player_name):
                return result

            if "/cbb/players/" not in final_url:
                soup_search = BeautifulSoup(response.text, "html.parser")
                found_link = None
                for a_tag in soup_search.find_all("a", href=True):
                    href = a_tag["href"]
                    if "/cbb/players/" in href and href.endswith(".html"):
                        found_link = urljoin("https://www.sports-reference.com", href)
                        break
                if not found_link:
                    return result
                player_response = await client.get(found_link, headers=headers)
                if player_response.status_code != 200:
                    return result
                player_url = str(player_response.url)
                if not _url_matches_requested_player(player_url, player_name):
                    return result
                player_html = player_response.text

        soup = BeautifulSoup(player_html, "html.parser")
        name_tag = soup.find("h1", {"itemprop": "name"})
        name = name_tag.get_text(" ", strip=True) if name_tag else None
        if name is None:
            title_tag = soup.find("title")
            name = title_tag.get_text(" ", strip=True).split(" Stats", 1)[0].strip() if title_tag else player_name
        if not _is_same_player(player_name, name):
            return result

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
                if team is None and "School" in text:
                    s_match = re.search(r"School\s*:\s*([A-Za-z0-9\.\-\s'&]+)", text)
                    if s_match:
                        team = s_match.group(1).strip()

        stats, stats_team = _extract_stats_from_table(soup, ["players_per_game"])
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
            "level": "college",
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
        return _empty_result() | {"level": "college"}


async def get_espn_college_stats(player_name: str) -> dict:
    """Fetch college stats from ESPN as a fallback when Sports Reference lacks data."""
    result = _empty_result()
    result["level"] = "college"
    if not player_name.strip():
        return result

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        # Discover the player's ESPN page via web search
        query = f"{player_name} ESPN college stats site:espn.com mens-college-basketball player"
        search_results = await search(query=query, max_results=8)

        player_url: str | None = None
        for item in search_results:
            url = str(item.get("url", ""))
            if "espn.com" in url and "mens-college-basketball" in url and "player" in url:
                player_url = url
                break

        if not player_url:
            # Broaden the search if the strict one found nothing
            fallback_results = await search(
                query=f"{player_name} ESPN mens college basketball player stats",
                max_results=8,
            )
            for item in fallback_results:
                url = str(item.get("url", ""))
                if "espn.com" in url and ("college-basketball" in url or "ncb" in url) and "player" in url:
                    player_url = url
                    break

        if not player_url:
            return result

        async with httpx.AsyncClient(follow_redirects=True, timeout=8) as client:
            response = await client.get(player_url, headers=headers)
            if response.status_code != 200 or not response.text:
                return result

        soup = BeautifulSoup(response.text, "html.parser")

        # Verify we landed on the right player
        name_tag = soup.find("h1") or soup.find("title")
        page_name = name_tag.get_text(" ", strip=True).split("|")[0].strip() if name_tag else ""
        if page_name and not _is_same_player(player_name, page_name):
            return result

        result["player_name"] = page_name or player_name
        result["source_url"] = player_url

        # Bio: position / height / weight
        page_text = soup.get_text(" ", strip=True)
        pos_match = re.search(r"\b(PG|SG|SF|PF|C|Guard|Forward|Center)\b", page_text)
        if pos_match:
            result["position"] = pos_match.group(1)
        h_match = re.search(r"(\d-\d{1,2})", page_text)
        if h_match:
            result["height"] = h_match.group(1)
        w_match = re.search(r"(\d{2,3})\s?lbs?", page_text, re.IGNORECASE)
        if w_match:
            result["weight"] = f"{w_match.group(1)}lb"

        # Team / school
        school_match = re.search(r"(?:School|College|Team)\s*[:\-]?\s*([A-Za-z0-9 &'.]+)", page_text)
        if school_match:
            result["team"] = school_match.group(1).strip()

        # Stats table — ESPN uses <tr> rows with class "Table__TR"
        stats: dict[str, float | int | None] = {
            "pts": None, "reb": None, "ast": None,
            "fg_pct": None, "three_pct": None, "ft_pct": None,
            "games": None, "minutes": None,
        }

        table = soup.find("table")
        if table:
            # Find header row to map column indices
            header_row = table.find("tr")
            if header_row:
                headers_list = [th.get_text(strip=True).upper() for th in header_row.find_all(["th", "td"])]
                col = {h: i for i, h in enumerate(headers_list)}

                # ESPN header names vary; normalise common aliases
                alias = {
                    "GP": "G", "MIN": "MPG", "FG%": "FG%", "3P%": "3P%",
                    "FT%": "FT%", "PTS": "PTS", "REB": "REB", "AST": "AST",
                }
                # Build a lookup tolerant of ESPN's header names
                def _col(*names: str) -> int | None:
                    for n in names:
                        if n in col:
                            return col[n]
                        if alias.get(n, n) in col:
                            return col[alias[n]]
                    return None

                # Last data row holds the most-recent season
                data_rows = [
                    r for r in table.find_all("tr")
                    if r.find("td") and "Total" not in r.get_text()
                ]
                if data_rows:
                    cells = [td.get_text(strip=True) for td in data_rows[-1].find_all("td")]

                    def _cell(idx: int | None) -> str | None:
                        if idx is None or idx >= len(cells):
                            return None
                        v = cells[idx]
                        return v if v and v != "--" else None

                    stats["games"]     = _to_int(_cell(_col("GP", "G", "GAMES")))
                    stats["minutes"]   = _to_float(_cell(_col("MIN", "MPG", "MP")))
                    stats["pts"]       = _to_float(_cell(_col("PTS", "PPG")))
                    stats["reb"]       = _to_float(_cell(_col("REB", "RPG")))
                    stats["ast"]       = _to_float(_cell(_col("AST", "APG")))
                    stats["fg_pct"]    = _to_float(_cell(_col("FG%", "FGP")))
                    stats["three_pct"] = _to_float(_cell(_col("3P%", "3PT%", "3FG%")))
                    stats["ft_pct"]    = _to_float(_cell(_col("FT%", "FTP")))

                    # ESPN stores percentages as whole numbers (e.g. 46.8); normalise to 0-1
                    for pct_key in ("fg_pct", "three_pct", "ft_pct"):
                        v = stats[pct_key]
                        if isinstance(v, float) and v > 1.0:
                            stats[pct_key] = round(v / 100, 4)

        result.update(stats)

        score_fields = [
            result["player_name"], result["position"], result["height"],
            result["weight"], result["team"], result["pts"], result["reb"],
            result["ast"], result["fg_pct"], result["three_pct"],
            result["ft_pct"], result["games"], result["minutes"],
        ]
        result["confidence"] = round(sum(v is not None for v in score_fields) / 13, 3)
        return result

    except Exception:
        return _empty_result() | {"level": "college"}
