from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from tools.bbref import get_player_stats
from tools.search import search

load_dotenv()


class ScoutAgent:
    MODEL = "claude-sonnet-4-20250514"

    def __init__(self) -> None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        self.client = AsyncAnthropic(api_key=api_key)
        self.tool_call_counts: dict[str, int] = {
            "web_search": 0,
            "get_player_stats": 0,
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
        ]

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are a conservative scout. Uncertainty stated explicitly is more valuable "
            "than false confidence.\n"
            "You are generating an NBA scouting report grounded ONLY in tool outputs.\n"
            "Critical constraints:\n"
            "- Never invent numbers, stats, teams, or measurements.\n"
            "- If a stat is missing from tools, set it to null and mention the gap.\n"
            "- Confidence must reflect data quality, source reliability, and coverage.\n"
            "- Strengths/weaknesses must include evidence references from tools.\n"
            "- Include sources as concrete URLs used in reasoning.\n"
            "Final output MUST be valid JSON matching this schema:\n"
            "{"
            '"player_name": str, "position": str|null, "age": int|null, "team": str|null, '
            '"physical": {"height": str|null, "weight": str|null, "wingspan": str|null}, '
            '"stats": {"pts": number|null, "reb": number|null, "ast": number|null, '
            '"fg_pct": number|null, "three_pct": number|null, "ft_pct": number|null, '
            '"games": int|null, "minutes": number|null}, '
            '"strengths": [str], "weaknesses": [str], '
            '"nba_comp": {"name": str|null, "reasoning": str}, '
            '"confidence": number, "confidence_notes": str, '
            '"sources": [str], "generated_at": str'
            "}\n"
            "Return only JSON in the final answer."
        )

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
        except Exception as exc:
            return {"error": f"Tool execution failed: {exc}"}

        return {"error": f"Unknown tool: {tool_name}"}

    async def generate_report(self, player_name: str) -> dict[str, Any]:
        player_name = player_name.strip()
        if not player_name:
            return self._normalize_report({}, "", set())

        self.tool_call_counts = {"web_search": 0, "get_player_stats": 0}
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
        for _ in range(12):
            response = await self.client.messages.create(
                model=self.MODEL,
                max_tokens=1800,
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
