# NBA Scout Agent

AI-powered scouting reports for college and international basketball 
prospects.

## Problem
Thousands of college and international players never get evaluated by 
professional scouts because scouting is expensive and human attention 
is finite. The data exists — the synthesis does not.

## What it does
Type a player name. Get a complete scouting report in under 30 seconds:
- Per-game stats from Basketball Reference
- Strengths and weaknesses with specific evidence  
- NBA comparison with reasoning
- Confidence score based on data quality
- All sources cited

## How it works
A multi-step AI agent built on Claude. The agent decides which tools 
to call, in what order, based on what it finds. It runs a reasoning 
loop — not a single prompt — synthesizing data from multiple sources 
into a structured report.

## Stack
Python, FastAPI, Claude API (tool use), React, Tailwind, Railway

## Key technical decisions
- Claude tool use over single-shot prompting: agent adapts its 
  research strategy based on what data is available
- Conservative confidence scoring: uncertainty stated explicitly 
  is more valuable than false confidence
- XGBoost rejected in favor of agent architecture: interpretability 
  and adaptability matter more than static model accuracy for 
  this use case

## Local setup

Backend:

    cd backend && pip install -r requirements.txt
    cp .env.example .env  # add your ANTHROPIC_API_KEY
    uvicorn main:app --reload

Frontend:

    cd frontend && npm install && npm run dev

## Configuration

- `VITE_API_URL` — the backend URL the frontend calls. Defaults to
  `http://localhost:8000` for local dev; production builds must set it
  to the deployed API origin (for example in the host's build settings)
  or every request will point at localhost.
- Backend environment variables are documented in `backend/.env.example`.
  All of them except `ANTHROPIC_API_KEY` are optional; each feature
  degrades to a no-op when its variable is missing.

## Database migrations

SQL migrations live in `backend/db/migrations/`, ordered by prefix.
Run them once in the Supabase SQL editor before enabling the report
cache and search history:

    backend/db/migrations/000_report_cache.sql
    backend/db/migrations/001_search_history.sql

## Tests

    cd backend && pip install -r requirements-dev.txt
    python -m pytest tests/ -q
    ruff check .

CI (GitHub Actions) runs ruff, pytest, and the frontend build on every
push and pull request.

