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
cd backend && pip install -r requirements.txt
cp .env.example .env  # add your ANTHROPIC_API_KEY
uvicorn main:app --reload

cd frontend && npm install && npm run dev

