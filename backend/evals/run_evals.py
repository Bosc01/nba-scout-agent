"""Identity eval harness: runs the live agent against a ground-truth roster
and writes a dated, reproducible scorecard.

Usage (from backend/):

    python -m evals.run_evals --limit 8

Cost note: every player is one real agent run (roughly $0.05-0.10 of
Anthropic API usage). There is no hosting cost: nothing here touches the
deployed service. Keep --limit small for casual runs.

Scoring:
- wrong_player (HARD FAIL): the reported name does not match the roster name.
- team: "match" when the reported team fuzzy-matches any known alias,
  "mismatch" when it matches none (needs human review; aliases may be stale),
  "missing" when the report has no team.
- completeness: fraction of key report fields that are non-null.
- latency and confidence are recorded per player.

Caches are force-disabled so every run exercises the live research path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import scout as scout_mod  # noqa: E402
from agents.scout import ScoutAgent  # noqa: E402

EVALS_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVALS_DIR / "results"
REPO_ROOT = EVALS_DIR.parent.parent
EVALS_MD = REPO_ROOT / "EVALS.md"

KEY_FIELDS = [
    ("player_name",), ("position",), ("age",), ("team",),
    ("physical", "height"), ("physical", "weight"), ("physical", "wingspan"),
    ("stats", "pts"), ("stats", "reb"), ("stats", "ast"),
    ("stats", "fg_pct"), ("stats", "three_pct"), ("stats", "ft_pct"),
    ("stats", "games"), ("stats", "minutes"),
    ("nba_comp", "name"), ("nba_comp", "reasoning"),
    ("confidence_notes",), ("sources",),
]


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _name_ok(expected: str, reported: str | None) -> bool:
    if not reported:
        return False
    return _ratio(expected, reported) >= 0.85


def _team_verdict(aliases: list[str], reported: str | None) -> str:
    if not reported or not str(reported).strip():
        return "missing"
    r = str(reported).lower()
    for alias in aliases:
        a = alias.lower()
        if a in r or r in a or _ratio(a, r) >= 0.6:
            return "match"
    return "mismatch"


def _completeness(report: dict) -> float:
    non_null = 0
    for path in KEY_FIELDS:
        node = report
        for key in path:
            node = (node or {}).get(key) if isinstance(node, dict) else None
        if node not in (None, "", [], {}):
            non_null += 1
    return round(non_null / len(KEY_FIELDS), 3)


def _disable_caches() -> None:
    """Evals must always exercise the live research path."""
    scout_mod._report_cache.clear()

    async def _read_nothing(*args, **kwargs):
        return None

    async def _write_nothing(*args, **kwargs):
        return None

    scout_mod.get_cached_report = _read_nothing
    scout_mod.set_cached_report = _write_nothing
    scout_mod.redis_cache.get_json = _read_nothing
    scout_mod.redis_cache.set_json = _write_nothing


async def _run_one(entry: dict) -> dict:
    name = entry["name"]
    start = time.perf_counter()
    row: dict = {"name": name}
    try:
        agent = ScoutAgent()
        report = await agent.generate_report(name)
        row["latency_s"] = round(time.perf_counter() - start, 2)
        row["reported_name"] = report.get("player_name")
        row["reported_team"] = report.get("team")
        row["season"] = report.get("season")
        row["confidence"] = report.get("confidence")
        row["completeness"] = _completeness(report)
        row["wrong_player"] = not _name_ok(name, report.get("player_name"))
        row["team"] = _team_verdict(entry["team_aliases"], report.get("team"))
        row["error"] = None
    except Exception as exc:
        row["latency_s"] = round(time.perf_counter() - start, 2)
        row["wrong_player"] = None
        row["team"] = None
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def _write_scoreboard(all_runs: list[dict]) -> None:
    latest = all_runs[-1]
    lines = [
        "# Eval Scorecard",
        "",
        "Dated, reproducible identity evals for the scout agent, run with",
        "`cd backend && python -m evals.run_evals` against the ground-truth",
        "roster in `backend/evals/roster.json`. A **wrong-player** result means",
        "the agent reported a different person than asked. A **team mismatch**",
        "is flagged for human review (roster aliases can go stale after trades).",
        "",
        "## Run history",
        "",
        "| Date (UTC) | Players | Wrong player | Team match / review / missing | Errors | Mean latency | Mean completeness |",
        "|---|---|---|---|---|---|---|",
    ]
    for run in all_runs:
        s = run["summary"]
        lines.append(
            f"| {run['date']} | {s['players']} | **{s['wrong_player']}** "
            f"| {s['team_match']} / {s['team_mismatch']} / {s['team_missing']} "
            f"| {s['errors']} | {s['mean_latency_s']}s | {s['mean_completeness']} |"
        )
    lines += [
        "",
        f"## Latest run detail ({latest['date']})",
        "",
        "| Player | Reported team | Season | Team check | Confidence | Completeness | Latency |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in latest["rows"]:
        if row.get("error"):
            lines.append(f"| {row['name']} | ERROR: {row['error']} | | | | | {row['latency_s']}s |")
            continue
        flag = " ⚠ WRONG PLAYER" if row["wrong_player"] else ""
        lines.append(
            f"| {row['name']}{flag} | {row.get('reported_team') or '--'} "
            f"| {row.get('season') or '--'} | {row['team']} | {row.get('confidence')} "
            f"| {row.get('completeness')} | {row['latency_s']}s |"
        )
    lines.append("")
    EVALS_MD.write_text("\n".join(lines))


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=8,
                        help="players to run (each costs ~$0.05-0.10 of API usage)")
    args = parser.parse_args()

    roster = json.loads((EVALS_DIR / "roster.json").read_text())
    players = roster["players"][: args.limit]

    _disable_caches()
    print(f"Running {len(players)} evals (live agent runs, caches disabled)…")

    rows: list[dict] = []
    for i, entry in enumerate(players, start=1):
        row = await _run_one(entry)
        rows.append(row)
        status = "ERROR" if row.get("error") else (
            "WRONG PLAYER" if row["wrong_player"] else f"ok/{row['team']}"
        )
        print(f"  [{i}/{len(players)}] {entry['name']:24s} {status:14s} {row['latency_s']}s")

    scored = [r for r in rows if not r.get("error")]
    summary = {
        "players": len(rows),
        "wrong_player": sum(1 for r in scored if r["wrong_player"]),
        "team_match": sum(1 for r in scored if r["team"] == "match"),
        "team_mismatch": sum(1 for r in scored if r["team"] == "mismatch"),
        "team_missing": sum(1 for r in scored if r["team"] == "missing"),
        "errors": sum(1 for r in rows if r.get("error")),
        "mean_latency_s": round(statistics.mean(r["latency_s"] for r in rows), 1) if rows else 0,
        "mean_completeness": round(
            statistics.mean(r["completeness"] for r in scored), 3
        ) if scored else 0,
    }

    run_record = {
        "date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
        "roster_verified_as_of": roster.get("verified_as_of"),
        "summary": summary,
        "rows": rows,
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M")
    (RESULTS_DIR / f"{stamp}.json").write_text(json.dumps(run_record, indent=2))

    history = []
    for path in sorted(RESULTS_DIR.glob("*.json")):
        try:
            history.append(json.loads(path.read_text()))
        except Exception:
            continue
    _write_scoreboard(history)

    print(f"\nSummary: {json.dumps(summary)}")
    print(f"Scorecard written to {EVALS_MD}")
    return 1 if (summary["wrong_player"] or summary["errors"]) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
