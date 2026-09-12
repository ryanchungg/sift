"""Async Redis client helpers for auth cache and rate limiting."""

from __future__ import annotations

from typing import Optional

import redis.asyncio as redis

from app.core.config import Settings, get_settings

_redis_client: Optional[redis.Redis] = None


async def get_redis(settings: Settings | None = None) -> redis.Redis:
    """Return a singleton async Redis client."""
    global _redis_client
    if _redis_client is None:
        cfg = settings or get_settings()
        _redis_client = redis.from_url(
            cfg.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def close_redis() -> None:
    """Close the shared Redis connection on shutdown."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
