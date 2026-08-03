from __future__ import annotations

import asyncio
import difflib
import json
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from anthropic import AsyncAnthropic
from dotenv import load_dotenv

# Optional Redis layer — the agent runs fine without the package or REDIS_URL.
try:
    import redis.asyncio as redis_asyncio
except ImportError:  # pragma: no cover - package optional at runtime
    redis_asyncio = None

from db.cache import get_cached_report, set_cached_report
from tools.bbref import get_college_stats, get_espn_college_stats, get_player_stats, get_wingspan
from tools.euroleague import get_euroleague_stats
from tools.fiba import get_fiba_profile
from tools.search import search

load_dotenv(override=True)

_report_cache: dict[str, Any] = {}

# ── Redis cache layer (fast, TTL-bound, survives deploys) ────────────────────
REDIS_TTL_SECONDS = 86400  # 24 hours
_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None and redis_asyncio is not None and os.getenv("REDIS_URL"):
        try:
            _redis_client = redis_asyncio.from_url(
                os.getenv("REDIS_URL"),
                decode_responses=True,
                socket_timeout=2,
                socket_connect_timeout=2,
            )
        except Exception:
            _redis_client = None
    return _redis_client


async def _redis_get_report(redis_key: str) -> dict[str, Any] | None:
    client = _get_redis()
    if client is None:
        return None
    try:
        payload = await client.get(redis_key)
        if payload:
            parsed = json.loads(payload)
            return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None
    return None


async def _redis_set_report(redis_key: str, report: dict[str, Any]) -> None:
    client = _get_redis()
    if client is None:
        return
    try:
        await client.set(redis_key, json.dumps(report, ensure_ascii=True), ex=REDIS_TTL_SECONDS)
    except Exception:
        pass

# Validation failures across all reports this process has generated.
# Exposed via /metrics so wrong-player incidents are observable.
validation_log: list[dict[str, Any]] = []

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]

_PLAUSIBLE_STAT_RANGES: dict[str, tuple[float, float]] = {
    "pts": (0, 50),
    "reb": (0, 25),
    "ast": (0, 20),
    "fg_pct": (0, 1),
    "three_pct": (0, 1),
    "ft_pct": (0, 1),
    "fga": (0, 40),
    "fta": (0, 25),
    "games": (0, 120),
    "minutes": (0, 48),
}

_PLAUSIBLE_ADVANCED_RANGES: dict[str, tuple[float, float]] = {
    "ts_pct": (0, 1),
    "usg_pct": (0, 1),
    "bpm": (-15, 15),
    "per": (0, 40),
}

_PLACEHOLDER_TEAM_VALUES = {"unknown", "n/a", "none", "null", "tbd", "--"}

# Only sources from known basketball/sports outlets make it into a report.
_ALLOWED_SOURCE_DOMAINS = [
    "basketball-reference.com", "sports-reference.com", "espn.com",
    "nbadraft.net", "tankathon.com", "nbascoutinglive.com",
    "realgm.com", "hoopshype.com", "draftexpress.com",
    "247sports.com", "rivals.com", "on3.com", "wikipedia.org",
    "nba.com", "euroleague.net", "fiba.basketball", "proballers.com",
    "nbadraftroom.com", "draftsite.com", "thedraftreview.com",
    "si.com", "bleacherreport.com", "theathletic.com", "cbssports.com",
    "usatoday.com", "washingtonpost.com", "latimes.com", "nypost.com",
]


