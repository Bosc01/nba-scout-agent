from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from tools.bbref import get_college_stats, get_player_stats
from tools.euroleague import get_euroleague_stats
from tools.fiba import get_fiba_profile
from tools.search import search

load_dotenv(override=True)


class ScoutAgent:
    MODEL = "claude-sonnet-4-20250514"

    def __init__(self) -> None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        self.client = AsyncAnthropic(api_key=api_key)
        self.tool_call_counts: dict[str, int] = {
            "web_search": 0,
            "get_player_stats": 0,
            "get_college_stats": 0,
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
        return """You are a conservative NBA scout generating reports grounded ONLY
in tool outputs. Never invent numbers or stats.

Research order:
1. Call get_player_stats (NBA/pro)
2. Call get_college_stats (college)
3. Call get_euroleague_stats (international pro)
4. Call get_fiba_profile (international)
5. Use web_search for anything still missing
Try ALL sources before concluding data is unavailable.
For each source that returns data, merge into the report.
Use the highest quality data found across all sources.

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
    "wingspan": string | null   // only if surfaced by web_search; else null
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
- confidence must reflect actual data completeness, not a default"""

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

        self.tool_call_counts = {
            "web_search": 0,
            "get_player_stats": 0,
            "get_college_stats": 0,
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
        for _ in range(15):
            response = await self.client.messages.create(
                model=self.MODEL,
                max_tokens=4000,
                temperature=0,
                system=self._system_prompt(),
                tools=self._tools(),
                messages=messages,
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
                            seen_sources.add(url)
                elif isinstance(result, dict):
                    source_url = result.get("source_url")
                    if isinstance(source_url, str) and source_url:
                        seen_sources.add(source_url)

                tool_results_content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": getattr(tool_use, "id", ""),
                        "content": json.dumps(result, ensure_ascii=True),
                    }
                )

            messages.append({"role": "user", "content": tool_results_content})

        raw_report = self._safe_json_parse(final_text)
        return self._normalize_report(raw_report, player_name, seen_sources)
