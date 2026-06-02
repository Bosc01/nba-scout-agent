from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Comment

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

    # Sports Reference often wraps tables in HTML comments; parse those too.
    if table is None:
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            comment_str = str(comment)
            for table_id in table_ids:
                if table_id in comment_str:
                    comment_soup = BeautifulSoup(comment_str, "html.parser")
                    found = comment_soup.find("table", {"id": table_id})
                    if found is not None:
                        table = found
                        break
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


def _cbb_direct_urls(player_name: str) -> list[str]:
    """Build candidate Sports Reference CBB player URLs from a name."""
    tokens = _normalize_name_tokens(player_name)
    if len(tokens) < 2:
        return []
    first = tokens[0]
    last = "-".join(tokens[1:])
    base = f"https://www.sports-reference.com/cbb/players/{first}-{last}"
    return [f"{base}-1.html", f"{base}-2.html"]


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
        player_url: str | None = None
        player_html: str | None = None

        async with httpx.AsyncClient(follow_redirects=True, timeout=8) as client:
            # Fast-path: try the canonical URL pattern directly before using search.
            # The URL slug is derived from the player name so URL matching is sufficient;
            # CBB pages don't always carry an <h1 itemprop="name"> tag.
            for direct_url in _cbb_direct_urls(player_name):
                r = await client.get(direct_url, headers=headers)
                if r.status_code != 200:
                    continue
                if _url_matches_requested_player(str(r.url), player_name):
                    player_url = str(r.url)
                    player_html = r.text
                    break

            # Fall back to the search redirect if direct URLs didn't work.
            if not player_html:
                search_url = (
                    "https://www.sports-reference.com/cbb/search/search.fcgi?search="
                    f"{player_name.replace(' ', '+')}"
                )
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
            if title_tag:
                raw_title = title_tag.get_text(" ", strip=True)
                # CBB title format: "Jordan Pope College Stats | Sports Reference"
                # Strip " College Stats …" so we're left with just "Jordan Pope".
                name = re.sub(
                    r"\s+(?:College\s+|High\s+School\s+)?Stats\b.*",
                    "",
                    raw_title,
                    flags=re.IGNORECASE,
                ).strip()
            if not name:
                name = player_name
        # Only reject when we have a name that clearly belongs to someone else.
        if name and not _is_same_player(player_name, name):
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
        # Step 1 — find the ESPN numeric player ID from search results.
        # Build the expected URL slug: "jordan-pope" for "Jordan Pope".
        _tokens = _normalize_name_tokens(player_name)
        _expected_slug = (
            f"{_tokens[0]}-{_tokens[-1]}" if len(_tokens) >= 2 else player_name.lower()
        )

        player_id: str | None = None
        _fallback_id: str | None = None

        for query in [
            f"{player_name} site:espn.com mens-college-basketball player",
            f"{player_name} ESPN college basketball player stats",
        ]:
            for item in await search(query=query, max_results=10):
                url = str(item.get("url", ""))
                if "espn.com" not in url or "player" not in url:
                    continue
                # Skip non-profile pages.
                if any(x in url for x in ["/news/", "/gamelog/", "/playbyplay/", "/game/"]):
                    continue
                m = re.search(r"/id/(\d+)", url)
                if not m:
                    continue
                # Prefer URLs whose trailing name slug matches exactly.
                path_slug = url.rstrip("/").split("/")[-1].lower()
                if path_slug == _expected_slug:
                    player_id = m.group(1)
                    break
                if _fallback_id is None:
                    _fallback_id = m.group(1)
            if player_id:
                break

        player_id = player_id or _fallback_id

        if not player_id:
            return result

        stats_page_url = (
            f"https://www.espn.com/mens-college-basketball/player/stats/_/id/{player_id}"
        )
        result["source_url"] = stats_page_url

        async with httpx.AsyncClient(follow_redirects=True, timeout=8) as client:
            # Step 2a — try multiple ESPN JSON API variants (fast, no JS rendering needed).
            api_url = (
                "https://site.web.api.espn.com/apis/common/v3/sports/basketball"
                f"/mens-college-basketball/athletes/{player_id}/overview"
            )
            # Fallback API URLs tried in order.
            _api_candidates = [
                api_url,
                (
                    "https://site.web.api.espn.com/apis/site/v2/sports/basketball"
                    f"/mens-college-basketball/athletes/{player_id}/statistics"
                ),
                (
                    "https://site.api.espn.com/apis/site/v2/sports/basketball"
                    f"/mens-college-basketball/athletes/{player_id}/statistics"
                ),
            ]
            api_data: dict = {}
            for api_url in _api_candidates:
                try:
                    _r = await client.get(api_url, headers=headers)
                    if _r.status_code == 200:
                        api_data = _r.json()
                        break
                except Exception:
                    pass
            if api_data:
                try:
                    data = api_data
                    # Stat names ESPN uses in the API payload.
                    _api_map = {
                        "gamesPlayed": "games",
                        "avgMinutes": "minutes",
                        "avgPoints": "pts",
                        "avgRebounds": "reb",
                        "avgAssists": "ast",
                        "fieldGoalPct": "fg_pct",
                        "threePointFieldGoalPct": "three_pct",
                        "freeThrowPct": "ft_pct",
                    }

                    def _walk(node: object) -> None:
                        if isinstance(node, dict):
                            name_key = node.get("name") or node.get("abbreviation", "")
                            val = node.get("value")
                            if name_key in _api_map and val is not None:
                                key = _api_map[name_key]
                                v = float(val)
                                # API returns pct as 0-1 already for some fields
                                if key in ("fg_pct", "three_pct", "ft_pct") and v > 1.0:
                                    v = round(v / 100, 4)
                                if key == "games":
                                    result[key] = int(v)
                                else:
                                    result[key] = v
                            for child in node.values():
                                _walk(child)
                        elif isinstance(node, list):
                            for item in node:
                                _walk(item)

                    _walk(data)

                    # Also grab bio from the athlete node.
                    athlete = data.get("athlete", {})
                    if not result["player_name"]:
                        result["player_name"] = athlete.get("displayName") or player_name
                    if not result["position"]:
                        pos = (athlete.get("position") or {}).get("abbreviation")
                        if pos:
                            result["position"] = pos
                    if not result["height"]:
                        ht = athlete.get("height")
                        if ht:
                            feet, inches = divmod(int(ht), 12)
                            result["height"] = f"{feet}-{inches}"
                    if not result["weight"]:
                        wt = athlete.get("weight")
                        if wt:
                            result["weight"] = f"{int(wt)}lb"
                    if not result["team"]:
                        team_node = (athlete.get("team") or {})
                        result["team"] = team_node.get("displayName") or team_node.get("name")

                    # If we got meaningful stats from the API, return now.
                    if result.get("pts") is not None or result.get("games") is not None:
                        score_fields = [
                            result["player_name"], result["position"], result["height"],
                            result["weight"], result["team"], result["pts"], result["reb"],
                            result["ast"], result["fg_pct"], result["three_pct"],
                            result["ft_pct"], result["games"], result["minutes"],
                        ]
                        result["confidence"] = round(
                            sum(v is not None for v in score_fields) / 13, 3
                        )
                        return result
                except Exception:
                    pass

            # Step 2b — fall back to the HTML stats page and parse any tables found.
            page_resp = await client.get(stats_page_url, headers=headers)
            if page_resp.status_code != 200 or not page_resp.text:
                return result

        soup = BeautifulSoup(page_resp.text, "html.parser")
        page_text = soup.get_text(" ", strip=True)

        # Verify we landed on the right player.
        name_tag = soup.find("h1") or soup.find("title")
        page_name = name_tag.get_text(" ", strip=True).split("|")[0].strip() if name_tag else ""
        if page_name and not _is_same_player(player_name, page_name):
            return result

        result["player_name"] = page_name or player_name

        # Bio from page text.
        pos_match = re.search(r"\b(PG|SG|SF|PF|C)\b", page_text)
        if pos_match:
            result["position"] = pos_match.group(1)
        h_match = re.search(r"(\d-\d{1,2})", page_text)
        if h_match:
            result["height"] = h_match.group(1)
        w_match = re.search(r"(\d{2,3})\s?lbs?", page_text, re.IGNORECASE)
        if w_match:
            result["weight"] = f"{w_match.group(1)}lb"

        # Step 3 — look for a stats table containing the expected column headers.
        target_cols = {"GP", "FG%", "3P%", "FT%", "REB", "AST", "PTS"}
        stats: dict[str, float | int | None] = {
            "pts": None, "reb": None, "ast": None,
            "fg_pct": None, "three_pct": None, "ft_pct": None,
            "games": None, "minutes": None,
        }

        for table in soup.find_all("table"):
            header_row = table.find("tr")
            if not header_row:
                continue
            all_headers = [
                c.get_text(strip=True).upper()
                for c in header_row.find_all(["th", "td"])
            ]
            if not target_cols.issubset(set(all_headers)):
                continue

            col = {h: i for i, h in enumerate(all_headers)}

            def _col(*names: str) -> int | None:
                for n in names:
                    if n in col:
                        return col[n]
                return None

            # Prefer the 2025-26 row; otherwise take the last data row.
            data_rows = [
                r for r in table.find_all("tr")
                if r.find("td") and "Total" not in r.get_text()
            ]
            if not data_rows:
                continue
            target_row = next(
                (r for r in data_rows if "2025" in r.get_text() or "2026" in r.get_text()),
                data_rows[-1],
            )
            cells = [td.get_text(strip=True) for td in target_row.find_all("td")]

            def _cell(idx: int | None) -> str | None:
                if idx is None or idx >= len(cells):
                    return None
                v = cells[idx]
                return v if v and v != "--" else None

            stats["games"]     = _to_int(_cell(_col("GP", "G", "GAMES")))
            stats["minutes"]   = _to_float(_cell(_col("MIN", "MPG", "MP")))
            stats["pts"]       = _to_float(_cell(_col("PTS", "PPG")))
            stats["reb"]       = _to_float(_cell(_col("REB", "RPG", "TREB")))
            stats["ast"]       = _to_float(_cell(_col("AST", "APG")))
            stats["fg_pct"]    = _to_float(_cell(_col("FG%", "FGP")))
            stats["three_pct"] = _to_float(_cell(_col("3P%", "3PT%", "3FG%")))
            stats["ft_pct"]    = _to_float(_cell(_col("FT%", "FTP")))

            # ESPN encodes percentages as whole numbers (e.g. 46.8 → 0.468).
            for pct_key in ("fg_pct", "three_pct", "ft_pct"):
                v = stats[pct_key]
                if isinstance(v, float) and v > 1.0:
                    stats[pct_key] = round(v / 100, 4)

            if any(v is not None for v in stats.values()):
                break

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
