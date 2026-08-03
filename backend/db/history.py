"""Search history persisted to Supabase.

Same degradation contract as db.cache: every function is a no-op (or returns
None) when Supabase is not configured, so local dev keeps working on the
in-memory fallback in main.py.
"""

from db.cache import get_client


async def record_search(
    player_name: str,
    position: str | None,
    team: str | None,
    confidence: float | None,
    response_time: float | None,
) -> None:
    client = get_client()
    if not client:
        return
    try:
        client.table("search_history").insert(
            {
                "player_name": player_name,
                "position": position,
                "team": team,
                "confidence": confidence,
                "response_time": response_time,
            }
        ).execute()
    except Exception:
        pass


async def get_recent_searches(limit: int = 10) -> list[dict] | None:
    """Latest search per player, newest first. None means Supabase unavailable."""
    client = get_client()
    if not client:
        return None
    try:
        result = (
            client.table("search_history")
            .select("player_name, position, team, created_at")
            .order("created_at", desc=True)
            .limit(limit * 5)  # overfetch so dedup by player still fills the list
            .execute()
        )
        rows = result.data or []
        seen: set[str] = set()
        deduped: list[dict] = []
        for row in rows:
            key = str(row.get("player_name", "")).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(
                {
                    "player_name": row.get("player_name"),
                    "position": row.get("position"),
                    "team": row.get("team"),
                    "timestamp": row.get("created_at"),
                }
            )
            if len(deduped) >= limit:
                break
        return deduped
    except Exception:
        return None
