from __future__ import annotations

import asyncio
import json
import time

from agents.scout import ScoutAgent


async def main() -> None:
    agent = ScoutAgent()
    target_player = "Jordan Pope"

    start = time.perf_counter()
    report = await agent.generate_report(target_player)
    elapsed = time.perf_counter() - start

    print("=== REPORT ===")
    print(json.dumps(report, indent=2, ensure_ascii=True))
    print()

    print("=== TOOL CALL COUNTS ===")
    print(json.dumps(agent.tool_call_counts, indent=2, ensure_ascii=True))
    print(f"Total tool calls: {sum(agent.tool_call_counts.values())}")
    print()

    print("=== TOOL CALL ORDER ===")
    for idx, call in enumerate(agent.tool_calls, start=1):
        print(f"{idx}. {json.dumps(call, ensure_ascii=True)}")
    if not agent.tool_calls:
        print("No tool calls were made.")
    print()

    print("=== KEY FIELD STATUS ===")
    key_fields = {
        "player_name": report.get("player_name"),
        "position": report.get("position"),
        "age": report.get("age"),
        "team": report.get("team"),
        "physical.height": (report.get("physical") or {}).get("height"),
        "physical.weight": (report.get("physical") or {}).get("weight"),
        "physical.wingspan": (report.get("physical") or {}).get("wingspan"),
        "stats.pts": (report.get("stats") or {}).get("pts"),
        "stats.reb": (report.get("stats") or {}).get("reb"),
        "stats.ast": (report.get("stats") or {}).get("ast"),
        "stats.fg_pct": (report.get("stats") or {}).get("fg_pct"),
        "stats.three_pct": (report.get("stats") or {}).get("three_pct"),
        "stats.ft_pct": (report.get("stats") or {}).get("ft_pct"),
        "stats.games": (report.get("stats") or {}).get("games"),
        "stats.minutes": (report.get("stats") or {}).get("minutes"),
        "nba_comp.name": (report.get("nba_comp") or {}).get("name"),
        "nba_comp.reasoning": (report.get("nba_comp") or {}).get("reasoning"),
        "confidence": report.get("confidence"),
        "confidence_notes": report.get("confidence_notes"),
        "sources": report.get("sources"),
        "generated_at": report.get("generated_at"),
    }
    for field, value in key_fields.items():
        status = "has_data" if value not in (None, "", [], {}) else "null_or_empty"
        print(f"{field}: {status}")
    print()

    non_null_count = sum(1 for value in key_fields.values() if value not in (None, "", [], {}))
    total_fields = len(key_fields)
    completeness = non_null_count / total_fields if total_fields else 0.0
    print("=== DATA COMPLETENESS ===")
    print(f"{non_null_count}/{total_fields} ({completeness:.3f})")
    print()

    print("=== TIMING ===")
    print(f"Total time: {elapsed:.3f}s")


if __name__ == "__main__":
    asyncio.run(main())
