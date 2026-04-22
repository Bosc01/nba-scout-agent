from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agents.scout import ScoutAgent

app = FastAPI(title="NBA Scout Agent API")
agent = ScoutAgent()


class ScoutRequest(BaseModel):
    player_name: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "model": ScoutAgent.MODEL}


@app.post("/scout")
async def scout(request: ScoutRequest) -> dict[str, Any]:
    player_name = request.player_name.strip()
    if not player_name:
        raise HTTPException(status_code=400, detail="player_name must not be empty")

    start = time.perf_counter()
    try:
        report = await agent.generate_report(player_name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ScoutAgent failed: {exc}") from exc

    elapsed = time.perf_counter() - start
    return {**report, "response_time_seconds": round(elapsed, 3)}
