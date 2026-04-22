from __future__ import annotations

import asyncio
import json
import time

from agents.scout import ScoutAgent


async def main() -> None:
    agent = ScoutAgent()
    target_player = "Cooper Flagg"

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

    print("=== TIMING ===")
    print(f"Total time: {elapsed:.3f}s")


if __name__ == "__main__":
    asyncio.run(main())
