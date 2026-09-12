"""API key authentication and Redis sliding-window rate limiting."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from fastapi import status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.core.config import get_settings
from app.core.database import get_async_supabase_client
from app.core.redis import get_redis

API_KEY_HEADER = "X-API-Key"
API_KEY_PREFIX_LENGTH = 8
API_KEY_CACHE_TTL_SECONDS = 300
API_KEY_CACHE_PREFIX = "apikey:v1:"
RATE_LIMIT_KEY_PREFIX = "ratelimit:rpm:"
RATE_LIMIT_WINDOW_SECONDS = 60

PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/openapi.json",
    }
)


@dataclass(slots=True)
class CurrentClient:
    """Authenticated client context attached to ``request.state.current_client``."""

    client_id: str
    api_key_id: str
    key_prefix: str
    rate_limit_rpm: int
    name: str | None = None
    email: str | None = None

    def to_cache_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_cache_dict(cls, data: dict[str, Any]) -> CurrentClient:
        return cls(
            client_id=str(data["client_id"]),
            api_key_id=str(data["api_key_id"]),
            key_prefix=str(data["key_prefix"]),
            rate_limit_rpm=int(data["rate_limit_rpm"]),
            name=data.get("name"),
            email=data.get("email"),
        )


def hash_api_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest of a raw API key (never store plaintext)."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def extract_key_prefix(raw_key: str) -> str:
    """Return the lookup prefix stored alongside ``key_hash``."""
    return raw_key[:API_KEY_PREFIX_LENGTH]


def _is_public_path(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    if path.endswith("/") and path.rstrip("/") in PUBLIC_PATHS:
        return True
    return False


def _error_response(
    status_code: int,
    detail: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail},
        headers=headers,
    )


async def _load_client_from_cache(key_hash: str) -> CurrentClient | None:
    redis_client = await get_redis()
    cached = await redis_client.get(f"{API_KEY_CACHE_PREFIX}{key_hash}")
    if not cached:
        return None
    try:
        payload = json.loads(cached)
    except json.JSONDecodeError:
        await redis_client.delete(f"{API_KEY_CACHE_PREFIX}{key_hash}")
        return None
    if not payload.get("is_active", True):
        return None
    if "client_id" not in payload or "api_key_id" not in payload:
        return None
    return CurrentClient.from_cache_dict(payload)


async def _cache_client(
    key_hash: str,
    client: CurrentClient,
    *,
    is_active: bool = True,
) -> None:
    redis_client = await get_redis()
    payload = client.to_cache_dict()
    payload["is_active"] = is_active
    await redis_client.set(
        f"{API_KEY_CACHE_PREFIX}{key_hash}",
        json.dumps(payload),
        ex=API_KEY_CACHE_TTL_SECONDS,
    )


async def _load_client_from_supabase(raw_key: str, key_hash: str) -> CurrentClient | None:
    """Look up an active API key in Supabase and join client profile fields."""
    prefix = extract_key_prefix(raw_key)
    supabase = await get_async_supabase_client()

    result = (
        await supabase.table("api_keys")
        .select(
            "id, client_id, key_hash, key_prefix, rate_limit_rpm, is_active, "
            "clients(id, name, email)"
        )
        .eq("key_prefix", prefix)
        .eq("key_hash", key_hash)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )

    rows: Iterable[dict[str, Any]] = result.data or []
    row = next(iter(rows), None)
    if row is None:
        return None

    clients = row.get("clients") or {}
    if isinstance(clients, list):
        clients = clients[0] if clients else {}

    return CurrentClient(
        client_id=str(row["client_id"]),
        api_key_id=str(row["id"]),
        key_prefix=str(row["key_prefix"]),
        rate_limit_rpm=int(row.get("rate_limit_rpm") or 60),
        name=clients.get("name"),
        email=clients.get("email"),
    )


async def resolve_api_key(raw_key: str) -> CurrentClient | None:
    """Validate ``raw_key`` via Redis cache, falling back to Supabase."""
    key_hash = hash_api_key(raw_key)
    cached = await _load_client_from_cache(key_hash)
    if cached is not None:
        return cached

    client = await _load_client_from_supabase(raw_key, key_hash)
    if client is None:
        redis_client = await get_redis()
        await redis_client.set(
            f"{API_KEY_CACHE_PREFIX}{key_hash}",
            json.dumps({"is_active": False}),
            ex=60,
        )
        return None

    await _cache_client(key_hash, client, is_active=True)
    return client


async def enforce_sliding_window_rpm(client: CurrentClient) -> tuple[bool, int, int]:
    """Apply a Redis sorted-set sliding window for requests-per-minute.

    Returns ``(allowed, remaining, retry_after_seconds)``.
    RPM comes from ``api_keys.rate_limit_rpm`` (SPEC). Token/minute (TPM)
    limits can be layered later once usage metering is live.
    """
    limit = max(int(client.rate_limit_rpm), 1)
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS
    redis_key = f"{RATE_LIMIT_KEY_PREFIX}{client.api_key_id}"
    member = f"{now:.6f}:{uuid.uuid4().hex}"

    redis_client = await get_redis()
    pipe = redis_client.pipeline()
    pipe.zremrangebyscore(redis_key, 0, window_start)
    pipe.zcard(redis_key)
    results = await pipe.execute()
    prior_count = int(results[1] or 0)

    if prior_count >= limit:
        oldest = await redis_client.zrange(redis_key, 0, 0, withscores=True)
        if oldest:
            retry_after = max(
                1,
                int(oldest[0][1] + RATE_LIMIT_WINDOW_SECONDS - now) + 1,
            )
        else:
            retry_after = 1
        return False, 0, retry_after

    pipe = redis_client.pipeline()
    pipe.zadd(redis_key, {member: now})
    pipe.expire(redis_key, RATE_LIMIT_WINDOW_SECONDS + 1)
    await pipe.execute()

    remaining = max(0, limit - (prior_count + 1))
    return True, remaining, 0


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate ``X-API-Key``, rate-limit, and set ``request.state.current_client``."""

    def __init__(self, app: ASGIApp, public_paths: Iterable[str] | None = None) -> None:
        super().__init__(app)
        self._extra_public = frozenset(public_paths or ())

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        path = request.url.path
        if (
            request.method == "OPTIONS"
            or _is_public_path(path)
            or path in self._extra_public
        ):
            return await call_next(request)

        settings = get_settings()
        if not path.startswith(settings.api_v1_prefix):
            return await call_next(request)

        raw_key = request.headers.get(API_KEY_HEADER)
        if not raw_key or not raw_key.strip():
            return _error_response(
                status.HTTP_401_UNAUTHORIZED,
                f"Missing {API_KEY_HEADER} header",
            )

        try:
            client = await resolve_api_key(raw_key.strip())
        except RuntimeError as exc:
            detail = str(exc) if settings.debug else "Authentication service unavailable"
            return _error_response(status.HTTP_503_SERVICE_UNAVAILABLE, detail)
        except Exception:
            return _error_response(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Authentication service unavailable",
            )

        if client is None:
            return _error_response(
                status.HTTP_401_UNAUTHORIZED,
                "Invalid or inactive API key",
            )

        allowed, remaining, retry_after = await enforce_sliding_window_rpm(client)
        if not allowed:
            return _error_response(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Rate limit exceeded",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(client.rate_limit_rpm),
                    "X-RateLimit-Remaining": "0",
                },
            )

        request.state.current_client = client
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(client.rate_limit_rpm)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


def get_current_client(request: Request) -> CurrentClient:
    """Helper for route handlers to read the authenticated client."""
    client = getattr(request.state, "current_client", None)
    if client is None:
        raise RuntimeError(
            "current_client missing; is APIKeyAuthMiddleware installed?"
        )
    return client


__all__ = [
    "APIKeyAuthMiddleware",
    "CurrentClient",
    "enforce_sliding_window_rpm",
    "get_current_client",
    "hash_api_key",
    "resolve_api_key",
]
