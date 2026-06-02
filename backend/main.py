import asyncio
from datetime import UTC, datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import time, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from agents.scout import ScoutAgent

app = FastAPI(title="NBA Scout Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class ScoutRequest(BaseModel):
    player_name: str

class CompareRequest(BaseModel):
    player_one: str
    player_two: str


recent_searches: list[dict] = []


def _record_search(player_name: str, position: str | None, team: str | None) -> None:
    """Append to recent_searches, deduplicate, keep last 20."""
    key = player_name.strip().lower()
    global recent_searches
    recent_searches = [e for e in recent_searches if e["player_name"].lower() != key]
    recent_searches.insert(0, {
        "player_name": player_name.strip(),
        "position": position or None,
        "team": team or None,
        "timestamp": datetime.now(UTC).isoformat(),
    })
    recent_searches = recent_searches[:20]


RATE_LIMIT_MAX_REQUESTS = 3
RATE_LIMIT_WINDOW_SECONDS = 3600
request_log_by_ip: dict[str, list[float]] = {}


def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    request_times = request_log_by_ip.get(ip, [])
    request_times = [t for t in request_times if now - t < RATE_LIMIT_WINDOW_SECONDS]
    if len(request_times) >= RATE_LIMIT_MAX_REQUESTS:
        request_log_by_ip[ip] = request_times
        return True
    request_times.append(now)
    request_log_by_ip[ip] = request_times
    return False


@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "ok"}

@app.get("/ping")
async def ping():
    return {"ok": True}

@app.post("/scout")
async def scout(req: ScoutRequest, request: Request):
    if not req.player_name.strip():
        raise HTTPException(status_code=400, detail="Player name required")
    client_ip = request.client.host if request.client else "unknown"
    if _is_rate_limited(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please try again later.",
        )
    start = time.time()
    try:
        agent = ScoutAgent()
        report = await agent.generate_report(req.player_name)
        report["response_time_seconds"] = round(time.time() - start, 2)
        _record_search(
            report.get("player_name") or req.player_name,
            report.get("position"),
            report.get("team"),
        )
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/compare")
async def compare(req: CompareRequest):
    if not req.player_one.strip() or not req.player_two.strip():
        raise HTTPException(status_code=400, detail="Both player names required")
    start = time.time()
    try:
        agent_one = ScoutAgent()
        agent_two = ScoutAgent()
        report_one, report_two = await asyncio.gather(
            agent_one.generate_report(req.player_one),
            agent_two.generate_report(req.player_two),
        )
        elapsed = round(time.time() - start, 2)
        _record_search(
            report_one.get("player_name") or req.player_one,
            report_one.get("position"),
            report_one.get("team"),
        )
        _record_search(
            report_two.get("player_name") or req.player_two,
            report_two.get("position"),
            report_two.get("team"),
        )
        return {
            "player_one": report_one,
            "player_two": report_two,
            "response_time_seconds": elapsed,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/recent")
async def recent():
    return recent_searches[:10]
