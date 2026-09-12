"""Supabase client helpers for database and storage access."""

from __future__ import annotations

from typing import Optional

from supabase import AsyncClient, Client, acreate_client, create_client

from app.core.config import Settings, get_settings

_sync_client: Optional[Client] = None
_async_client: Optional[AsyncClient] = None


def _require_supabase_credentials(settings: Settings) -> tuple[str, str]:
    """Validate and return Supabase URL + key."""
    key = settings.effective_supabase_key
    if not settings.supabase_url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY (or SUPABASE_SERVICE_ROLE_KEY) "
            "must be configured"
        )
    return settings.supabase_url, key


def get_supabase_client(settings: Settings | None = None) -> Client:
    """Return a singleton sync Supabase client (useful for Celery workers)."""
    global _sync_client
    if _sync_client is None:
        url, key = _require_supabase_credentials(settings or get_settings())
        _sync_client = create_client(url, key)
    return _sync_client


async def get_async_supabase_client(
    settings: Settings | None = None,
) -> AsyncClient:
    """Return a singleton async Supabase client for FastAPI endpoints."""
    global _async_client
    if _async_client is None:
        url, key = _require_supabase_credentials(settings or get_settings())
        _async_client = await acreate_client(url, key)
    return _async_client


async def close_async_supabase_client() -> None:
    """Dispose of the async Supabase client on application shutdown."""
    global _async_client
    if _async_client is None:
        return
    # Prefer public close helpers when available across supabase-py versions.
    close = getattr(_async_client, "aclose", None)
    if callable(close):
        await close()
    else:
        postgrest = getattr(_async_client, "postgrest", None)
        if postgrest is not None:
            aclose = getattr(postgrest, "aclose", None)
            if callable(aclose):
                await aclose()
    _async_client = None
