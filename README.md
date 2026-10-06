# NBA Scout Agent

Scouting reports for college and international basketball prospects. Type a
player's name and an agent built on Claude researches them across six sources
and writes a report with stats, strengths and weaknesses backed by evidence,
an NBA comparison, a confidence score, and a citation for every claim.

## Why

Thousands of college and international players never get a real look from a
professional scout, because scouting is expensive and human attention runs
out. The data on most of them already exists. Nobody has the time to pull it
together.

## How it works

The agent runs a tool-use loop instead of a single prompt. It decides which
source to check next based on what it has found so far, so a Euroleague
player and a freshman at Duke take different paths through the tools:

| Source | Used for |
|---|---|
| Basketball Reference | Bio and recent per-game stats |
| Sports Reference (college) | NCAA stats |
| ESPN | Fallback when college shooting splits are missing |
| Euroleague | European club stats |
| FIBA | International player profiles |
| Web search | Wingspan and context the stat sites do not carry |

Reports stream to the browser as the agent works, so the user watches each
phase instead of staring at a spinner. Finished reports are cached in three
layers: in memory for repeat requests, Redis across instances, and Supabase
for persistence.

## How I know it works

The hardest failure for a scouting agent is reporting the wrong person: two
players with similar names, or a twin. `backend/evals` runs the live agent
against a ground-truth roster and writes a dated scorecard to `EVALS.md`. The
first run, on 8 players including the Boozer twins:

| Wrong player | Team matches | Flagged for review | Mean completeness | Mean latency |
|---|---|---|---|---|
| **0** | 7 of 8 | 1 | 0.855 | 35.6 s |

The one flag was a team the roster did not expect, which is exactly what the
review step is for: rosters go stale when players transfer or turn pro.

The confidence score is deliberately conservative. A report that says "I am
not sure about this" is more useful to a scout than one that sounds certain
and is wrong, so confidence tracks how complete the data actually is.

## Security

Every scraper request goes through `tools/urlguard.py`. Hostnames must match
an explicit allowlist (exact or dot-suffix match, never a substring check),
literal IP addresses are rejected, and redirects are followed by hand with
each hop re-checked. A naive `"espn.com" in url` check would let a crafted
URL reach internal addresses, so the guard exists to stop that.

## Design decisions

- **Tool use over one big prompt.** The agent changes its research plan based
  on what data exists for a given player. A fixed prompt cannot do that.
- **Agent over XGBoost.** A trained model would give one static number. For
  this use case, a report a scout can read and check matters more than a
  slightly better accuracy figure.
- **Honest confidence.** Uncertainty stated plainly beats false confidence.

## Stack

Python, FastAPI, Claude API (tool use), React, Tailwind, Redis, Supabase,
deployed on Railway.

## Local setup

Backend:

    cd backend && pip install -r requirements.txt
    cp .env.example .env  # add your ANTHROPIC_API_KEY
    uvicorn main:app --reload

Frontend:

    cd frontend && npm install && npm run dev

## Configuration

- `VITE_API_URL` is the backend URL the frontend calls. It defaults to
  `http://localhost:8000` for local development. Production builds must set
  it to the deployed API origin, or every request will point at localhost.
- Backend environment variables are documented in `backend/.env.example`.
  Everything except `ANTHROPIC_API_KEY` is optional; each feature turns into a
  no-op when its variable is missing.

## Database migrations

SQL migrations live in `backend/db/migrations/`, ordered by prefix. Run them
once in the Supabase SQL editor before enabling the report cache and search
history:

    backend/db/migrations/000_report_cache.sql
    backend/db/migrations/001_search_history.sql

## Evals

    cd backend && python -m evals.run_evals --limit 8

Each player is one real Anthropic API call (roughly $0.05 to $0.10), so the
GitHub Actions `Evals` workflow is manual-trigger only and needs the
`ANTHROPIC_API_KEY` repository secret. The evals never touch the deployed
service.

## Tests

    cd backend && pip install -r requirements-dev.txt
    python -m pytest tests/ -q     # 43 tests
    ruff check .

CI runs ruff, the 43 tests, and the frontend build on every push and pull
request.
