from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import quote_plus, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Comment

from db import redis_cache
from tools.search import search
from tools.urlguard import UnsafeURLError, is_allowed_url, safe_get

_SR_DOMAINS = {"basketball-reference.com", "sports-reference.com"}
_ESPN_DOMAINS = {"espn.com"}

# Sports Reference enforces roughly 20 requests/minute and bans repeat
# violators. One process-wide lock spaces every SR request ~3s apart.
_SR_LOCK = asyncio.Lock()
_SR_SPACING_SECONDS = 3.0
_last_sr_request = 0.0

_HTML_CACHE_TTL_OK = 21600  # 6 hours for successful pages
_HTML_CACHE_TTL_MISS = 86400  # 24 hours for 404s (slug does not exist)

_HEADERS = {
    # Real identifying UA per Sports Reference's bot policy, not a spoofed browser.
    "User-Agent": "NBAScoutBot/1.0 (+https://nbascout.app)",
    "Accept-Language": "en-US,en;q=0.9",
}

_TOTAL_ROW_TEAMS = {"TOT", "2TM", "3TM", "4TM", "5TM"}


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
        "season": None,
        "pts": None,
        "reb": None,
        "ast": None,
        "fg_pct": None,
        "three_pct": None,
        "ft_pct": None,
        "fga": None,
        "fta": None,
        "games": None,
        "minutes": None,
        "source_url": None,
        "level": None,
        "confidence": 0.0,
    }


def _failure(status: str, *, level: str | None = None, http_status: int | None = None,
             error: str | None = None) -> dict:
    result = _empty_result()
    result["status"] = status
    result["http_status"] = http_status
    result["error"] = error
    if level:
        result["level"] = level
    return result


def _status_for_http(code: int) -> str:
    if code in (403, 429):
        return "blocked"
    if code == 404:
        return "not_found"
    return "parse_failed"


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


def _normalize_name_tokens(name: str) -> list[str]:
    cleaned = re.sub(r"[^a-zA-Z\s]", " ", name).lower()
    return [t for t in cleaned.split() if t]


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    previous = list(range(len(b) + 1))
    for i, ch_a in enumerate(a, start=1):
        current = [i]
        for j, ch_b in enumerate(b, start=1):
            cost = 0 if ch_a == ch_b else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1]


def _is_same_player(requested_name: str, found_name: str) -> bool:
    """Same last name plus a genuinely matching first name.

    First-initial-only matching let 'Jalen Williams' pass for 'Jaylen Williams'
    and 'Marcus Johnson' for 'Michael Johnson'. Now the first name must be
    equal, a nickname-style prefix (Cam/Cameron), or within edit-distance
    similarity > 0.9 — which one-letter variants of short names fail.
    """
    req_tokens = _normalize_name_tokens(requested_name)
    found_tokens = _normalize_name_tokens(found_name)
    if not req_tokens or not found_tokens:
        return False
    if req_tokens[-1] != found_tokens[-1]:
        return False
    first_req, first_found = req_tokens[0], found_tokens[0]
    if first_req == first_found:
        return True
    shorter, longer = sorted((first_req, first_found), key=len)
    if len(shorter) >= 3 and longer.startswith(shorter):
        return True
    distance = _levenshtein(first_req, first_found)
    similarity = 1 - distance / max(len(first_req), len(first_found))
    return similarity > 0.9


def _url_matches_requested_player(url: str, requested_name: str) -> bool:
    """Match the final path segment against the requested name.

    The old check passed when the last name appeared anywhere in the URL,
    which any query string can satisfy. Now the slug itself must encode the
    name in one of the two known formats:
    - Sports Reference CBB: first-last-1.html
    - Basketball Reference: lastxfir01.html (last[:5] + first[:2])
    """
    tokens = _normalize_name_tokens(requested_name)
    if len(tokens) < 2:
        return False
    first = tokens[0]
    last_candidates = {tokens[-1], "-".join(tokens[1:])}
    try:
        segment = urlparse(url).path.rstrip("/").split("/")[-1].lower()
    except ValueError:
        return False
    segment = segment.removesuffix(".html")
    for last in last_candidates:
        if segment.startswith(f"{first}-{last}"):
            return True
        prefix = last.replace("-", "")[:5]
        bare = segment.replace("-", "")
        if bare.startswith(prefix) and bare[len(prefix):len(prefix) + 2] == first[:2]:
            return True
    return False


