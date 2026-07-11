"""Persistent report cache backed by Supabase.

Every function degrades gracefully to a no-op when Supabase is not
configured (no SUPABASE_URL/KEY) or the client library is unavailable,
so the agent keeps working with only its in-memory cache.
"""

import os

# Guard the import so a missing/broken `supabase` package can never crash the
# whole backend at import time — the cache simply disables itself.
try:
    from supabase import create_client
except ImportError:  # pragma: no cover - package optional at runtime
    create_client = None

_client = None


def get_client():
    global _client
    if _client is None:
        if create_client is None:
            return None
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_ANON_KEY")
        if url and key:
            _client = create_client(url, key)
    return _client


async def get_cached_report(player_key: str) -> dict | None:
    client = get_client()
    if not client:
        return None
    try:
        # Select hit_count too so we can increment it correctly on each hit.
        result = (
            client.table("report_cache")
            .select("report, hit_count")
            .eq("player_key", player_key)
            .single()
            .execute()
        )
        if result.data:
            client.table("report_cache").update(
                {"hit_count": (result.data.get("hit_count") or 1) + 1}
            ).eq("player_key", player_key).execute()
            return result.data["report"]
    except Exception:
        return None


async def set_cached_report(player_key: str, report: dict) -> None:
    client = get_client()
    if not client:
        return
    try:
        client.table("report_cache").upsert(
            {
                "player_key": player_key,
                "report": report,
                "hit_count": 1,
            }
        ).execute()
    except Exception:
        pass


async def get_cache_stats() -> dict:
    """Aggregate usage metric: how many reports are cached and how many
    total API calls the cache has saved (hits beyond each report's first)."""
    empty = {"cached_players": 0, "total_hits": 0, "api_calls_saved": 0}
    client = get_client()
    if not client:
        return empty
    try:
        result = client.table("report_cache").select("hit_count").execute()
        rows = result.data or []
        cached_players = len(rows)
        total_hits = sum(int(r.get("hit_count") or 0) for r in rows)
        # Each cached report cost one real API call to generate (hit_count starts
        # at 1); every hit beyond that first generation is a saved API call.
        api_calls_saved = max(0, total_hits - cached_players)
        return {
            "cached_players": cached_players,
            "total_hits": total_hits,
            "api_calls_saved": api_calls_saved,
        }
    except Exception:
        return empty
