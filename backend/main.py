import asyncio
import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, constr

sys.path.insert(0, os.path.dirname(__file__))
from agents.scout import ScoutAgent, validation_log
from db import redis_cache
from db.cache import get_cache_stats
from db.history import get_recent_searches, record_search

# ── Input constraints ────────────────────────────────────────────────────────
# Unbounded player_name reached the model prompt, scraper query strings, and
# cache keys verbatim. Length-capped, whitespace-stripped, and screened for
# URL/injection characters while still allowing accented international names.
PLAYER_NAME_MAX = 80
PlayerName = constr(strip_whitespace=True, min_length=1, max_length=PLAYER_NAME_MAX)
_FORBIDDEN_NAME_CHARS = re.compile(r"[<>{}\[\]\\|^~`$%&#@!?;:/=+*\"()\x00-\x1f]")


def _clean_player_name(raw: str, field: str = "player_name") -> str:
    name = (raw or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail=f"{field} required")
    if len(name) > PLAYER_NAME_MAX:
        raise HTTPException(
            status_code=400, detail=f"{field} too long (max {PLAYER_NAME_MAX} characters)"
        )
    if _FORBIDDEN_NAME_CHARS.search(name):
        raise HTTPException(status_code=400, detail=f"{field} contains unsupported characters")
    return name