async def _sr_get(client: httpx.AsyncClient, url: str) -> tuple[int, str, str]:
    """Throttled, allowlisted, Redis-cached GET for Sports Reference pages.

    Returns (status_code, body_text, final_url).
    """
    global _last_sr_request
    cache_key = f"html:{url}"
    cached = await redis_cache.get_json(cache_key)
    if cached is not None:
        return int(cached["status"]), cached["text"], cached["final_url"]

    async with _SR_LOCK:
        wait = _SR_SPACING_SECONDS - (time.monotonic() - _last_sr_request)
        if wait > 0:
            await asyncio.sleep(wait)
        response = await safe_get(client, url, _SR_DOMAINS, headers=_HEADERS)
        _last_sr_request = time.monotonic()

    if response.status_code == 429:
        retry_after = _to_int(response.headers.get("retry-after"))
        if retry_after and 0 < retry_after <= 15:
            await asyncio.sleep(retry_after)
            async with _SR_LOCK:
                response = await safe_get(client, url, _SR_DOMAINS, headers=_HEADERS)
                _last_sr_request = time.monotonic()

    status, text, final_url = response.status_code, response.text, str(response.url)
    if status == 200:
        await redis_cache.set_json(
            cache_key, {"status": status, "text": text, "final_url": final_url}, _HTML_CACHE_TTL_OK
        )
    elif status == 404:
        await redis_cache.set_json(
            cache_key, {"status": status, "text": "", "final_url": final_url}, _HTML_CACHE_TTL_MISS
        )
    return status, text, final_url


def _extract_stats_from_table(
    soup: BeautifulSoup, table_ids: list[str]
) -> tuple[dict | None, str | None, str | None]:
    """Parse the newest season row from a stats table.

    Returns (stats, team, season). stats is None when no table matched at
    all — a parse failure the caller must surface — as opposed to a real
    table with missing values. Within the latest season, a TOT/2TM combined
    row is preferred over a single team's partial split.
    """
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

    if table is None:
        return None, None, None

    tbody = table.find("tbody")
    if tbody is None:
        return None, None, None

    def row_season(row) -> str | None:
        cell = row.find(["th", "td"], {"data-stat": "year_id"}) or row.find(
            ["th", "td"], {"data-stat": "season"}
        )
        if cell is None:
            return None
        text = cell.get_text(strip=True)
        return text or None

    def row_team(row) -> str | None:
        cell = row.find("td", {"data-stat": "team_name_abbr"}) or row.find(
            "td", {"data-stat": "team_id"}
        )
        if cell is None:
            return None
        return cell.get_text(strip=True) or None

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
        return None, None, None

    latest_season = row_season(valid_rows[-1])
    candidate = valid_rows[-1]
    if latest_season:
        season_rows = [r for r in valid_rows if row_season(r) == latest_season]
        for row in season_rows:
            if (row_team(row) or "").upper() in _TOTAL_ROW_TEAMS:
                candidate = row
                break
        else:
            candidate = season_rows[-1]

    def get_stat(stat_name: str) -> str | None:
        cell = candidate.find("td", {"data-stat": stat_name})
        if cell is None:
            return None
        text = cell.get_text(strip=True)
        if not text or text == "--":
            return None
        return text

    team = row_team(candidate)
    stats = {
        "pts": _to_float(get_stat("pts_per_g")),
        "reb": _to_float(get_stat("trb_per_g")),
        "ast": _to_float(get_stat("ast_per_g")),
        "fg_pct": _to_float(get_stat("fg_pct")),
        "three_pct": _to_float(get_stat("fg3_pct")),
        "ft_pct": _to_float(get_stat("ft_pct")),
        "fga": _to_float(get_stat("fga_per_g") or get_stat("fga")),
        "fta": _to_float(get_stat("fta_per_g") or get_stat("fta")),
        "games": _to_int(get_stat("games") or get_stat("g")),
        "minutes": _to_float(get_stat("mp_per_g")),
    }
    return stats, team, row_season(candidate)


