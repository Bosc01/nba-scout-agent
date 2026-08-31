"""Shared Redis client and helpers.

Every function degrades to a no-op (or returns None) when the redis package
or REDIS_URL is missing, mirroring the Supabase modules' contract.
"""

from __future__ import annotations

import json
import os
from typing import Any

try:
    import redis.asyncio as redis_asyncio
except ImportError:  # pragma: no cover - package optional at runtime
    redis_asyncio = None

_client = None


def get_redis():
    global _client
    if _client is None and redis_asyncio is not None and os.getenv("REDIS_URL"):
        try:
            _client = redis_asyncio.from_url(
                os.getenv("REDIS_URL"),
                decode_responses=True,
                socket_timeout=2,
                socket_connect_timeout=2,
            )
        except Exception:
            _client = None
    return _client


async def get_json(key: str) -> dict[str, Any] | None:
    client = get_redis()
    if client is None:
        return None
    try:
        payload = await client.get(key)
        if payload:
            parsed = json.loads(payload)
            return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None
    return None


async def set_json(key: str, value: dict[str, Any], ttl_seconds: int) -> None:
    client = get_redis()
    if client is None:
        return
    try:
        await client.set(key, json.dumps(value, ensure_ascii=True), ex=ttl_seconds)
    except Exception:
        pass


async def get_text(key: str) -> str | None:
    client = get_redis()
    if client is None:
        return None
    try:
        return await client.get(key)
    except Exception:
        return None


async def set_text(key: str, value: str, ttl_seconds: int) -> None:
    client = get_redis()
    if client is None:
        return
    try:
        await client.set(key, value, ex=ttl_seconds)
    except Exception:
        pass


async def incr_with_window(key: str, window_seconds: int) -> int | None:
    """Fixed-window counter. Returns the count, or None when Redis is absent."""
    client = get_redis()
    if client is None:
        return None
    try:
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window_seconds)
        return int(count)
    except Exception:
        return None
