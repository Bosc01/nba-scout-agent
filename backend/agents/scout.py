from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from tools.bbref import get_college_stats, get_espn_college_stats, get_player_stats, get_wingspan
from tools.euroleague import get_euroleague_stats
from tools.fiba import get_fiba_profile
from tools.search import search

load_dotenv(override=True)

_report_cache: dict[str, Any] = {}


class ScoutAgent:
    MODEL = "claude-sonnet-4-6"

    def __init__(self) -> None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        self.client = AsyncAnthropic(api_key=api_key)
        self.tool_call_counts: dict[str, int] = {
            "web_search": 0,
            "get_player_stats": 0,
            "get_college_stats": 0,
            "get_espn_college_stats": 0,
            "get_wingspan": 0,
            "get_euroleague_stats": 0,
            "get_fiba_profile": 0,
        }
        self.tool_calls: list[dict[str, Any]] = []

    def _tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "web_search",
                "description": "Search the web for player-related information and sources.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "get_player_stats",
                "description": "Get Basketball Reference bio and recent per-game statistics.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "player_name": {"type": "string"},
                    },
                    "required": ["player_name"],
                },
            },
            {
                "name": "get_college_stats",
                "description": "Get college basketball stats from Sports Reference",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "player_name": {"type": "string"},
                    },
                    "required": ["player_name"],
                },
            },
            {
                "name": "get_espn_college_stats",
                "description": (
                    "Get college basketball stats from ESPN. "
                    "Use as a fallback when get_college_stats returns null shooting percentages."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "player_name": {"type": "string"},
                    },
                    "required": ["player_name"],
                },
            },
            {
                "name": "get_wingspan",
                "description": (
                    "Get player wingspan measurement from draft combine or scouting sources. "
                    "Call for any player where physical.wingspan is null after other tools run."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "player_name": {"type": "string"},
                        "team": {"type": "string"},
                    },
                    "required": ["player_name"],
                },
            },
            {
                "name": "get_euroleague_stats",
                "description": "Get Euroleague professional stats",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "player_name": {"type": "string"},
                    },
                    "required": ["player_name"],
                },
            },
            {
                "name": "get_fiba_profile",
                "description": "Get FIBA international basketball profile",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "player_name": {"type": "string"},
                    },
                    "required": ["player_name"],
                },
            },
        ]

    @staticmethod
    def _system_prompt() -> str:
        return """SPEED MODE: Maximum 4 tool calls. Call get_player_stats
first, then get_college_stats, then maximum 2 web searches.
Stop immediately after 4 calls and generate report with
whatever data you have. Do not exceed 4 tool calls under
any circumstances.

You have a tool call budget of 5. Use it wisely.
You are a conservative NBA scout generating reports grounded ONLY
in tool outputs. Never invent numbers or stats.
If the player name includes a team or school context (e.g.
'Marcus Johnson Duke'), use that context to disambiguate between
players with the same name. Search specifically for that
player at that institution.

Research order — follow this exactly:
1. Call get_player_stats (NBA/pro Basketball Reference)
2. Call web_search: '{player_name} height weight position team 2026 NBA draft'
3. Call get_college_stats (Sports Reference CBB)
4. If get_college_stats returns null shooting percentages (fg_pct, three_pct, ft_pct),
   call get_espn_college_stats as a fallback for those percentages.
5. Call web_search: '{player_name} scouting report strengths weaknesses'
6. Call web_search: '{player_name} mock draft projection'

Do not wait for scraper tools to succeed before searching
the web. Run web searches in parallel with scraper results.

CRITICAL: If web search snippets contain physical
measurements, strengths, weaknesses, or draft projections
— extract and use that information directly. Do not return
null fields when the information exists in search results.

Call get_wingspan for any player where physical.wingspan is
null after the other tools have run. Pass the player's team
as the second argument to improve search accuracy.

When shooting percentages are not found in scrapers,
search for them explicitly:
web_search: '{player_name} field goal percentage three point percentage stats 2025-26 season'

Also check search snippets for any mention of shooting
percentages — they are often mentioned in scouting articles.
Extract numbers like '39.7% on two-point field goals' or
'22.7% from three' from article text.

For current college players, also search:
'{player_name} college basketball stats 2025-26'
'{player_name} sports reference cbb'

Sports Reference CBB URL pattern for current players:
https://www.sports-reference.com/cbb/players/{firstname}-{lastname}-1.html

Try multiple URL variations if first attempt fails.
For 2025-26 freshmen, stats may be under the current season
table not career totals — check both.
After retrieving stats from any tool, verify the player matches
by checking:
1. Does the team/school match what was searched?
2. Does the position match if known?
3. Are the stats plausible for the level of play?

If the retrieved player's team does not match the search context,
discard those stats and set them to null. It is better to show
null stats than wrong stats from the wrong player.

Wrong data is worse than missing data.

Return ONLY valid JSON. No prose, no markdown fences, no other text.
Use EXACTLY this schema and these field names (do not invent your own):

{
  "player_name": string,
  "position": string | null,
  "age": integer | null,
  "team": string | null,
  "physical": {
    "height": string | null,    // e.g. "6-9" — copy from get_player_stats.height
    "weight": string | null,    // e.g. "205lb" — copy from get_player_stats.weight
    "wingspan": string | null   // from get_wingspan tool or web_search snippets; else null
  },
  "stats": {
    "pts": number | null,        // from get_player_stats.pts (per game)
    "reb": number | null,        // from get_player_stats.reb (per game)
    "ast": number | null,        // from get_player_stats.ast (per game)
    "fg_pct": number | null,     // decimal 0-1 from get_player_stats.fg_pct (e.g. 0.468, NOT 46.8)
    "three_pct": number | null,  // decimal 0-1 from get_player_stats.three_pct
    "ft_pct": number | null,     // decimal 0-1 from get_player_stats.ft_pct
    "games": integer | null,     // from get_player_stats.games
    "minutes": number | null     // from get_player_stats.minutes (per game)
  },
  "strengths": [string, ...],    // 3-7 items, each citing a specific stat or observation
  "weaknesses": [string, ...],   // 2-5 items, each citing a specific gap or concern
  "nba_comp": {
    "name": string | null,       // REQUIRED if any data exists — pick the closest current/recent NBA player
    "reasoning": string          // REQUIRED — explain WHY using specific evidence (stats, role, archetype)
  },
  "draft_projection": {
    "year": integer | null,
    "round": string | null,     // e.g. "Lottery", "Late First", "Second Round", "Undrafted"
    "notes": string             // brief explanation of why this projection tier fits
  },
  "confidence": number,          // 0.0-1.0, honest assessment of data completeness
  "confidence_notes": string,    // brief note on what's confident and what's uncertain
  "sources": [string, ...]       // URLs from tool results
}

Rules:
- Copy stat values verbatim from get_player_stats — do NOT convert percentages (keep 0.468, not 46.8)
- Copy height/weight verbatim into physical.height and physical.weight
- If a field has no data from tools, set to null (or [] for lists, "" for nba_comp.reasoning only when no data at all)
- Strengths/weaknesses must reference specific stats or observations from tools
- nba_comp must always be attempted when stats exist; null only if truly insufficient data
- Always include a draft_projection based on the data found.
  Use these tiers:
  - Lottery (top 14)
  - Late First (15-30)
  - Second Round
  - Undrafted
  - Too Early To Project for high school/freshman players.
  Base this on stats, physical profile, and any draft coverage found in web searches.
- confidence must reflect actual data completeness, not a default"""

    @staticmethod
    def _normalize_source_url(url: str) -> str:
        if "duckduckgo.com/l/" not in url or "uddg=" not in url:
            return url
        try:
            parsed = urlparse(url)
            uddg_values = parse_qs(parsed.query).get("uddg", [])
            if not uddg_values:
                return url
            decoded = unquote(uddg_values[0]).strip()
            return decoded or url
        except Exception:
            return url

    @staticmethod
    def _normalize_assistant_blocks(content_blocks: list[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for block in content_blocks:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                normalized.append({"type": "text", "text": getattr(block, "text", "")})
            elif block_type == "tool_use":
                normalized.append(
                    {
                        "type": "tool_use",
                        "id": getattr(block, "id", ""),
                        "name": getattr(block, "name", ""),
                        "input": getattr(block, "input", {}) or {},
                    }
                )
        return normalized

    @staticmethod
    def _extract_text(content_blocks: list[Any]) -> str:
        parts: list[str] = []
        for block in content_blocks:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", ""))
        return "\n".join(part for part in parts if part).strip()

    @staticmethod
    def _safe_json_parse(payload: str) -> dict[str, Any]:
        if not payload.strip():
            return {}
        try:
            parsed = json.loads(payload)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            start = payload.find("{")
            end = payload.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return {}
            try:
                parsed = json.loads(payload[start : end + 1])
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}

    @staticmethod
    def _clamp_confidence(value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, numeric))

    def _normalize_report(self, raw: dict[str, Any], player_name: str, sources: set[str]) -> dict[str, Any]:
        default = {
            "player_name": player_name,
            "position": None,
            "age": None,
            "team": None,
            "physical": {"height": None, "weight": None, "wingspan": None},
            "stats": {
                "pts": None,
                "reb": None,
                "ast": None,
                "fg_pct": None,
                "three_pct": None,
                "ft_pct": None,
                "games": None,
                "minutes": None,
            },
            "strengths": [],
            "weaknesses": [],
            "nba_comp": {"name": None, "reasoning": ""},
            "draft_projection": None,
            "confidence": 0.0,
            "confidence_notes": "Limited data available from tools.",
            "sources": [],
            "generated_at": datetime.now(UTC).isoformat(),
        }

        report = default | {k: v for k, v in raw.items() if k in default}
        report["physical"] = default["physical"] | (
            raw.get("physical", {}) if isinstance(raw.get("physical"), dict) else {}
        )
        report["stats"] = default["stats"] | (raw.get("stats", {}) if isinstance(raw.get("stats"), dict) else {})
        report["nba_comp"] = default["nba_comp"] | (
            raw.get("nba_comp", {}) if isinstance(raw.get("nba_comp"), dict) else {}
        )
        draft_projection_raw = raw.get("draft_projection")
        if isinstance(draft_projection_raw, dict):
            year_val = draft_projection_raw.get("year")
            draft_year: int | None
            if isinstance(year_val, int):
                draft_year = year_val
            elif isinstance(year_val, float):
                draft_year = int(year_val)
            elif isinstance(year_val, str):
                year_str = year_val.strip()
                draft_year = int(year_str) if year_str.isdigit() else None
            else:
                draft_year = None

            round_val = draft_projection_raw.get("round")
            draft_round = round_val if (round_val is None or isinstance(round_val, str)) else str(round_val)
            notes_val = draft_projection_raw.get("notes")
            draft_notes = notes_val if isinstance(notes_val, str) else str(notes_val or "")

            report["draft_projection"] = {"year": draft_year, "round": draft_round, "notes": draft_notes}
        report["strengths"] = [str(item) for item in raw.get("strengths", []) if isinstance(item, str)]
        report["weaknesses"] = [str(item) for item in raw.get("weaknesses", []) if isinstance(item, str)]
        report["confidence"] = self._clamp_confidence(raw.get("confidence"))

        report_sources = [str(src) for src in raw.get("sources", []) if isinstance(src, str)]
        merged_sources = list(dict.fromkeys([*report_sources, *sorted(sources)]))
        report["sources"] = merged_sources

        if not isinstance(report.get("generated_at"), str) or not report["generated_at"]:
            report["generated_at"] = datetime.now(UTC).isoformat()
        return report

    async def _run_tool(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
        try:
            if tool_name == "web_search":
                query = str(tool_input.get("query", "")).strip()
                max_results = int(tool_input.get("max_results", 5))
                self.tool_call_counts["web_search"] += 1
                self.tool_calls.append({"tool": "web_search", "query": query, "max_results": max_results})
                return await search(query=query, max_results=max_results)

            if tool_name == "get_player_stats":
                player_name = str(tool_input.get("player_name", "")).strip()
                self.tool_call_counts["get_player_stats"] += 1
                self.tool_calls.append({"tool": "get_player_stats", "player_name": player_name})
                return await get_player_stats(player_name=player_name)

            if tool_name == "get_college_stats":
                player_name = str(tool_input.get("player_name", "")).strip()
                self.tool_call_counts["get_college_stats"] += 1
                self.tool_calls.append({"tool": "get_college_stats", "player_name": player_name})
                return await get_college_stats(player_name=player_name)

            if tool_name == "get_espn_college_stats":
                player_name = str(tool_input.get("player_name", "")).strip()
                self.tool_call_counts["get_espn_college_stats"] += 1
                self.tool_calls.append({"tool": "get_espn_college_stats", "player_name": player_name})
                return await get_espn_college_stats(player_name=player_name)

            if tool_name == "get_wingspan":
                player_name = str(tool_input.get("player_name", "")).strip()
                team = str(tool_input.get("team", "")).strip()
                self.tool_call_counts["get_wingspan"] += 1
                self.tool_calls.append({"tool": "get_wingspan", "player_name": player_name, "team": team})
                return await get_wingspan(player_name=player_name, team=team)

            if tool_name == "get_euroleague_stats":
                player_name = str(tool_input.get("player_name", "")).strip()
                self.tool_call_counts["get_euroleague_stats"] += 1
                self.tool_calls.append({"tool": "get_euroleague_stats", "player_name": player_name})
                return await get_euroleague_stats(player_name=player_name)

            if tool_name == "get_fiba_profile":
                player_name = str(tool_input.get("player_name", "")).strip()
                self.tool_call_counts["get_fiba_profile"] += 1
                self.tool_calls.append({"tool": "get_fiba_profile", "player_name": player_name})
                return await get_fiba_profile(player_name=player_name)

        except Exception as exc:
            return {"error": f"Tool execution failed: {exc}"}

        return {"error": f"Unknown tool: {tool_name}"}

    async def generate_report(self, player_name: str) -> dict[str, Any]:
        player_name = player_name.strip()
        if not player_name:
            return self._normalize_report({}, "", set())

        cache_key = player_name.lower()
        if cache_key in _report_cache:
            cached = dict(_report_cache[cache_key])
            cached["cached"] = True
            return cached

        self.tool_call_counts = {
            "web_search": 0,
            "get_player_stats": 0,
            "get_college_stats": 0,
            "get_espn_college_stats": 0,
            "get_wingspan": 0,
            "get_euroleague_stats": 0,
            "get_fiba_profile": 0,
        }
        self.tool_calls = []

        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": (
                    f"Create a complete scouting report for player: {player_name}.\n"
                    "Research thoroughly with tools before concluding."
                ),
            }
        ]
        seen_sources: set[str] = set()

        final_text = ""
        for _ in range(6):
            response = await self.client.messages.create(
                model=self.MODEL,
                max_tokens=2000,
                temperature=0,
                system=self._system_prompt(),
                tools=self._tools(),
                messages=messages,
                timeout=60.0,
            )

            assistant_blocks = self._normalize_assistant_blocks(response.content)
            messages.append({"role": "assistant", "content": assistant_blocks})

            tool_uses = [block for block in response.content if getattr(block, "type", None) == "tool_use"]
            if not tool_uses:
                final_text = self._extract_text(response.content)
                break

            tool_results_content: list[dict[str, Any]] = []
            for tool_use in tool_uses:
                tool_name = getattr(tool_use, "name", "")
                tool_input = getattr(tool_use, "input", {}) or {}
                result = await self._run_tool(tool_name=tool_name, tool_input=tool_input)

                if isinstance(result, list):
                    for item in result:
                        url = item.get("url") if isinstance(item, dict) else None
                        if isinstance(url, str) and url:
                            seen_sources.add(self._normalize_source_url(url))
                elif isinstance(result, dict):
                    source_url = result.get("source_url")
                    if isinstance(source_url, str) and source_url:
                        seen_sources.add(self._normalize_source_url(source_url))

                tool_results_content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": getattr(tool_use, "id", ""),
                        "content": json.dumps(result, ensure_ascii=True),
                    }
                )

            messages.append({"role": "user", "content": tool_results_content})

        raw_report = self._safe_json_parse(final_text)
        report = self._normalize_report(raw_report, player_name, seen_sources)
        if len(_report_cache) > 50:
            _report_cache.clear()
        _report_cache[cache_key] = report
        return report