app = FastAPI(title="NBA Scout Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Analytics (PostHog) ──────────────────────────────────────────────────────
# No-op when POSTHOG_API_KEY is not set, so local dev works without a key.
posthog_client = None
if os.getenv("POSTHOG_API_KEY"):
    try:
        from posthog import Posthog

        posthog_client = Posthog(
            project_api_key=os.getenv("POSTHOG_API_KEY"),
            host=os.getenv("POSTHOG_HOST", "https://us.i.posthog.com"),
        )
    except Exception:
        posthog_client = None


def _field_completeness(report: dict) -> float:
    """Fraction of key report fields that came back non-null."""
    physical = report.get("physical") or {}
    stats = report.get("stats") or {}
    nba_comp = report.get("nba_comp") or {}
    values = [
        report.get("player_name"),
        report.get("position"),
        report.get("age"),
        report.get("team"),
        physical.get("height"),
        physical.get("weight"),
        physical.get("wingspan"),
        stats.get("pts"),
        stats.get("reb"),
        stats.get("ast"),
        stats.get("fg_pct"),
        stats.get("three_pct"),
        stats.get("ft_pct"),
        stats.get("games"),
        stats.get("minutes"),
        nba_comp.get("name"),
        nba_comp.get("reasoning"),
        report.get("confidence"),
        report.get("confidence_notes"),
        report.get("sources"),
    ]
    non_null = sum(1 for v in values if v not in (None, "", [], {}))
    return round(non_null / len(values), 3)


# Raw client IPs are personal data; PostHog gets a salted hash that still
# distinguishes users without storing the address itself.
_IP_HASH_SALT = os.getenv("POSTHOG_IP_SALT", "nbascout-ip-salt")


def _hashed_distinct_id(client_ip: str) -> str:
    return hashlib.sha256(f"{_IP_HASH_SALT}:{client_ip}".encode()).hexdigest()[:16]


def _track_report(client_ip: str, player_name: str, elapsed: float, report: dict, endpoint: str) -> None:
    if posthog_client is None:
        return
    try:
        posthog_client.capture(
            distinct_id=_hashed_distinct_id(client_ip or "anonymous"),
            event="report_generated",
            properties={
                "player_name": player_name,
                "response_time": elapsed,
                "confidence": report.get("confidence"),
                "field_completeness": _field_completeness(report),
                "endpoint": endpoint,
                "cached": bool(report.get("cached")),
            },
        )
    except Exception:
        pass


# ── Uptime / request metrics ─────────────────────────────────────────────────
SERVER_STARTED_AT = datetime.now(UTC)
# Counts scouting work only (scout/compare); health checks and input errors excluded.
request_metrics = {"total": 0, "success": 0, "failed": 0}


class ScoutRequest(BaseModel):
    player_name: PlayerName
    team_context: PlayerName | None = None

class CompareRequest(BaseModel):
    player_one: PlayerName
    player_two: PlayerName


recent_searches: list[dict] = []

# In-memory job store for async /scout processing.
# Each entry is one of:
#   {"status": "processing"}
#   {"status": "complete", "report": {...}}
#   {"status": "error", "detail": "..."}
jobs: dict = {}
# Hold strong references to in-flight tasks so they aren't garbage-collected.
_background_tasks: set = set()


def _record_search(
    player_name: str,
    position: str | None,
    team: str | None,
    confidence: float | None = None,
    response_time: float | None = None,
) -> None:
    """Record in memory (fallback) and persist to Supabase search_history."""
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

    # Fire-and-forget: persistence must never slow down or fail a request.
    task = asyncio.create_task(
        record_search(player_name.strip(), position, team, confidence, response_time)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


RATE_LIMIT_MAX_REQUESTS = 3
RATE_LIMIT_WINDOW_SECONDS = 3600
request_log_by_ip: dict[str, list[float]] = {}


async def _is_rate_limited(ip: str) -> bool:
    # Redis-backed when available, so the budget survives deploys and is
    # shared across replicas; in-memory sliding window otherwise.
    count = await redis_cache.incr_with_window(
        f"ratelimit:{ip}", RATE_LIMIT_WINDOW_SECONDS
    )
    if count is not None:
        return count > RATE_LIMIT_MAX_REQUESTS

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


@app.get("/metrics")
async def metrics():
    total = request_metrics["total"]
    uptime_pct = round(request_metrics["success"] / total * 100, 2) if total else 100.0
    now = datetime.now(UTC)
    return {
        "uptime_start": SERVER_STARTED_AT.isoformat(),
        "uptime_seconds": round((now - SERVER_STARTED_AT).total_seconds(), 1),
        "total_requests": total,
        "successful_requests": request_metrics["success"],
        "failed_requests": request_metrics["failed"],
        "uptime_pct": uptime_pct,
        "validation_failures": len(validation_log),
    }


async def _run_scout_job(
    job_id: str, player_name: str, client_ip: str, team_context: str | None = None
) -> None:
    """Run the scout agent in the background and store the result in `jobs`."""
    start = time.time()
    try:
        agent = ScoutAgent()
        report = await agent.generate_report(player_name, team_context=team_context)
        elapsed = round(time.time() - start, 2)
        report["response_time_seconds"] = elapsed
        _record_search(
            report.get("player_name") or player_name,
            report.get("position"),
            report.get("team"),
            report.get("confidence"),
            elapsed,
        )
        request_metrics["success"] += 1
        _track_report(client_ip, player_name, elapsed, report, "/scout")
        jobs[job_id] = {"status": "complete", "report": report}
    except Exception as e:
        request_metrics["failed"] += 1
        jobs[job_id] = {"status": "error", "detail": str(e)}


@app.post("/scout")
async def scout(req: ScoutRequest, request: Request):
    player_name = _clean_player_name(req.player_name)
    team_context = _clean_player_name(req.team_context, "team_context") if req.team_context else None
    client_ip = request.client.host if request.client else "unknown"
    if await _is_rate_limited(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please try again later.",
        )

    request_metrics["total"] += 1
    job_id = str(uuid4())
    jobs[job_id] = {"status": "processing"}

    # Keep the in-memory job store bounded (drop oldest, keep the latest 50).
    if len(jobs) > 100:
        for stale_key in list(jobs.keys())[:-50]:
            jobs.pop(stale_key, None)

    # Run the agent concurrently and return immediately so the request itself
    # never blocks past Render's 30s limit — the client polls /scout/{job_id}.
    task = asyncio.create_task(_run_scout_job(job_id, player_name, client_ip, team_context))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {"job_id": job_id, "status": "processing"}


async def _scout_stream_response(player_name: str, request: Request, team_context: str | None = None):
    """Stream agent progress as Server-Sent Events, ending with the full report."""
    player_name = _clean_player_name(player_name)
    team_context = _clean_player_name(team_context, "team_context") if team_context else None
    client_ip = request.client.host if request.client else "unknown"
    if await _is_rate_limited(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please try again later.",
        )
    request_metrics["total"] += 1
    start = time.time()
    queue: asyncio.Queue = asyncio.Queue()

    async def progress_cb(event: dict) -> None:
        await queue.put(event)

    async def run() -> None:
        try:
            agent = ScoutAgent()
            report = await agent.generate_report(
                player_name, progress_cb=progress_cb, team_context=team_context
            )
            elapsed = round(time.time() - start, 2)
            report["response_time_seconds"] = elapsed
            _record_search(
                report.get("player_name") or player_name,
                report.get("position"),
                report.get("team"),
                report.get("confidence"),
                elapsed,
            )
            request_metrics["success"] += 1
            _track_report(client_ip, player_name, elapsed, report, "/scout/stream")
            await queue.put({"type": "report", "report": report})
        except Exception as e:
            request_metrics["failed"] += 1
            await queue.put({"type": "error", "detail": str(e)})
        finally:
            await queue.put(None)

    async def event_stream():
        task = asyncio.create_task(run())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/scout/stream")
async def scout_stream(req: ScoutRequest, request: Request):
    return await _scout_stream_response(req.player_name, request, req.team_context)


# GET variant: EventSource and curl both speak GET with a query param.
# Declared before /scout/{job_id} so "stream" never matches as a job id.
@app.get("/scout/stream")
async def scout_stream_get(player_name: str, request: Request, team_context: str | None = None):
    return await _scout_stream_response(player_name, request, team_context)


@app.get("/scout/{job_id}")
async def scout_status(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/compare")
async def compare(req: CompareRequest, request: Request):
    player_one = _clean_player_name(req.player_one, "player_one")
    player_two = _clean_player_name(req.player_two, "player_two")
    client_ip = request.client.host if request.client else "unknown"
    # Same limiter as /scout: this endpoint runs TWO full agents per call and
    # was previously an unbounded Claude and scrape amplifier.
    if await _is_rate_limited(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please try again later.",
        )
    request_metrics["total"] += 1
    start = time.time()
    try:
        agent_one = ScoutAgent()
        agent_two = ScoutAgent()
        report_one, report_two = await asyncio.gather(
            agent_one.generate_report(player_one),
            agent_two.generate_report(player_two),
        )
        elapsed = round(time.time() - start, 2)
        _record_search(
            report_one.get("player_name") or player_one,
            report_one.get("position"),
            report_one.get("team"),
            report_one.get("confidence"),
            elapsed,
        )
        _record_search(
            report_two.get("player_name") or player_two,
            report_two.get("position"),
            report_two.get("team"),
            report_two.get("confidence"),
            elapsed,
        )
        request_metrics["success"] += 1
        _track_report(client_ip, player_one, elapsed, report_one, "/compare")
        _track_report(client_ip, player_two, elapsed, report_two, "/compare")
        return {
            "player_one": report_one,
            "player_two": report_two,
            "response_time_seconds": elapsed,
        }
    except Exception as e:
        request_metrics["failed"] += 1
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/recent")
async def recent():
    # Supabase history survives restarts and deploys; memory is the fallback.
    persisted = await get_recent_searches(10)
    if persisted is not None:
        return persisted
    return recent_searches[:10]


@app.get("/cache/stats")
async def cache_stats():
    """Persistent cache usage — a real cost-savings metric.

    Returns the number of cached players, total cache hits, and how many
    Claude API calls were avoided by serving from the cache.
    """
    return await get_cache_stats()
