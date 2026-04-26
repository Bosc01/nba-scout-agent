from fastapi import FastAPI, HTTPException
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

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/scout")
async def scout(req: ScoutRequest):
    if not req.player_name.strip():
        raise HTTPException(status_code=400, detail="Player name required")
    start = time.time()
    try:
        agent = ScoutAgent()
        report = await agent.generate_report(req.player_name)
        report["response_time_seconds"] = round(time.time() - start, 2)
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
