import asyncio
from datetime import UTC, datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from uuid import uuid4
import time, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from agents.scout import ScoutAgent
from db.cache import get_cache_stats

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

# In-memory job store for async /scout processing.
# Each entry is one of:
#   {"status": "processing"}
#   {"status": "complete", "report": {...}}
#   {"status": "error", "detail": "..."}
jobs: dict = {}
# Hold strong references to in-flight tasks so they aren't garbage-collected.
_background_tasks: set = set()


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

async def _run_scout_job(job_id: str, player_name: str) -> None:
    """Run the scout agent in the background and store the result in `jobs`."""
    start = time.time()
    try:
        agent = ScoutAgent()
        report = await agent.generate_report(player_name)
        report["response_time_seconds"] = round(time.time() - start, 2)
        _record_search(
            report.get("player_name") or player_name,
            report.get("position"),
            report.get("team"),
        )
        jobs[job_id] = {"status": "complete", "report": report}
    except Exception as e:
        jobs[job_id] = {"status": "error", "detail": str(e)}


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

    job_id = str(uuid4())
    jobs[job_id] = {"status": "processing"}

    # Keep the in-memory job store bounded (drop oldest, keep the latest 50).
    if len(jobs) > 100:
        for stale_key in list(jobs.keys())[:-50]:
            jobs.pop(stale_key, None)

    # Run the agent concurrently and return immediately so the request itself
    # never blocks past Render's 30s limit — the client polls /scout/{job_id}.
    task = asyncio.create_task(_run_scout_job(job_id, req.player_name))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {"job_id": job_id, "status": "processing"}


@app.get("/scout/{job_id}")
async def scout_status(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


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


@app.get("/cache/stats")
async def cache_stats():
    """Persistent cache usage — a real cost-savings metric.

    Returns the number of cached players, total cache hits, and how many
    Claude API calls were avoided by serving from the cache.
    """
    return await get_cache_stats()