class ScoutAgent:
    MODEL = "claude-sonnet-4-6"
    MAX_TOOL_CALLS = 5
    NAME_MATCH_THRESHOLD = 0.8

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
        return """SPEED MODE: You have a HARD budget of 5 tool calls total.
Issue ALL FIVE tool calls AT ONCE in your FIRST response — do not
wait for any result before issuing the others; they execute in
parallel. After the results return, generate the final JSON
immediately. No second round of tool calls under any circumstances.

Default batch for college/NBA players:
1. get_player_stats
2. get_college_stats
3. web_search: '{player_name} height weight position team 2026 NBA draft'
4. web_search: '{player_name} scouting report strengths weaknesses stats 2025-26'
5. web_search: '{player_name} true shooting percentage usage rate BPM PER advanced stats'

For international pros, swap get_college_stats for
get_euroleague_stats or get_fiba_profile.

You are a conservative NBA scout generating reports grounded ONLY
in tool outputs. Never invent numbers or stats.
If the player name includes a team or school context (e.g.
'Marcus Johnson Duke'), use that context to disambiguate between
players with the same name. Search specifically for that
player at that institution and include it in your search queries.

CRITICAL: If web search snippets contain physical measurements
(including wingspan), shooting percentages, strengths, weaknesses,
or draft projections — extract and use that information directly.
Extract numbers like '39.7% on two-point field goals' or '22.7%
from three' from article text. Do not return null fields when the
information exists in search results.

Extract advanced metrics the same way: phrases like '58.4% true
shooting', 'usage rate of 24.1%', 'BPM of 4.2', or 'PER of 21.3'
become advanced.ts_pct 0.584, advanced.usg_pct 0.241,
advanced.bpm 4.2, advanced.per 21.3. Null when not found.

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
    "fga": number | null,        // from get_player_stats.fga (per game attempts, copy verbatim)
    "fta": number | null,        // from get_player_stats.fta (per game attempts, copy verbatim)
    "games": integer | null,     // from get_player_stats.games
    "minutes": number | null     // from get_player_stats.minutes (per game)
  },
  "advanced": {
    "ts_pct": number | null,     // true shooting, decimal 0-1 (e.g. 0.584, NOT 58.4)
    "usg_pct": number | null,    // usage rate, decimal 0-1 (e.g. 0.241, NOT 24.1)
    "bpm": number | null,        // box plus/minus, raw value (e.g. 4.2)
    "per": number | null         // player efficiency rating, raw value (e.g. 21.3)
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
- confidence must reflect actual data completeness, not a default
- Write like a scout talks, not like a form being filled in. Plain, direct,
  specific. Vary sentence shape — never open three list items the same way
  ('Elite...', 'Solid...', 'Strong...'). Prefer a concrete observation
  ('hit 37% from deep on nearly five attempts a game') over a generic label
  ('good shooter'). No hedging boilerplate. Use commas or periods, never
  em dashes.
- Keep the report COMPACT — it renders in a UI and long output is slow:
  - strengths: 3-4 items, each under 15 words
  - weaknesses: 2-3 items, each under 15 words
  - nba_comp.reasoning: under 35 words
  - draft_projection.notes and confidence_notes: under 20 words each
  - sources: list AT MOST the 3 most important URLs — every tool-result
    URL is merged into the report automatically, so do not repeat them"""

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
    def _is_valid_source(url: str) -> bool:
        return any(domain in url for domain in _ALLOWED_SOURCE_DOMAINS)

    @staticmethod
    def _no_em_dash(text: Any) -> Any:
        """Enforce the house style rule deterministically: prompt adherence is not guaranteed."""
        if not isinstance(text, str):
            return text
        return text.replace(" — ", ", ").replace("—", ", ")

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
                "fga": None,
                "fta": None,
                "games": None,
                "minutes": None,
            },
            "advanced": {
                "ts_pct": None,
                "usg_pct": None,
                "bpm": None,
                "per": None,
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

        report = default | {k: v for k, v in raw.items() if k in default and v is not None}
        report["physical"] = default["physical"] | (
            raw.get("physical", {}) if isinstance(raw.get("physical"), dict) else {}
        )
        report["stats"] = default["stats"] | (raw.get("stats", {}) if isinstance(raw.get("stats"), dict) else {})
        report["advanced"] = default["advanced"] | (
            raw.get("advanced", {}) if isinstance(raw.get("advanced"), dict) else {}
        )
        # Derive true shooting from scraped per-game attempts when search
        # extraction found nothing: TS% = PTS / (2 * (FGA + 0.44 * FTA)).
        if report["advanced"].get("ts_pct") is None:
            pts = report["stats"].get("pts")
            fga = report["stats"].get("fga")
            fta = report["stats"].get("fta")
            if all(isinstance(v, (int, float)) for v in (pts, fga, fta)):
                true_shot_attempts = fga + 0.44 * fta
                if true_shot_attempts > 0:
                    report["advanced"]["ts_pct"] = round(pts / (2 * true_shot_attempts), 3)
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
        report["strengths"] = [self._no_em_dash(str(item)) for item in raw.get("strengths", []) if isinstance(item, str)]
        report["weaknesses"] = [self._no_em_dash(str(item)) for item in raw.get("weaknesses", []) if isinstance(item, str)]
        report["nba_comp"]["reasoning"] = self._no_em_dash(report["nba_comp"].get("reasoning"))
        report["confidence_notes"] = self._no_em_dash(report.get("confidence_notes"))
        if isinstance(report.get("draft_projection"), dict):
            report["draft_projection"]["notes"] = self._no_em_dash(report["draft_projection"].get("notes"))
        report["confidence"] = self._clamp_confidence(raw.get("confidence"))

        report_sources = [str(src) for src in raw.get("sources", []) if isinstance(src, str)]
        merged_sources = list(dict.fromkeys([*report_sources, *sorted(sources)]))
        # Model-listed URLs get vetted too, not just tool-result URLs.
        report["sources"] = [src for src in merged_sources if self._is_valid_source(src)]

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

    @staticmethod
    async def _emit(progress_cb: ProgressCallback | None, event: dict[str, Any]) -> None:
        if progress_cb is None:
            return
        try:
            await progress_cb(event)
        except Exception:
            pass

    def _validate_report(self, report: dict[str, Any], searched_name: str) -> list[str]:
        issues: list[str] = []

        reported = str(report.get("player_name") or "").strip()
        searched = searched_name.strip()
        if reported and searched:
            ratio = difflib.SequenceMatcher(None, reported.lower(), searched.lower()).ratio()
            substring_match = reported.lower() in searched.lower() or searched.lower() in reported.lower()
            if ratio < self.NAME_MATCH_THRESHOLD and not substring_match:
                issues.append(
                    f"player_name mismatch: searched '{searched}' but report is for "
                    f"'{reported}' (similarity {ratio:.2f})"
                )

        team = report.get("team")
        if team is not None:
            team_str = str(team).strip()
            if (
                team_str.lower() in _PLACEHOLDER_TEAM_VALUES
                or len(team_str) < 3
                or not any(ch.isalpha() for ch in team_str)
            ):
                issues.append(f"implausible team value: '{team}'")

        stats = report.get("stats") or {}
        for field, (low, high) in _PLAUSIBLE_STAT_RANGES.items():
            value = stats.get(field)
            if isinstance(value, (int, float)) and not low <= value <= high:
                issues.append(f"stat out of plausible range: {field}={value} (expected {low}-{high})")

        advanced = report.get("advanced") or {}
        for field, (low, high) in _PLAUSIBLE_ADVANCED_RANGES.items():
            value = advanced.get(field)
            if isinstance(value, (int, float)) and not low <= value <= high:
                issues.append(
                    f"advanced stat out of plausible range: {field}={value} (expected {low}-{high})"
                )

        return issues

    async def _generate_once(
        self,
        player_name: str,
        progress_cb: ProgressCallback | None = None,
        validation_issues: list[str] | None = None,
    ) -> dict[str, Any]:
        self.tool_call_counts = dict.fromkeys(self.tool_call_counts, 0)
        self.tool_calls = []

        prompt = (
            f"Create a complete scouting report for player: {player_name}.\n"
            "Research thoroughly with tools before concluding."
        )
        if validation_issues:
            prompt += (
                "\n\nIMPORTANT: a previous attempt at this report failed validation:\n- "
                + "\n- ".join(validation_issues)
                + f"\nBe extremely careful to research the correct player named '{player_name}'. "
                "Verify that every team, stat, and bio field belongs to this exact player. "
                "If you cannot confirm a field belongs to this player, set it to null. "
                "Wrong data is worse than missing data."
            )

        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
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
                await self._emit(progress_cb, {"type": "phase", "label": "Writing report"})
                break

            # Enforce the hard tool budget in code, not just in the prompt.
            remaining = self.MAX_TOOL_CALLS - sum(self.tool_call_counts.values())
            to_run = tool_uses[: max(0, remaining)]

            for tool_use in to_run:
                tool_input = getattr(tool_use, "input", {}) or {}
                await self._emit(
                    progress_cb,
                    {
                        "type": "tool",
                        "tool": getattr(tool_use, "name", ""),
                        "query": tool_input.get("query"),
                    },
                )

            # Tools in the same assistant turn are independent — run them concurrently.
            results = await asyncio.gather(
                *(
                    self._run_tool(
                        tool_name=getattr(tool_use, "name", ""),
                        tool_input=getattr(tool_use, "input", {}) or {},
                    )
                    for tool_use in to_run
                )
            )

            tool_results_content: list[dict[str, Any]] = []
            for tool_use, result in zip(to_run, results):
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

            for tool_use in tool_uses[len(to_run):]:
                tool_results_content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": getattr(tool_use, "id", ""),
                        "content": json.dumps({"error": "Tool call budget exhausted."}, ensure_ascii=True),
                    }
                )

            messages.append({"role": "user", "content": tool_results_content})

            if sum(self.tool_call_counts.values()) >= self.MAX_TOOL_CALLS:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Tool call budget exhausted. Generate the final JSON report now "
                            "using only the data already gathered. Respond with ONLY the JSON object."
                        ),
                    }
                )

        raw_report = self._safe_json_parse(final_text)
        return self._normalize_report(raw_report, player_name, seen_sources)

    async def generate_report(
        self,
        player_name: str,
        progress_cb: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        player_name = player_name.strip()
        if not player_name:
            return self._normalize_report({}, "", set())

        await self._emit(progress_cb, {"type": "phase", "label": "Checking report cache"})

        # First layer: in-memory cache (fastest for repeat requests this session).
        cache_key = player_name.lower()
        if cache_key in _report_cache:
            cached = dict(_report_cache[cache_key])
            cached["cached"] = True
            return cached

        # Second layer: Redis with a 24h TTL (fast, survives deploys, stays fresh).
        redis_key = f"scout:{player_name.lower().strip()}"
        redis_report = await _redis_get_report(redis_key)
        if redis_report:
            redis_report["cached"] = True
            _report_cache[cache_key] = redis_report  # warm the in-memory layer
            return redis_report

        # Third layer: persistent Supabase cache (survives server restarts).
        player_key = player_name.lower().strip().replace(" ", "_")
        persisted = await get_cached_report(player_key)
        if persisted:
            persisted["cached"] = True
            _report_cache[cache_key] = persisted  # warm the in-memory layer
            await _redis_set_report(redis_key, persisted)  # warm the Redis layer
            return persisted

        report = await self._generate_once(player_name, progress_cb=progress_cb)

        issues = self._validate_report(report, player_name)
        if issues:
            validation_log.append(
                {
                    "player_name": player_name,
                    "issues": issues,
                    "stage": "initial",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            await self._emit(
                progress_cb,
                {"type": "phase", "label": "Validation failed, retrying with disambiguation"},
            )
            report = await self._generate_once(
                player_name, progress_cb=progress_cb, validation_issues=issues
            )
            retry_issues = self._validate_report(report, player_name)
            if retry_issues:
                validation_log.append(
                    {
                        "player_name": player_name,
                        "issues": retry_issues,
                        "stage": "after_retry",
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )

        if len(_report_cache) > 50:
            _report_cache.clear()
        _report_cache[cache_key] = report
        # Persist to Redis (24h TTL) and Supabase so the report survives
        # restarts and deploys and saves future API calls.
        await _redis_set_report(redis_key, report)
        await set_cached_report(player_key, report)
        return report