def _extract_page_name(soup: BeautifulSoup, fallback: str) -> str:
    name_tag = soup.find("h1", {"itemprop": "name"}) or soup.find("h1")
    if name_tag:
        text = name_tag.get_text(" ", strip=True)
        if text:
            return re.sub(
                r"\s+(?:College\s+|High\s+School\s+)?Stats\b.*", "", text, flags=re.IGNORECASE
            ).strip()
    title_tag = soup.find("title")
    if title_tag:
        raw_title = title_tag.get_text(" ", strip=True)
        cleaned = re.sub(
            r"\s+(?:College\s+|High\s+School\s+)?Stats\b.*", "", raw_title, flags=re.IGNORECASE
        ).strip()
        if cleaned:
            return cleaned
    return fallback


def _score_confidence(result: dict) -> float:
    score_fields = [
        result["player_name"], result["position"], result["height"],
        result["weight"], result["team"], result["pts"], result["reb"],
        result["ast"], result["fg_pct"], result["three_pct"],
        result["ft_pct"], result["games"], result["minutes"],
    ]
    return round(sum(v is not None for v in score_fields) / 13, 3)


def _build_result(
    *, name: str, position: str | None, height: str | None, weight: str | None,
    team: str | None, season: str | None, stats: dict, source_url: str, level: str,
) -> dict:
    result = _empty_result()
    result.update(
        {
            "status": "ok",
            "http_status": 200,
            "player_name": name,
            "position": position,
            "height": height,
            "weight": weight,
            "team": team,
            "season": season,
            "pts": stats["pts"],
            "reb": stats["reb"],
            "ast": stats["ast"],
            "fg_pct": stats["fg_pct"],
            "three_pct": stats["three_pct"],
            "ft_pct": stats["ft_pct"],
            "fga": stats.get("fga"),
            "fta": stats.get("fta"),
            "games": stats["games"],
            "minutes": stats["minutes"],
            "source_url": source_url,
            "level": level,
        }
    )
    result["confidence"] = _score_confidence(result)
    return result


def _parse_meta_bio(soup: BeautifulSoup, *, team_label: str) -> tuple[
    str | None, str | None, str | None, str | None
]:
    meta = soup.find("div", {"id": "meta"})
    position = height = weight = team = None
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
            if team is None and re.search(rf"\b{team_label}\s*:", text):
                t_match = re.search(rf"\b{team_label}\s*:\s*([A-Za-z0-9\.\-\s'&]+)", text)
                if t_match:
                    team = t_match.group(1).strip()
            if team is None and team_label == "Team" and re.search(r"\bCollege\s*:", text):
                c_match = re.search(r"\bCollege\s*:\s*([A-Za-z0-9\.\-\s'&]+)", text)
                if c_match:
                    team = c_match.group(1).strip()
    return position, height, weight, team


