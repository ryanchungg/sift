"""GET /usage — aggregated usage metrics for the authenticated client."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status

from app.api.v1.schemas import UsageSummaryResponse
from app.core.database import get_async_supabase_client
from app.middleware.auth import get_current_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["usage"])


def _month_bounds_utc(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return [start, end) for the current UTC calendar month."""
    current = now or datetime.now(timezone.utc)
    start = datetime(current.year, current.month, 1, tzinfo=timezone.utc)
    if current.month == 12:
        end = datetime(current.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(current.year, current.month + 1, 1, tzinfo=timezone.utc)
    return start, end


@router.get("/usage", response_model=UsageSummaryResponse)
async def get_usage(request: Request) -> UsageSummaryResponse:
    """Return current-month token and page totals for the caller."""
    client = get_current_client(request)
    supabase = await get_async_supabase_client()
    period_start, period_end = _month_bounds_utc()

    try:
        result = await (
            supabase.table("usage_logs")
            .select("pages_processed, prompt_tokens, completion_tokens")
            .eq("client_id", client.client_id)
            .gte("created_at", period_start.isoformat())
            .lt("created_at", period_end.isoformat())
            .execute()
        )
    except Exception as exc:
        logger.exception("Failed to load usage for client %s", client.client_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to load usage metrics",
        ) from exc

    rows = result.data or []
    pages = sum(int(r.get("pages_processed") or 0) for r in rows)
    prompt = sum(int(r.get("prompt_tokens") or 0) for r in rows)
    completion = sum(int(r.get("completion_tokens") or 0) for r in rows)

    return UsageSummaryResponse(
        client_id=client.client_id,
        period_start=period_start,
        period_end=period_end,
        job_count=len(rows),
        pages_processed=pages,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
    )
