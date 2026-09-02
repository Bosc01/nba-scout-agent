# Eval Scorecard

Dated, reproducible identity evals for the scout agent, run with
`cd backend && python -m evals.run_evals` against the ground-truth
roster in `backend/evals/roster.json`. A **wrong-player** result means
the agent reported a different person than asked. A **team mismatch**
is flagged for human review (roster aliases can go stale after trades).

## Run history

| Date (UTC) | Players | Wrong player | Team match / review / missing | Errors | Mean latency | Mean completeness |
|---|---|---|---|---|---|---|
| 2026-09-02 08:35 | 8 | **0** | 7 / 1 / 0 | 0 | 35.6s | 0.855 |

## Latest run detail (2026-09-02 08:35)

| Player | Reported team | Season | Team check | Confidence | Completeness | Latency |
|---|---|---|---|---|---|---|
| Jordan Pope | Oregon State | -- | match | 0.15 | 0.263 | 37.11s |
| Cameron Boozer | Duke Blue Devils | 2025-26 | match | 0.62 | 0.842 | 70.87s |
| Cayden Boozer | Duke Blue Devils | 2025-26 | match | 0.62 | 0.947 | 28.25s |
| AJ Dybantsa | BYU | 2025-26 | match | 0.85 | 1.0 | 30.97s |
| Darryn Peterson | Kansas Jayhawks | 2025-26 | match | 0.72 | 0.947 | 30.13s |
| Nate Ament | Tennessee | 2025-26 | match | 0.72 | 1.0 | 29.69s |
| Braden Smith | Indiana Pacers (Two-Way) / Noblesville Boom (G League) | 2025-26 | mismatch | 0.62 | 0.947 | 29.59s |
| Xaivian Lee | Florida (most recent college); committed to Gonzaga for 2026-27 | 2025-26 | match | 0.52 | 0.895 | 28.14s |