async def get_player_stats(player_name: str) -> dict:
    if not player_name.strip():
        return _failure("not_found", level="pro", error="empty player name")

    player_page_pattern = re.compile(r"/players/[a-z]/[a-z0-9'\-]+\.html")

    try:
        search_url = (
            "https://www.basketball-reference.com/search/search.fcgi?search="
            f"{quote_plus(player_name)}"
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            status, body, final_url = await _sr_get(client, search_url)
            if status != 200:
                return _failure(_status_for_http(status), level="pro", http_status=status,
                                error=f"search returned HTTP {status}")

            player_url = final_url
            player_html = body

            if not player_page_pattern.search(final_url):
                soup_search = BeautifulSoup(body, "html.parser")
                found_link = None
                for a_tag in soup_search.find_all("a", href=True):
                    href = a_tag["href"]
                    if player_page_pattern.search(href):
                        found_link = urljoin("https://www.basketball-reference.com", href)
                        break
                if not found_link:
                    return _failure("not_found", level="pro", http_status=200,
                                    error="no player link in search results")
                status, player_html, player_url = await _sr_get(client, found_link)
                if status != 200:
                    return _failure(_status_for_http(status), level="pro", http_status=status,
                                    error=f"player page returned HTTP {status}")
                if not _url_matches_requested_player(player_url, player_name):
                    return _failure("not_found", level="pro", http_status=200,
                                    error="search landed on a different player")

        soup = BeautifulSoup(player_html, "html.parser")
        name = _extract_page_name(soup, player_name)
        if not _is_same_player(player_name, name):
            return _failure("not_found", level="pro", http_status=200,
                            error=f"page belongs to '{name}', not '{player_name}'")

        position, height, weight, team = _parse_meta_bio(soup, team_label="Team")
        stats, stats_team, season = _extract_stats_from_table(
            soup, ["per_game_stats", "per_game"]
        )
        if stats is None:
            return _failure("parse_failed", level="pro", http_status=200,
                            error="per-game table not found; markup may have changed")
        if team is None and stats_team is not None:
            team = stats_team

        return _build_result(
            name=name, position=position, height=height, weight=weight, team=team,
            season=season, stats=stats, source_url=player_url, level="pro",
        )
    except UnsafeURLError as exc:
        return _failure("parse_failed", level="pro", error=str(exc))
    except Exception as exc:
        return _failure("parse_failed", level="pro", error=str(exc))


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
    if not player_name.strip():
        return _failure("not_found", level="college", error="empty player name")

    try:
        player_url: str | None = None
        player_html: str | None = None
        blocked_status: int | None = None

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Fast path: canonical slug URLs. The page name (h1/title) is the
            # verification — never the URL, which just echoes the input name.
            # When both -1 and -2 exist the slug is ambiguous between two
            # players; fall through to search rather than guessing.
            direct_urls = _cbb_direct_urls(player_name)
            direct_hits: list[tuple[str, str]] = []
            for direct_url in direct_urls:
                status, body, final_url = await _sr_get(client, direct_url)
                if status in (403, 429):
                    blocked_status = status
                    break
                if status == 200:
                    direct_hits.append((final_url, body))
            if blocked_status is not None:
                return _failure("blocked", level="college", http_status=blocked_status,
                                error=f"Sports Reference returned HTTP {blocked_status}")
            if len(direct_hits) == 1:
                candidate_url, candidate_html = direct_hits[0]
                candidate_soup = BeautifulSoup(candidate_html, "html.parser")
                page_name = _extract_page_name(candidate_soup, "")
                if page_name and _is_same_player(player_name, page_name):
                    player_url, player_html = candidate_url, candidate_html

            # Fall back to the search redirect.
            if not player_html:
                search_url = (
                    "https://www.sports-reference.com/cbb/search/search.fcgi?search="
                    f"{quote_plus(player_name)}"
                )
                status, body, final_url = await _sr_get(client, search_url)
                if status != 200:
                    return _failure(_status_for_http(status), level="college",
                                    http_status=status,
                                    error=f"search returned HTTP {status}")

                player_url = final_url
                player_html = body

                if "/cbb/players/" not in final_url:
                    soup_search = BeautifulSoup(body, "html.parser")
                    found_link = None
                    for a_tag in soup_search.find_all("a", href=True):
                        href = a_tag["href"]
                        if "/cbb/players/" in href and href.endswith(".html"):
                            found_link = urljoin("https://www.sports-reference.com", href)
                            break
                    if not found_link:
                        return _failure("not_found", level="college", http_status=200,
                                        error="no player link in search results")
                    status, player_html, player_url = await _sr_get(client, found_link)
                    if status != 200:
                        return _failure(_status_for_http(status), level="college",
                                        http_status=status,
                                        error=f"player page returned HTTP {status}")

        soup = BeautifulSoup(player_html, "html.parser")
        name = _extract_page_name(soup, player_name)
        if name and not _is_same_player(player_name, name):
            return _failure("not_found", level="college", http_status=200,
                            error=f"page belongs to '{name}', not '{player_name}'")

        position, height, weight, team = _parse_meta_bio(soup, team_label="School")
        stats, stats_team, season = _extract_stats_from_table(soup, ["players_per_game"])
        if stats is None:
            return _failure("parse_failed", level="college", http_status=200,
                            error="players_per_game table not found; markup may have changed")
        if team is None and stats_team is not None:
            team = stats_team

        return _build_result(
            name=name, position=position, height=height, weight=weight, team=team,
            season=season, stats=stats, source_url=player_url or "", level="college",
        )
    except UnsafeURLError as exc:
        return _failure("parse_failed", level="college", error=str(exc))
    except Exception as exc:
        return _failure("parse_failed", level="college", error=str(exc))


# ---------------------------------------------------------------------------
# Wingspan
# ---------------------------------------------------------------------------

def _parse_wingspan_from_text(text: str) -> str | None:
    """Extract a wingspan string (e.g. '7-1') from arbitrary text."""

    def _fmt(feet: int, inches: float) -> str | None:
        if not (5 <= feet <= 9 and 0 <= inches < 12):
            return None
        return f"{feet}-{int(inches)}" if inches == int(inches) else f"{feet}-{inches:.1f}"

    # "6'11" wingspan" / "6′11.5″" (with various quote chars)
    m = re.search(
        r"(\d+)\s*['''′]\s*(\d+(?:\.\d+)?)\s*[\"″]?\s*(?:wingspan|wing[\s\-]span)",
        text, re.IGNORECASE,
    )
    if m:
        return _fmt(int(m.group(1)), float(m.group(2)))

    # "wingspan of 7 feet 3 inches" / "7 feet 3 inch wingspan"
    m = re.search(
        r"(\d+)\s*feet?\s+(\d+(?:\.\d+)?)\s*inch(?:es?)?\s*(?:wingspan|wing[\s\-]span)?",
        text, re.IGNORECASE,
    )
    if m:
        return _fmt(int(m.group(1)), float(m.group(2)))

    # "87 inches wingspan" / "87.5-inch wingspan"
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*[-\s]?inch(?:es?)?\s*(?:wingspan|wing[\s\-]span)",
        text, re.IGNORECASE,
    )
    if m:
        total = float(m.group(1))
        if 60 <= total <= 110:
            return _fmt(int(total // 12), total % 12)

    # "wingspan 7.25 feet" / "7.5-foot wingspan"
    m = re.search(
        r"(?:wingspan[^.]{0,10}?)(\d+\.\d+)\s*(?:feet?|ft)\b",
        text, re.IGNORECASE,
    )
    if m:
        total_feet = float(m.group(1))
        return _fmt(int(total_feet), (total_feet % 1) * 12)

    return None


async def get_wingspan(player_name: str, team: str = "") -> dict:
    """Search web sources for a player's wingspan measurement."""
    context = f"{player_name} {team}".strip() if team else player_name
    for query in [
        f"{context} wingspan inches NBA draft combine",
        f"{context} wingspan measurement",
    ]:
        results = await search(query=query, max_results=6)
        for item in results:
            blob = f"{item.get('title', '')} {item.get('snippet', '')}"
            ws = _parse_wingspan_from_text(blob)
            if ws:
                return {"status": "ok", "wingspan": ws, "source_url": item.get("url")}
    return {"status": "not_found", "wingspan": None, "source_url": None}


# ---------------------------------------------------------------------------
# ESPN fallback
# ---------------------------------------------------------------------------

def _parse_espn_stats_tables(soup: BeautifulSoup) -> dict:
    """Parse per-game stats out of ESPN's HTML stats tables.

    Handles header rows that mix th and td cells by indexing all header
    cells together, and converts whole-number percentages (46.8) to
    decimals (0.468).
    """
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

        stats["games"] = _to_int(_cell(_col("GP", "G", "GAMES")))
        stats["minutes"] = _to_float(_cell(_col("MIN", "MPG", "MP")))
        stats["pts"] = _to_float(_cell(_col("PTS", "PPG")))
        stats["reb"] = _to_float(_cell(_col("REB", "RPG", "TREB")))
        stats["ast"] = _to_float(_cell(_col("AST", "APG")))
        stats["fg_pct"] = _to_float(_cell(_col("FG%", "FGP")))
        stats["three_pct"] = _to_float(_cell(_col("3P%", "3PT%", "3FG%")))
        stats["ft_pct"] = _to_float(_cell(_col("FT%", "FTP")))

        # ESPN encodes percentages as whole numbers (e.g. 46.8 → 0.468).
        for pct_key in ("fg_pct", "three_pct", "ft_pct"):
            v = stats[pct_key]
            if isinstance(v, float) and v > 1.0:
                stats[pct_key] = round(v / 100, 4)

        if any(v is not None for v in stats.values()):
            break

    return stats


async def get_espn_college_stats(player_name: str) -> dict:
    """Fetch college stats from ESPN as a fallback when Sports Reference lacks data."""
    if not player_name.strip():
        return _failure("not_found", level="college", error="empty player name")

    try:
        # Step 1 — find the ESPN numeric player ID from search results.
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
                if not is_allowed_url(url, _ESPN_DOMAINS) or "player" not in url:
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
            return _failure("not_found", level="college",
                            error="no ESPN player profile found in search results")

        result = _empty_result()
        result["level"] = "college"
        stats_page_url = (
            f"https://www.espn.com/mens-college-basketball/player/stats/_/id/{player_id}"
        )
        result["source_url"] = stats_page_url

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Step 2a — try multiple ESPN JSON API variants.
            _api_candidates = [
                (
                    "https://site.web.api.espn.com/apis/common/v3/sports/basketball"
                    f"/mens-college-basketball/athletes/{player_id}/overview"
                ),
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
                    _r = await safe_get(client, api_url, _ESPN_DOMAINS, headers=_HEADERS)
                    if _r.status_code == 200:
                        api_data = _r.json()
                        break
                except Exception:
                    pass
            if api_data:
                try:
                    data = api_data
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

                    if result.get("pts") is not None or result.get("games") is not None:
                        result["status"] = "ok"
                        result["http_status"] = 200
                        result["confidence"] = _score_confidence(result)
                        return result
                except Exception:
                    pass

            # Step 2b — fall back to the HTML stats page.
            page_resp = await safe_get(client, stats_page_url, _ESPN_DOMAINS, headers=_HEADERS)
            if page_resp.status_code != 200 or not page_resp.text:
                return _failure(_status_for_http(page_resp.status_code), level="college",
                                http_status=page_resp.status_code,
                                error=f"ESPN stats page returned HTTP {page_resp.status_code}")

        soup = BeautifulSoup(page_resp.text, "html.parser")
        page_text = soup.get_text(" ", strip=True)

        name_tag = soup.find("h1") or soup.find("title")
        page_name = name_tag.get_text(" ", strip=True).split("|")[0].strip() if name_tag else ""
        if page_name and not _is_same_player(player_name, page_name):
            return _failure("not_found", level="college", http_status=200,
                            error=f"page belongs to '{page_name}', not '{player_name}'")

        result["player_name"] = page_name or player_name

        pos_match = re.search(r"\b(PG|SG|SF|PF|C)\b", page_text)
        if pos_match:
            result["position"] = pos_match.group(1)
        h_match = re.search(r"(\d-\d{1,2})", page_text)
        if h_match:
            result["height"] = h_match.group(1)
        w_match = re.search(r"(\d{2,3})\s?lbs?", page_text, re.IGNORECASE)
        if w_match:
            result["weight"] = f"{w_match.group(1)}lb"

        stats = _parse_espn_stats_tables(soup)
        result.update(stats)
        result["status"] = "ok" if any(v is not None for v in stats.values()) else "parse_failed"
        result["http_status"] = 200
        if result["status"] == "parse_failed":
            result["error"] = "no recognizable stats table on ESPN page"
        result["confidence"] = _score_confidence(result)
        return result

    except UnsafeURLError as exc:
        return _failure("parse_failed", level="college", error=str(exc))
    except Exception as exc:
        return _failure("parse_failed", level="college", error=str(exc))
